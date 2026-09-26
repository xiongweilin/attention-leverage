from __future__ import annotations

import asyncio

import feedparser

from .base import Source
from .utils import parse_datetime, strip_html
from ..models import RawItem, SourceQuery


class RSSSource(Source):
    name = "rss"

    def __init__(self, client, feeds: list[str]):
        super().__init__(client)
        self.feeds = feeds

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        if not self.feeds:
            return []
        results = await asyncio.gather(*(self._feed(url, query) for url in self.feeds), return_exceptions=True)
        out: list[RawItem] = []
        for result in results:
            if isinstance(result, list):
                out.extend(result)
        terms = [x.lower() for x in query.query.split() if len(x) >= 3]
        if terms:
            out.sort(key=lambda x: sum(t in f"{x.title} {x.summary}".lower() for t in terms), reverse=True)
        return out[: query.limit]

    async def _feed(self, url: str, query: SourceQuery) -> list[RawItem]:
        r = await self.client.get(url)
        r.raise_for_status()
        feed = feedparser.loads(r.content)
        out = []
        for e in feed.entries[:30]:
            out.append(self.item(
                title=e.get("title", ""), url=e.get("link", ""), summary=strip_html(e.get("summary", "")),
                published_at=parse_datetime(e.get("published_parsed") or e.get("updated_parsed") or e.get("published")),
                query=query.query, metadata={"feed": url},
            ))
        return out
