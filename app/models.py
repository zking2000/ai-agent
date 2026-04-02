from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Mode = Literal["api", "html"]
OutputFormat = Literal["markdown", "json"]
SummaryMode = Literal["llm", "fallback"]
LLMApiStyle = Literal["auto", "chat_completions", "responses"]


class ScopeConfig(BaseModel):
    allowed_space: str | None = None
    allowed_parent_page_id: str | None = None
    allowed_url_prefixes: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    enabled: bool = True
    api_style: LLMApiStyle = "auto"
    temperature: float = 0.2
    max_input_chars: int = 16000


class AgentConfig(BaseModel):
    mode: Mode = "api"
    start_page_id: str | None = None
    start_url: str | None = None
    max_depth: int = 2
    max_pages: int = 20
    output_format: OutputFormat = "markdown"
    output_file: str = "output/summary.md"
    topic: str = "总结页面中的项目背景、关键结论和行动项。"
    answer_language: str = "zh-CN"
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


class PageLink(BaseModel):
    url: str
    title: str | None = None
    source_url: str | None = None


class ExtractedPage(BaseModel):
    page_id: str | None = None
    url: str
    title: str
    text: str
    html: str | None = None
    space_key: str | None = None
    parent_page_id: str | None = None
    ancestor_page_ids: list[str] = Field(default_factory=list)
    depth: int = 0
    links: list[PageLink] = Field(default_factory=list)
    skipped_reason: str | None = None


class CrawlStats(BaseModel):
    visited: int = 0
    collected: int = 0
    skipped_out_of_scope: int = 0
    skipped_permission: int = 0
    skipped_error: int = 0


class SummaryResult(BaseModel):
    topic: str
    mode: Mode
    pages: list[ExtractedPage]
    stats: CrawlStats
    summary_mode: SummaryMode
    summary_reason: str | None = None
    summary_markdown: str


class RuntimeSecrets(BaseModel):
    confluence_base_url: str
    confluence_email: str | None = None
    confluence_api_token: str | None = None
    confluence_bearer_token: str | None = None
    html_cookie: str | None = None
    confluence_ssl_verify: bool = True
    confluence_ca_bundle: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_ssl_verify: bool = True
    llm_ca_bundle: str | None = None
