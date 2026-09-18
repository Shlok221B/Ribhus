from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ribhus.channels.whatsapp_web.selectors import WHATSAPP_HOSTS
from ribhus.tools.base import Tool

_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "button",
)
_MAIN_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".article-body",
    ".entry-content",
    "#content",
    ".content",
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def html_to_text(html: str, *, max_chars: int = 12_000) -> tuple[str, str]:
    """Return (title, cleaned body text) from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())
    elif soup.find("h1"):
        title = " ".join(soup.find("h1").get_text(" ", strip=True).split())

    root = None
    for selector in _MAIN_SELECTORS:
        root = soup.select_one(selector)
        if root and root.get_text(strip=True):
            break
    if root is None:
        root = soup.body or soup

    text = root.get_text("\n", strip=True)
    # Collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return title, text


class WebExtractTool(Tool):
    name = "web_extract"
    description = (
        "Fetch a public URL and return cleaned page text (title + main content). "
        "Prefer this over http_request for articles and docs. "
        "Use browser if the page needs login, JS-heavy rendering, or clicking."
    )
    risk_level = "low"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full http(s) URL to extract",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters of body text (default 12000, max 30000)",
                    "default": 12000,
                },
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        url = str(arguments.get("url") or "").strip()
        if not url:
            return "Error: url is required"
        if not url.startswith(("http://", "https://")):
            return "Error: url must start with http:// or https://"

        host = _host(url)
        if host in WHATSAPP_HOSTS or host.endswith(".whatsapp.com"):
            return (
                "Error: use whatsapp_* tools for WhatsApp Web, not web_extract."
            )

        max_chars = int(arguments.get("max_chars") or 12_000)
        max_chars = max(1000, min(max_chars, 30_000))

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Ribhus/0.1; +https://github.com/ribhus)"
            ),
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=30.0, headers=headers
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as extra:
            return f"Error fetching {url}: {extra}"

        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code >= 400:
            return (
                f"Error: HTTP {response.status_code} for {url}\n"
                f"Content-Type: {content_type}"
            )

        if "html" not in content_type and not response.text.lstrip().startswith(
            ("<!DOCTYPE", "<!doctype", "<html", "<HTML")
        ):
            # Plain text / json-ish — return truncated raw
            body = response.text
            if len(body) > max_chars:
                body = body[:max_chars] + "\n...[truncated]"
            return (
                f"URL: {response.url}\n"
                f"Status: {response.status_code}\n"
                f"Content-Type: {content_type}\n\n"
                f"{body}"
            )

        title, text = html_to_text(response.text, max_chars=max_chars)
        if not text.strip():
            return (
                f"URL: {response.url}\n"
                f"Status: {response.status_code}\n"
                "Error: no readable text extracted. Try the browser tool."
            )
        title_line = f"Title: {title}\n" if title else ""
        return (
            f"URL: {response.url}\n"
            f"Status: {response.status_code}\n"
            f"{title_line}\n"
            f"{text}"
        )
