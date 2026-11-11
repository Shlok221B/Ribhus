"""Lightweight robots.txt respect for research fetches."""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "RibhusResearch"
_CACHE_TTL_SECONDS = 3600.0


class RobotsCache:
    def __init__(self) -> None:
        self._parsers: dict[str, tuple[float, RobotFileParser | None]] = {}
        self._lock = asyncio.Lock()

    async def allowed(self, url: str, *, enabled: bool = True) -> bool:
        if not enabled:
            return True
        try:
            parsed = urlparse(url)
        except Exception:  # noqa: BLE001
            return True
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return True
        origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
        async with self._lock:
            cached = self._parsers.get(origin)
            now = time.monotonic()
            if cached is None or now - cached[0] > _CACHE_TTL_SECONDS:
                parser = await self._fetch(origin)
                self._parsers[origin] = (now, parser)
            else:
                parser = cached[1]
        if parser is None:
            # Fail open if robots.txt missing/unreachable (common for ATS)
            return True
        try:
            return bool(parser.can_fetch(_USER_AGENT, url))
        except Exception:  # noqa: BLE001
            return True

    async def _fetch(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                response = await client.get(
                    robots_url,
                    headers={"User-Agent": f"{_USER_AGENT}/0.1"},
                )
            if response.status_code >= 400:
                return None
            text = response.text or ""
            parser.parse(text.splitlines())
            return parser
        except Exception as exc:  # noqa: BLE001
            logger.debug("robots.txt fetch failed for %s: %s", origin, exc)
            return None


_SHARED = RobotsCache()


def shared_robots_cache() -> RobotsCache:
    return _SHARED
