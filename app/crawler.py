from __future__ import annotations

from collections import deque
from urllib.parse import urlparse

from app.confluence_client import (
    ConfluenceClient,
    ConfluencePermissionError,
    ConfluenceRequestError,
)
from app.extractor import extract_from_api_payload, extract_from_html
from app.models import AgentConfig, CrawlStats, ExtractedPage
from app.scope_guard import page_in_scope, url_in_scope


class ConfluenceCrawler:
    def __init__(self, client: ConfluenceClient, config: AgentConfig) -> None:
        self.client = client
        self.config = config
        self.stats = CrawlStats()

    def _same_host(self, url: str) -> bool:
        target_host = urlparse(self.client.secrets.confluence_base_url).netloc
        return urlparse(url).netloc == target_host

    async def crawl(self) -> tuple[list[ExtractedPage], CrawlStats]:
        if self.config.mode == "api":
            pages = await self._crawl_api()
        else:
            pages = await self._crawl_html()
        return pages, self.stats

    async def _crawl_api(self) -> list[ExtractedPage]:
        seed_page_id = self.config.start_page_id
        if not seed_page_id and self.config.start_url:
            seed_page_id = self.client.extract_page_id_from_url(self.config.start_url)

        if not seed_page_id:
            raise ValueError("API 模式需要 start_page_id，或提供可解析 pageId 的 start_url。")

        queue: deque[tuple[str, int]] = deque([(seed_page_id, 0)])
        seen_ids: set[str] = set()
        pages: list[ExtractedPage] = []

        while queue and len(pages) < self.config.max_pages:
            page_id, depth = queue.popleft()
            if page_id in seen_ids or depth > self.config.max_depth:
                continue

            seen_ids.add(page_id)
            self.stats.visited += 1

            try:
                payload = await self.client.get_page(page_id)
            except ConfluencePermissionError:
                self.stats.skipped_permission += 1
                continue
            except ConfluenceRequestError:
                self.stats.skipped_error += 1
                continue

            page = extract_from_api_payload(
                payload=payload,
                base_url=self.client.secrets.confluence_base_url,
                depth=depth,
            )
            if not page_in_scope(page, self.config.scope):
                self.stats.skipped_out_of_scope += 1
                continue

            pages.append(page)
            self.stats.collected += 1

            if depth >= self.config.max_depth:
                continue

            try:
                children = await self.client.get_child_pages(page_id)
            except ConfluencePermissionError:
                self.stats.skipped_permission += 1
                children = []
            except ConfluenceRequestError:
                self.stats.skipped_error += 1
                children = []

            for child in children:
                child_id = child.get("id")
                if child_id:
                    queue.append((str(child_id), depth + 1))

            for link in page.links:
                if not self._same_host(link.url) or not url_in_scope(link.url, self.config.scope):
                    continue
                linked_page_id = self.client.extract_page_id_from_url(link.url)
                if linked_page_id:
                    queue.append((linked_page_id, depth + 1))

        return pages

    async def _crawl_html(self) -> list[ExtractedPage]:
        seed_url = self.config.start_url
        if not seed_url and self.config.start_page_id:
            seed_url = (
                f"{self.client.secrets.confluence_base_url}/pages/viewpage.action"
                f"?pageId={self.config.start_page_id}"
            )

        if not seed_url:
            raise ValueError("HTML 模式需要 start_url，或提供 start_page_id。")

        queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
        seen_urls: set[str] = set()
        pages: list[ExtractedPage] = []

        while queue and len(pages) < self.config.max_pages:
            url, depth = queue.popleft()
            if url in seen_urls or depth > self.config.max_depth:
                continue

            seen_urls.add(url)
            if not self._same_host(url) or not url_in_scope(url, self.config.scope):
                self.stats.skipped_out_of_scope += 1
                continue

            self.stats.visited += 1

            try:
                html = await self.client.fetch_html(url)
            except ConfluencePermissionError:
                self.stats.skipped_permission += 1
                continue
            except ConfluenceRequestError:
                self.stats.skipped_error += 1
                continue

            page = extract_from_html(url=url, html=html, depth=depth)
            if not page_in_scope(page, self.config.scope):
                self.stats.skipped_out_of_scope += 1
                continue

            pages.append(page)
            self.stats.collected += 1

            if depth >= self.config.max_depth:
                continue

            for link in page.links:
                if link.url not in seen_urls and self._same_host(link.url):
                    queue.append((link.url, depth + 1))

        return pages
