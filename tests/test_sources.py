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
        assert len(sources) >= 26
        categories={s.profile.category for s in sources.values()}
        assert len(categories) >= 18
        assert {
            'wikidata','openalex_authors','openalex_institutions',
            'propublica_nonprofits','grants_gov','rss','greenhouse',
        }.issubset(sources)

        rss_config=settings.source_config['sources']['rss']['feeds']
        greenhouse_config=settings.source_config['sources']['greenhouse']['boards']
        assert len(rss_config) >= 24
        assert len(greenhouse_config) >= 10
        assert {x['token'] for x in greenhouse_config} >= {
            'figma','coinbase','scaleai','airtable','dropbox',
            'klaviyo','vercel','xai','upstart','intercom',
        }
    finally:
        import asyncio
        asyncio.run(client.aclose())
