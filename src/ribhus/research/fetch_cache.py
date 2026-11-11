"""In-memory + optional disk cache for HTTP page bodies."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CachedFetch:
    url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
    redirect_chain: list[str]
    fetched_at: float


class FetchCache:
    def __init__(
        self,
        *,
        disk_dir: Path | None = None,
        ttl_seconds: float = 1800.0,
        max_memory: int = 64,
    ) -> None:
        self.disk_dir = Path(disk_dir) if disk_dir else None
        self.ttl_seconds = ttl_seconds
        self.max_memory = max_memory
        self._mem: dict[str, CachedFetch] = {}
        self._lock = threading.Lock()
        if self.disk_dir is not None:
            self.disk_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> CachedFetch | None:
        key = self._key(url)
        now = time.time()
        with self._lock:
            hit = self._mem.get(key)
            if hit is not None and now - hit.fetched_at <= self.ttl_seconds:
                return hit
            if hit is not None:
                self._mem.pop(key, None)
        if self.disk_dir is None:
            return None
        path = self.disk_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(raw.get("fetched_at") or 0)
            if time.time() - fetched_at > self.ttl_seconds:
                path.unlink(missing_ok=True)
                return None
            item = CachedFetch(
                url=str(raw.get("url") or url),
                final_url=str(raw.get("final_url") or url),
                status_code=int(raw.get("status_code") or 0),
                content_type=str(raw.get("content_type") or ""),
                body=str(raw.get("body") or ""),
                redirect_chain=list(raw.get("redirect_chain") or []),
                fetched_at=fetched_at,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        with self._lock:
            self._mem[key] = item
            self._trim()
        return item

    def put(self, item: CachedFetch) -> None:
        key = self._key(item.url)
        with self._lock:
            self._mem[key] = item
            self._trim()
        if self.disk_dir is None:
            return
        path = self.disk_dir / f"{key}.json"
        payload = {
            "url": item.url,
            "final_url": item.final_url,
            "status_code": item.status_code,
            "content_type": item.content_type,
            "body": item.body[:500_000],
            "redirect_chain": item.redirect_chain[:20],
            "fetched_at": item.fetched_at,
        }
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass

    def _trim(self) -> None:
        if len(self._mem) <= self.max_memory:
            return
        ordered = sorted(self._mem.items(), key=lambda kv: kv[1].fetched_at)
        for key, _ in ordered[: max(0, len(self._mem) - self.max_memory)]:
            self._mem.pop(key, None)
