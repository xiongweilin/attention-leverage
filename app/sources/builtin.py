from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser

from .base import Source
from .utils import parse_datetime, strip_html
from ..models import RawItem, SourceQuery


class GoogleNewsSource(Source):
    name = "google_news"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        q = quote_plus(query.query)
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        r = await self.client.get(url)
        r.raise_for_status()
        feed = feedparser.loads(r.content)
        out = []
        for e in feed.entries[: query.limit]:
            out.append(self.item(
                title=e.get("title", ""), url=e.get("link", ""),
                summary=strip_html(e.get("summary", "")),
                published_at=parse_datetime(e.get("published_parsed") or e.get("published")), query=query.query,
            ))
        return out


class GDELTSource(Source):
    name = "gdelt"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        params = {
            "query": query.query,
            "mode": "ArtList",
            "maxrecords": query.limit,
            "format": "json",
            "sort": "HybridRel",
            "timespan": f"{max(1, int(horizon_hours))}h",
        }
        r = await self.client.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params)
        r.raise_for_status()
        out = []
        for a in r.json().get("articles", [])[: query.limit]:
            out.append(self.item(
                title=a.get("title", ""), url=a.get("url", ""), summary=a.get("seendate", ""),
                published_at=parse_datetime(a.get("seendate")), query=query.query,
                metadata={"domain": a.get("domain"), "language": a.get("language"), "country": a.get("sourcecountry")},
            ))
        return out


class HackerNewsSource(Source):
    name = "hackernews"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=horizon_hours)).timestamp())
        params = {"query": query.query, "tags": "story", "hitsPerPage": query.limit, "numericFilters": f"created_at_i>{cutoff}"}
        r = await self.client.get("https://hn.algolia.com/api/v1/search_by_date", params=params)
        r.raise_for_status()
        out = []
        for h in r.json().get("hits", [])[: query.limit]:
            item_url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append(self.item(
                title=h.get("title") or h.get("story_title") or "", url=item_url,
                summary=h.get("story_text") or "", published_at=parse_datetime(h.get("created_at")), query=query.query,
                metadata={"points": h.get("points"), "comments": h.get("num_comments"), "author": h.get("author")},
            ))
        return out


class GitHubSource(Source):
    name = "github"

    def __init__(self, client, token: str = ""):
        super().__init__(client)
        self.token = token

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        since = (datetime.now(timezone.utc) - timedelta(hours=horizon_hours)).date().isoformat()
        q = f"{query.query} pushed:>={since}"
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = await self.client.get("https://api.github.com/search/repositories", params={"q": q, "sort": "updated", "order": "desc", "per_page": query.limit}, headers=headers)
        r.raise_for_status()
        out = []
        for repo in r.json().get("items", [])[: query.limit]:
            out.append(self.item(
                title=repo.get("full_name", ""), url=repo.get("html_url", ""), summary=repo.get("description") or "",
                published_at=parse_datetime(repo.get("pushed_at") or repo.get("updated_at")), query=query.query,
                metadata={"stars": repo.get("stargazers_count"), "language": repo.get("language")},
            ))
        return out


class OpenAlexSource(Source):
    name = "openalex"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        since = (datetime.now(timezone.utc) - timedelta(hours=horizon_hours)).date().isoformat()
        params = {"search": query.query, "per-page": query.limit, "filter": f"from_publication_date:{since}"}
        r = await self.client.get("https://api.openalex.org/works", params=params)
        r.raise_for_status()
        out = []
        for w in r.json().get("results", [])[: query.limit]:
            primary = w.get("primary_location") or {}
            out.append(self.item(
                title=w.get("display_name", ""), url=(primary.get("landing_page_url") or w.get("doi") or w.get("id") or ""),
                summary="", published_at=parse_datetime(w.get("publication_date")), query=query.query,
                metadata={"citations": w.get("cited_by_count"), "type": w.get("type")},
            ))
        return out


class ArxivSource(Source):
    name = "arxiv"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        params = {"search_query": f'all:"{query.query}"', "start": 0, "max_results": query.limit, "sortBy": "submittedDate", "sortOrder": "descending"}
        r = await self.client.get("https://export.arxiv.org/api/query", params=params)
        r.raise_for_status()
        feed = feedparser.loads(r.content)
        out = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=horizon_hours * 1.5)
        for e in feed.entries:
            published = parse_datetime(e.get("published"))
            if published and published < cutoff:
                continue
            out.append(self.item(
                title=e.get("title", ""), url=e.get("link", ""), summary=strip_html(e.get("summary", "")),
                published_at=published, query=query.query,
            ))
        return out[: query.limit]


class CrossrefSource(Source):
    name = "crossref"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        since = (datetime.now(timezone.utc) - timedelta(hours=horizon_hours)).date().isoformat()
        params = {"query.bibliographic": query.query, "rows": query.limit, "filter": f"from-pub-date:{since}"}
        r = await self.client.get("https://api.crossref.org/works", params=params)
        r.raise_for_status()
        out = []
        for w in r.json().get("message", {}).get("items", [])[: query.limit]:
            title = (w.get("title") or [""])[0]
            out.append(self.item(
                title=title, url=w.get("URL", ""), summary=(w.get("abstract") or ""),
                published_at=_crossref_date(w), query=query.query,
                metadata={"publisher": w.get("publisher"), "type": w.get("type")},
            ))
        return out


def _crossref_date(w: dict):
    parts = (((w.get("published-online") or w.get("published-print") or w.get("created") or {}).get("date-parts") or [[]])[0])
    if not parts:
        created = (w.get("created") or {}).get("date-time")
        return parse_datetime(created)
    parts = list(parts) + [1, 1]
    try:
        return datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
    except Exception:
        return None


class StackExchangeSource(Source):
    name = "stackexchange"

    async def search(self, query: SourceQuery, horizon_hours: int) -> list[RawItem]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=horizon_hours)).timestamp())
        params = {"site": "stackoverflow", "q": query.query, "sort": "creation", "order": "desc", "pagesize": query.limit, "fromdate": cutoff}
        r = await self.client.get("https://api.stackexchange.com/2.3/search/advanced", params=params)
        r.raise_for_status()
        out = []
        for x in r.json().get("items", [])[: query.limit]:
            out.append(self.item(
                title=x.get("title", ""), url=x.get("link", ""), summary="",
                published_at=datetime.fromtimestamp(x.get("creation_date", 0), tz=timezone.utc), query=query.query,
                metadata={"score": x.get("score"), "answers": x.get("answer_count"), "is_answered": x.get("is_answered")},
            ))
        return out
