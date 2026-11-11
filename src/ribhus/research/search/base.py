from __future__ import annotations

from typing import Protocol

from ribhus.research.models import SearchLead


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int = 8) -> list[SearchLead]:
        ...
