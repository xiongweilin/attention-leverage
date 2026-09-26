from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from ..models import SourceProfile
from .base import Source


def _profile(name: str, category: str, description: str, authority: str, signal_kind: str) -> SourceProfile:
    return SourceProfile(
        name=name,
        category=category,
        description=description,
        authority=authority,
        queryable=True,
        signal_kind=signal_kind,
    )


class WikidataSource(Source):
    profile = _profile(
        'wikidata',
        'knowledge_graph',
        'Structured public entity search for people, organizations, places and named environments.',
        'community',
        'entity',
    )

    async def search(self, query, horizon_hours):
        params = {
            'action': 'wbsearchentities',
            'search': query.query,
            'language': 'en',
            'uselang': 'en',
            'format': 'json',
            'limit': query.limit,
            'origin': '*',
        }
        r = await self.client.get('https://www.wikidata.org/w/api.php', params=params)
        r.raise_for_status()
        out = []
        for x in r.json().get('search', [])[:query.limit]:
            entity_id = x.get('id', '')
            description = x.get('description') or ''
            out.append(self.item(
                title=x.get('label') or entity_id,
                url=f'https://www.wikidata.org/wiki/{entity_id}',
                summary=description,
                query=query.query,
                metadata={
                    'entity_id': entity_id,
                    'match_type': (x.get('match') or {}).get('type'),
                },
                stable_key=entity_id,
            ))
        return out


class OpenAlexAuthorsSource(Source):
    profile = _profile(
        'openalex_authors',
        'people_network',
        'Researcher/author search exposing career identity, institutional affiliation and cross-field connectors.',
        'aggregator',
        'people',
    )

    async def search(self, query, horizon_hours):
        r = await self.client.get(
            'https://api.openalex.org/authors',
            params={'search': query.query, 'per-page': query.limit},
        )
        r.raise_for_status()
        out = []
        for x in r.json().get('results', [])[:query.limit]:
            author_id = x.get('id', '')
            institutions = [
                i.get('display_name', '')
                for i in (x.get('last_known_institutions') or [])
                if i.get('display_name')
            ]
            topics = [
                t.get('display_name', '')
                for t in (x.get('topics') or [])[:5]
                if t.get('display_name')
            ]
            out.append(self.item(
                title=x.get('display_name') or author_id,
                url=author_id or 'https://openalex.org/',
                summary='; '.join(filter(None, [
                    f"Institutions: {', '.join(institutions[:4])}" if institutions else '',
                    f"Topics: {', '.join(topics)}" if topics else '',
                ])),
                query=query.query,
                metadata={
                    'works_count': x.get('works_count'),
                    'cited_by_count': x.get('cited_by_count'),
                    'institutions': ', '.join(institutions[:4]),
                    'orcid': x.get('orcid'),
                },
                stable_key=author_id,
            ))
        return out


class OpenAlexInstitutionsSource(Source):
    profile = _profile(
        'openalex_institutions',
        'institutions',
        'Institution search for universities, research organizations and affiliation structure.',
        'aggregator',
        'institution',
    )

    async def search(self, query, horizon_hours):
        r = await self.client.get(
            'https://api.openalex.org/institutions',
            params={'search': query.query, 'per-page': query.limit},
        )
        r.raise_for_status()
        out = []
        for x in r.json().get('results', [])[:query.limit]:
            institution_id = x.get('id', '')
            geo = x.get('geo') or {}
            out.append(self.item(
                title=x.get('display_name') or institution_id,
                url=x.get('homepage_url') or institution_id or 'https://openalex.org/',
                summary='; '.join(filter(None, [
                    x.get('type') or '',
                    ', '.join(filter(None, [geo.get('city'), geo.get('region'), geo.get('country')])),
                ])),
                query=query.query,
                metadata={
                    'type': x.get('type'),
                    'country_code': x.get('country_code'),
                    'works_count': x.get('works_count'),
                    'cited_by_count': x.get('cited_by_count'),
                },
                stable_key=institution_id,
            ))
        return out


class ProPublicaNonprofitsSource(Source):
    profile = _profile(
        'propublica_nonprofits',
        'nonprofit_foundations',
        'U.S. nonprofit/foundation/association search from ProPublica Nonprofit Explorer and IRS-derived data.',
        'institutional',
        'organization',
    )

    async def search(self, query, horizon_hours):
        r = await self.client.get(
            'https://projects.propublica.org/nonprofits/api/v2/search.json',
            params={'q': query.query},
        )
        r.raise_for_status()
        out = []
        for x in r.json().get('organizations', [])[:query.limit]:
            ein = str(x.get('ein') or '')
            out.append(self.item(
                title=x.get('name') or x.get('sub_name') or ein,
                url=f'https://projects.propublica.org/nonprofits/organizations/{ein}',
                summary=', '.join(filter(None, [x.get('city'), x.get('state'), x.get('ntee_code')])),
                query=query.query,
                metadata={
                    'ein': ein,
                    'city': x.get('city'),
                    'state': x.get('state'),
                    'ntee_code': x.get('ntee_code'),
                    'score': x.get('score'),
                },
                stable_key=ein,
            ))
        return out


class GrantsGovSource(Source):
    profile = _profile(
        'grants_gov',
        'grants_opportunities',
        'U.S. federal grant opportunities, including posted and forecasted opportunities and timing windows.',
        'primary',
        'opportunity',
    )

    async def search(self, query, horizon_hours):
        body = {
            'rows': min(query.limit, 25),
            'keyword': query.query,
            'oppStatuses': 'forecasted|posted',
        }
        r = await self.client.post('https://api.grants.gov/v1/api/search2', json=body)
        r.raise_for_status()
        data = r.json().get('data') or {}
        out = []
        for x in data.get('oppHits', [])[:query.limit]:
            opportunity_id = str(x.get('id') or x.get('number') or '')
            open_date = _us_date(x.get('openDate'))
            out.append(self.item(
                title=x.get('title') or x.get('number') or opportunity_id,
                url=(
                    f'https://www.grants.gov/search-results-detail/{quote(opportunity_id)}'
                    if opportunity_id else 'https://www.grants.gov/search-results'
                ),
                summary='; '.join(filter(None, [
                    x.get('agencyName') or '',
                    f"Status: {x.get('oppStatus')}" if x.get('oppStatus') else '',
                    f"Open: {x.get('openDate')}" if x.get('openDate') else '',
                    f"Close: {x.get('closeDate')}" if x.get('closeDate') else '',
                ])),
                published_at=open_date,
                query=query.query,
                metadata={
                    'opportunity_number': x.get('number'),
                    'agency': x.get('agencyName') or x.get('agencyCode'),
                    'status': x.get('oppStatus'),
                    'open_date': x.get('openDate'),
                    'close_date': x.get('closeDate'),
                    'document_type': x.get('docType'),
                },
                stable_key=opportunity_id,
            ))
        return out


def _us_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%m/%d/%Y').replace(tzinfo=timezone.utc)
    except ValueError:
        return None
