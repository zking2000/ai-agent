from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.models import ExtractedPage, PageLink


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _normalize_link(base_url: str, href: str) -> str | None:
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    if href.startswith("mailto:"):
        return None
    absolute = urljoin(base_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    return absolute


def _collect_links(soup: BeautifulSoup, base_url: str, source_url: str) -> list[PageLink]:
    links: list[PageLink] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        normalized = _normalize_link(base_url, anchor.get("href", ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        title = anchor.get_text(" ", strip=True) or None
        links.append(PageLink(url=normalized, title=title, source_url=source_url))
    return links


def extract_from_api_payload(payload: dict[str, Any], base_url: str, depth: int) -> ExtractedPage:
    body_html = payload.get("body", {}).get("storage", {}).get("value", "") or ""
    soup = BeautifulSoup(body_html, "html.parser")
    text = _clean_text(soup.get_text("\n", strip=True))

    webui_path = payload.get("_links", {}).get("webui", "")
    page_url = urljoin(f"{base_url}/", webui_path.lstrip("/"))
    ancestors = payload.get("ancestors", [])

    return ExtractedPage(
        page_id=str(payload.get("id")) if payload.get("id") else None,
        url=page_url,
        title=payload.get("title", "Untitled"),
        text=text,
        html=body_html,
        space_key=payload.get("space", {}).get("key"),
        parent_page_id=str(ancestors[-1]["id"]) if ancestors else None,
        ancestor_page_ids=[str(item["id"]) for item in ancestors if item.get("id")],
        depth=depth,
        links=_collect_links(soup, base_url, page_url),
    )


def extract_from_html(url: str, html: str, depth: int) -> ExtractedPage:
    soup = BeautifulSoup(html, "html.parser")
    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title and soup.title.get_text(strip=True)
        else "Untitled"
    )

    main_node = (
        soup.select_one("#main-content")
        or soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one(".wiki-content")
        or soup.body
        or soup
    )
    text = _clean_text(main_node.get_text("\n", strip=True))
    space_meta = soup.select_one('meta[name="ajs-space-key"]')
    page_id_meta = soup.select_one('meta[name="ajs-page-id"]')
    parent_meta = soup.select_one('meta[name="ajs-parent-page-id"]')

    return ExtractedPage(
        page_id=page_id_meta.get("content") if page_id_meta else None,
        url=url,
        title=title,
        text=text,
        html=str(main_node),
        space_key=space_meta.get("content") if space_meta else None,
        parent_page_id=parent_meta.get("content") if parent_meta else None,
        depth=depth,
        links=_collect_links(main_node if isinstance(main_node, BeautifulSoup) else BeautifulSoup(str(main_node), "html.parser"), url, url),
    )
