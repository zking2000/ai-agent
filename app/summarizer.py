from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.models import AgentConfig, ExtractedPage, RuntimeSecrets, SummaryResult


class Summarizer:
    def __init__(self, config: AgentConfig, secrets: RuntimeSecrets) -> None:
        self.config = config
        self.secrets = secrets

    def _build_context(self, pages: list[ExtractedPage]) -> str:
        parts: list[str] = []
        remaining = self.config.llm.max_input_chars
        for page in pages:
            chunk = (
                f"Title: {page.title}\n"
                f"URL: {page.url}\n"
                f"Space: {page.space_key or 'unknown'}\n"
                f"Content:\n{page.text}\n"
            )
            if remaining <= 0:
                break
            chunk = chunk[:remaining]
            parts.append(chunk)
            remaining -= len(chunk)
        return "\n---\n".join(parts)

    def _llm_verify_value(self) -> bool | str:
        if self.secrets.llm_ca_bundle:
            return self.secrets.llm_ca_bundle
        return self.secrets.llm_ssl_verify

    async def _post_llm(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.secrets.llm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=60.0,
                verify=self._llm_verify_value(),
            ) as client:
                response = await client.post(
                    f"{self.secrets.llm_base_url.rstrip('/')}/{endpoint.lstrip('/')}",
                    headers=headers,
                    json=payload,
                )
        except httpx.ConnectError as exc:
            raise ValueError(
                "LLM 连接失败，可能是模型网关证书未被信任。"
                "请设置 LLM_CA_BUNDLE，或临时设置 LLM_SSL_VERIFY=false。"
            ) from exc

        if response.status_code >= 400:
            raise ValueError(
                f"{endpoint} 调用失败: {response.status_code} {response.text[:400]}"
            )

        return response.json()

    async def _post_llm_with_variants(
        self,
        endpoint: str,
        payload_variants: list[dict[str, Any]],
    ) -> dict[str, Any]:
        errors: list[str] = []
        for index, payload in enumerate(payload_variants, start=1):
            try:
                return await self._post_llm(endpoint, payload)
            except Exception as exc:
                errors.append(f"variant_{index}: {exc}")
        raise ValueError(" ; ".join(errors))

    @staticmethod
    def _extract_chat_text(data: dict[str, Any]) -> str:
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

    @staticmethod
    def _extract_responses_text(data: dict[str, Any]) -> str:
        if data.get("output_text"):
            return str(data["output_text"]).strip()

        outputs = data.get("output", [])
        text_chunks: list[str] = []
        for item in outputs:
            for content in item.get("content", []):
                text_value = content.get("text")
                if text_value:
                    text_chunks.append(str(text_value))
        return "\n".join(text_chunks).strip()

    async def _call_chat_completions(self, prompt: str, user_content: str) -> str:
        payload_variants = [
            {
                "model": self.secrets.llm_model,
                "temperature": self.config.llm.temperature,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            },
            {
                "model": self.secrets.llm_model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            },
        ]
        data = await self._post_llm_with_variants("chat/completions", payload_variants)
        text = self._extract_chat_text(data)
        if not text:
            raise ValueError("chat/completions 返回成功，但没有可用文本。")
        return text

    async def _call_responses(self, prompt: str, user_content: str) -> str:
        payload_variants = [
            {
                "model": self.secrets.llm_model,
                "temperature": self.config.llm.temperature,
                "instructions": prompt,
                "input": user_content,
            },
            {
                "model": self.secrets.llm_model,
                "instructions": prompt,
                "input": user_content,
            },
            {
                "model": self.secrets.llm_model,
                "temperature": self.config.llm.temperature,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_content}]},
                ],
            },
            {
                "model": self.secrets.llm_model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_content}]},
                ],
            },
            {
                "model": self.secrets.llm_model,
                "input": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            },
        ]
        data = await self._post_llm_with_variants("responses", payload_variants)
        text = self._extract_responses_text(data)
        if not text:
            raise ValueError("responses 返回成功，但没有可用文本。")
        return text

    async def _llm_summary(self, pages: list[ExtractedPage]) -> tuple[str, str]:
        if not self.secrets.llm_base_url or not self.secrets.llm_api_key or not self.secrets.llm_model:
            raise ValueError("LLM 未配置完整，无法调用模型总结。")

        answer_language = self.config.answer_language or "zh-CN"
        prompt = (
            "你是一个Confluence项目信息压缩助手。"
            "请只保留与用户 topic 明确相关的信息，并拒绝扩展到无关页面。"
            f"无论源页面是什么语言，你都必须使用 {answer_language} 输出。"
            "除产品名、专有名词、协议名外，其余叙述都要翻译成目标语言。"
            "输出必须简洁，使用 markdown，包含以下小节：\n"
            "## 结论\n## 关键点\n## 行动项\n## 来源页面\n"
            "如果信息不足，直接说明“信息不足”。不要长篇复述原文。"
        )
        user_content = (
            f"Topic:\n{self.config.topic}\n\n"
            f"Answer language:\n{answer_language}\n\n"
            f"Pages:\n{self._build_context(pages)}"
        )
        api_style = self.config.llm.api_style
        errors: list[str] = []

        if api_style == "responses":
            return (
                await self._call_responses(prompt, user_content),
                "LLM summary completed successfully via responses API.",
            )

        if api_style == "chat_completions":
            return (
                await self._call_chat_completions(prompt, user_content),
                "LLM summary completed successfully via chat/completions API.",
            )

        for style in ("responses", "chat_completions"):
            try:
                if style == "responses":
                    return (
                        await self._call_responses(prompt, user_content),
                        "LLM summary completed successfully via responses API.",
                    )
                return (
                    await self._call_chat_completions(prompt, user_content),
                    "LLM summary completed successfully via chat/completions API.",
                )
            except Exception as exc:
                errors.append(f"{style}: {exc}")

        raise ValueError(" ; ".join(errors))

    def _fallback_summary(self, pages: list[ExtractedPage]) -> str:
        if not pages:
            return "## 结论\n信息不足。\n\n## 关键点\n- 未抓取到可用页面。\n\n## 行动项\n- 检查页面权限、起始页面和 scope 配置。\n\n## 来源页面\n- 无"

        key_points = []
        action_items = []
        for page in pages[:5]:
            preview = page.text.replace("\n", " ")
            preview = preview[:180] + ("..." if len(preview) > 180 else "")
            key_points.append(f"- `{page.title}`: {preview}")
            if "todo" in page.text.lower() or "action" in page.text.lower() or "待办" in page.text:
                action_items.append(f"- 查看 `{page.title}` 中的待办或行动项。")

        if not action_items:
            action_items.append("- 未发现明确行动项，建议人工确认关键页面。")

        sources = "\n".join(f"- [{page.title}]({page.url})" for page in pages[:10])
        return (
            "## 结论\n"
            f"围绕 topic 抓取了 {len(pages)} 个页面，以下仅保留高相关内容。"
            "当前为本地降级摘要，原文若为英文，片段可能保持原语言。\n\n"
            "## 关键点\n"
            f"{chr(10).join(key_points)}\n\n"
            "## 行动项\n"
            f"{chr(10).join(action_items)}\n\n"
            "## 来源页面\n"
            f"{sources}"
        )

    async def summarize(self, pages: list[ExtractedPage], stats) -> SummaryResult:
        summary_markdown = ""
        summary_mode = "fallback"
        summary_reason: str | None = None
        if self.config.llm.enabled:
            try:
                summary_markdown, summary_reason = await self._llm_summary(pages)
                summary_mode = "llm"
            except Exception as exc:
                summary_markdown = self._fallback_summary(pages)
                summary_mode = "fallback"
                summary_reason = f"LLM unavailable, using fallback summary: {exc}"
        else:
            summary_markdown = self._fallback_summary(pages)
            summary_mode = "fallback"
            summary_reason = "LLM disabled in config."

        return SummaryResult(
            topic=self.config.topic,
            mode=self.config.mode,
            pages=pages,
            stats=stats,
            summary_mode=summary_mode,
            summary_reason=summary_reason,
            summary_markdown=summary_markdown,
        )


def write_output(result: SummaryResult, output_format: str, output_file: str) -> Path:
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "json":
        payload = result.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        path.write_text(result.summary_markdown, encoding="utf-8")

    return path
