from __future__ import annotations

from urllib.parse import urlparse

from app.models import ExtractedPage, ScopeConfig


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return "/"
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return prefix.rstrip("/") or "/"


def url_in_scope(url: str, scope: ScopeConfig) -> bool:
    if not scope.allowed_url_prefixes:
        return True

    path = urlparse(url).path.rstrip("/") or "/"
    prefixes = [_normalize_prefix(prefix) for prefix in scope.allowed_url_prefixes]
    return any(path.startswith(prefix) for prefix in prefixes)


def page_in_scope(page: ExtractedPage, scope: ScopeConfig) -> bool:
    if scope.allowed_space and page.space_key != scope.allowed_space:
        return False

    if scope.allowed_parent_page_id:
        allowed_parent = scope.allowed_parent_page_id
        is_descendant = (
            allowed_parent == page.page_id
            or allowed_parent == page.parent_page_id
            or allowed_parent in page.ancestor_page_ids
        )
        if not is_descendant:
            return False

    if not url_in_scope(page.url, scope):
        return False

    return True
