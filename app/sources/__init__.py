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
from .environment import (
    GrantsGovSource, OpenAlexAuthorsSource, OpenAlexInstitutionsSource,
    ProPublicaNonprofitsSource, WikidataSource,
)
from .transport import SourceTransport, SourceTransportPolicy


def build_sources(
    client: httpx.AsyncClient,
    settings: Settings,
    direct_client: httpx.AsyncClient | None = None,
) -> dict[str, Source]:
    cfg = settings.source_config.get('sources', {})
    feeds = cfg.get('rss', {}).get('feeds', [])
    boards = cfg.get('greenhouse', {}).get('boards', [])

    def source_client(name: str) -> SourceTransport:
        source_cfg = cfg.get(name, {})
        policy = SourceTransportPolicy.from_config(source_cfg.get('transport'))
        return SourceTransport(name, client, direct_client, policy)

    candidates: dict[str, Source] = {
        'google_news': GoogleNewsSource(source_client('google_news')),
        'gdelt': GDELTSource(source_client('gdelt')),
        'hackernews': HackerNewsSource(source_client('hackernews')),
        'bluesky': BlueskySource(source_client('bluesky')),
        'github': GitHubSource(source_client('github'), settings.github_token),
        'npm': NpmSource(source_client('npm')),
        'crates': CratesSource(source_client('crates')),
        'stackexchange': StackExchangeSource(source_client('stackexchange')),
        'openalex': OpenAlexSource(source_client('openalex')),
        'arxiv': ArxivSource(source_client('arxiv')),
        'crossref': CrossrefSource(source_client('crossref')),
        'europepmc': EuropePMCSource(source_client('europepmc')),
        'clinicaltrials': ClinicalTrialsSource(source_client('clinicaltrials')),
        'federal_register': FederalRegisterSource(source_client('federal_register')),
        'worldbank': WorldBankSource(source_client('worldbank')),
        'cisa_kev': CisaKevSource(source_client('cisa_kev')),
        'nvd': NvdSource(source_client('nvd'), settings.nvd_api_key),
        'usgs': UsgsSource(source_client('usgs')),
        'nasa_eonet': NasaEonetSource(source_client('nasa_eonet')),
        'wikidata': WikidataSource(source_client('wikidata')),
        'openalex_authors': OpenAlexAuthorsSource(source_client('openalex_authors')),
        'openalex_institutions': OpenAlexInstitutionsSource(source_client('openalex_institutions')),
        'propublica_nonprofits': ProPublicaNonprofitsSource(source_client('propublica_nonprofits')),
        'grants_gov': GrantsGovSource(source_client('grants_gov')),
        'rss': RSSSource(source_client('rss'), feeds),
    }
    if settings.sec_user_agent:
        candidates['sec'] = SECSource(source_client('sec'), settings.sec_user_agent)
    if settings.reliefweb_appname:
        candidates['reliefweb'] = ReliefWebSource(source_client('reliefweb'), settings.reliefweb_appname)
    if boards:
        candidates['greenhouse'] = GreenhouseSource(source_client('greenhouse'), boards)

    return {
        name: source for name, source in candidates.items()
        if cfg.get(name, {}).get('enabled', True)
    }
