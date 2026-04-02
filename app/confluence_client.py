from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from app.models import RuntimeSecrets


class ConfluencePermissionError(Exception):
    """Raised when the current credentials cannot access a page."""


class ConfluenceRequestError(Exception):
    """Raised when a Confluence request fails unexpectedly."""


class ConfluenceClient:
    def __init__(self, secrets: RuntimeSecrets, timeout: float = 20.0) -> None:
        self.secrets = secrets
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=self._default_headers(),
            verify=self._verify_value(),
        )

    def _verify_value(self) -> bool | str:
        if self.secrets.confluence_ca_bundle:
            return self.secrets.confluence_ca_bundle
        return self.secrets.confluence_ssl_verify

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/html;q=0.9",
            "User-Agent": "confluence-ai-agent/0.1",
        }
        auth_headers = self._auth_headers()
        headers.update(auth_headers)
        if self.secrets.html_cookie:
            headers["Cookie"] = self.secrets.html_cookie
        return headers

    def _auth_headers(self) -> dict[str, str]:
        if self.secrets.confluence_bearer_token:
            return {"Authorization": f"Bearer {self.secrets.confluence_bearer_token}"}

        if self.secrets.confluence_email and self.secrets.confluence_api_token:
            raw = f"{self.secrets.confluence_email}:{self.secrets.confluence_api_token}"
            token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
            return {"Authorization": f"Basic {token}"}

        return {}

    def page_url_from_webui_path(self, path: str) -> str:
        return urljoin(f"{self.secrets.confluence_base_url}/", path.lstrip("/"))

    @staticmethod
    def extract_page_id_from_url(url: str) -> str | None:
        patterns = [
            r"[?&]pageId=(\d+)",
            r"/pages/(\d+)",
            r"/pages/viewpage\.action\?pageId=(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def close(self) -> None:
        await self.client.aclose()

    async def get_page(self, page_id: str) -> dict[str, Any]:
        url = f"{self.secrets.confluence_base_url}/rest/api/content/{page_id}"
        params = {
            "expand": "body.storage,space,ancestors,version",
        }
        try:
            response = await self.client.get(url, params=params)
        except httpx.ConnectError as exc:
            raise ConfluenceRequestError(
                "连接 Confluence 失败，可能是目标站点证书未被信任。"
                "请设置 CONFLUENCE_CA_BUNDLE 指向 CA 证书，"
                "或临时设置 CONFLUENCE_SSL_VERIFY=false。"
            ) from exc
        if response.status_code in {401, 403, 404}:
            raise ConfluencePermissionError(f"页面 {page_id} 无权限或不存在。")
        if response.status_code >= 400:
            raise ConfluenceRequestError(
                f"获取页面失败: {response.status_code} {response.text[:200]}"
            )
        return response.json()

    async def get_child_pages(self, page_id: str, limit: int = 100) -> list[dict[str, Any]]:
        start = 0
        results: list[dict[str, Any]] = []

        while True:
            url = f"{self.secrets.confluence_base_url}/rest/api/content/{page_id}/child/page"
            params = {
                "limit": limit,
                "start": start,
                "expand": "space,ancestors",
            }
            try:
                response = await self.client.get(url, params=params)
            except httpx.ConnectError as exc:
                raise ConfluenceRequestError(
                    "连接 Confluence 失败，可能是目标站点证书未被信任。"
                    "请设置 CONFLUENCE_CA_BUNDLE 指向 CA 证书，"
                    "或临时设置 CONFLUENCE_SSL_VERIFY=false。"
                ) from exc
            if response.status_code in {401, 403, 404}:
                raise ConfluencePermissionError(f"无法访问子页面列表: {page_id}")
            if response.status_code >= 400:
                raise ConfluenceRequestError(
                    f"获取子页面失败: {response.status_code} {response.text[:200]}"
                )

            payload = response.json()
            batch = payload.get("results", [])
            results.extend(batch)

            size = payload.get("size", len(batch))
            if size == 0 or len(batch) < limit:
                break
            start += len(batch)

        return results

    async def fetch_html(self, url: str) -> str:
        try:
            response = await self.client.get(url, headers={"Accept": "text/html"})
        except httpx.ConnectError as exc:
            raise ConfluenceRequestError(
                "抓取 HTML 失败，可能是目标站点证书未被信任。"
                "请设置 CONFLUENCE_CA_BUNDLE 指向 CA 证书，"
                "或临时设置 CONFLUENCE_SSL_VERIFY=false。"
            ) from exc
        if response.status_code in {401, 403, 404}:
            raise ConfluencePermissionError(f"无法抓取 HTML 页面: {url}")
        if response.status_code >= 400:
            raise ConfluenceRequestError(
                f"抓取 HTML 失败: {response.status_code} {response.text[:200]}"
            )
        return response.text
