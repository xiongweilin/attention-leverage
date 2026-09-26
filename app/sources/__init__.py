from __future__ import annotations

import httpx

from ..config import Settings
from .base import Source
from .builtin import (
    ArxivSource, BlueskySource, CisaKevSource, ClinicalTrialsSource, CratesSource,
    CrossrefSource, EuropePMCSource, FederalRegisterSource, GDELTSource, GitHubSource,
    GoogleNewsSource, GreenhouseSource, HackerNewsSource, NasaEonetSource, NpmSource,
    NvdSource, OpenAlexSource, RSSSource, ReliefWebSource, SECSource, StackExchangeSource,
    UsgsSource, WorldBankSource,
)


def build_sources(client: httpx.AsyncClient, settings: Settings) -> dict[str, Source]:
    cfg = settings.source_config.get('sources', {})
    feeds = cfg.get('rss', {}).get('feeds', [])
    boards = cfg.get('greenhouse', {}).get('boards', [])
    candidates: dict[str, Source] = {
        'google_news': GoogleNewsSource(client), 'gdelt': GDELTSource(client),
        'hackernews': HackerNewsSource(client), 'bluesky': BlueskySource(client),
        'github': GitHubSource(client, settings.github_token), 'npm': NpmSource(client),
        'crates': CratesSource(client), 'stackexchange': StackExchangeSource(client),
        'openalex': OpenAlexSource(client), 'arxiv': ArxivSource(client),
        'crossref': CrossrefSource(client), 'europepmc': EuropePMCSource(client),
        'clinicaltrials': ClinicalTrialsSource(client), 'federal_register': FederalRegisterSource(client),
        'worldbank': WorldBankSource(client), 'cisa_kev': CisaKevSource(client),
        'nvd': NvdSource(client, settings.nvd_api_key), 'usgs': UsgsSource(client),
        'nasa_eonet': NasaEonetSource(client), 'rss': RSSSource(client, feeds),
    }
    if settings.sec_user_agent:
        candidates['sec'] = SECSource(client, settings.sec_user_agent)
    if settings.reliefweb_appname:
        candidates['reliefweb'] = ReliefWebSource(client, settings.reliefweb_appname)
    if boards:
        candidates['greenhouse'] = GreenhouseSource(client, boards)

    return {
        name: source for name, source in candidates.items()
        if cfg.get(name, {}).get('enabled', True)
    }
