from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from ..models import RawItem, SourceProfile, SourceQuery


class Source(ABC):
    profile: SourceProfile

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @property
    def name(self) -> str:
        return self.profile.name

    @abstractmethod
    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        raise NotImplementedError

    def item(
        self, *, title: str, url: str, summary: str = '', published_at: datetime | None = None,
        query: str = '', metadata: dict | None = None, stable_key: str = '',
    ) -> RawItem:
        identity = stable_key or url or title
        raw_id = f'{self.name}\0{identity}'.encode('utf-8', errors='ignore')
        return RawItem(
            id=hashlib.sha1(raw_id).hexdigest()[:20], source=self.name,
            source_category=self.profile.category, title=(title or 'Untitled').strip(), url=url,
            summary=(summary or '').strip(), published_at=published_at, query=query,
            authority=self.profile.authority, metadata=metadata or {},
        )
