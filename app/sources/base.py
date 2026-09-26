from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from ..models import RawItem, SourceQuery


class Source(ABC):
    name: str

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        raise NotImplementedError

    def item(
        self,
        *,
        title: str,
        url: str,
        summary: str = "",
        published_at: datetime | None = None,
        query: str = "",
        metadata: dict | None = None,
    ) -> RawItem:
        raw_id = f"{self.name}\0{url}\0{title}".encode("utf-8", errors="ignore")
        return RawItem(
            id=hashlib.sha1(raw_id).hexdigest()[:16],
            source=self.name,
            title=(title or "Untitled").strip(),
            url=url,
            summary=(summary or "").strip(),
            published_at=published_at,
            query=query,
            metadata=metadata or {},
        )
