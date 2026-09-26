import httpx

from app.config import Settings
from app.sources import build_sources


def test_default_source_pool_is_highly_heterogeneous():
    settings=Settings.load()
    with httpx.Client():
        pass
    client=httpx.AsyncClient()
    try:
        sources=build_sources(client,settings)
        assert len(sources) >= 25
        categories={s.profile.category for s in sources.values()}
        assert len(categories) >= 17
        assert {
            'wikidata','openalex_authors','openalex_institutions',
            'propublica_nonprofits','grants_gov',
        }.issubset(sources)
    finally:
        import asyncio
        asyncio.run(client.aclose())
