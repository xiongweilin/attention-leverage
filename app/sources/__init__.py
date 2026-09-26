from __future__ import annotations

import httpx

from ..config import Settings
from .base import Source
from .builtin import (
    ArxivSource,
    CrossrefSource,
    GDELTSource,
    GitHubSource,
    GoogleNewsSource,
    HackerNewsSource,
    OpenAlexSource,
    StackExchangeSource,
)
from .rss import RSSSource


def build_sources(client: httpx.AsyncClient, settings: Settings) -> dict[str, Source]:
    cfg = settings.source_config.get("sources", {})
    candidates: dict[str, Source] = {
        "google_news": GoogleNewsSource(client),
        "gdelt": GDELTSource(client),
        "hackernews": HackerNewsSource(client),
        "github": GitHubSource(client, settings.github_token),
        "openalex": OpenAlexSource(client),
        "arxiv": ArxivSource(client),
        "crossref": CrossrefSource(client),
        "stackexchange": StackExchangeSource(client),
        "rss": RSSSource(client, cfg.get("rss", {}).get("feeds", [])),
    }
    return {
        name: source
        for name, source in candidates.items()
        if cfg.get(name, {}).get("enabled", True)
    }
