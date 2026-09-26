from datetime import datetime, timezone

from app.models import SourceQuery
from app.sources.environment import (
    GrantsGovSource, OpenAlexAuthorsSource, OpenAlexInstitutionsSource,
    ProPublicaNonprofitsSource, WikidataSource,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class StubClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        return self.responses.pop(0)


def q(source, text='network entry', limit=5):
    return SourceQuery(source=source.profile.name, query=text, mode='environment', limit=limit)


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_wikidata_openalex_people_and_institutions():
    wikidata = WikidataSource(StubClient(Response({'search':[{
        'id':'Q1','label':'Example Association','description':'professional association',
        'match':{'type':'label'},
    }]})))
    entity = run(wikidata.search(q(wikidata), 24))[0]
    assert entity.metadata['entity_id'] == 'Q1'
    assert entity.source_category == 'knowledge_graph'

    authors = OpenAlexAuthorsSource(StubClient(Response({'results':[{
        'id':'https://openalex.org/A1','display_name':'Alice Example','works_count':10,'cited_by_count':20,
        'last_known_institutions':[{'display_name':'Example University'}],
        'topics':[{'display_name':'AI'}],
    }]})))
    author = run(authors.search(q(authors), 24))[0]
    assert 'Example University' in author.summary
    assert author.metadata['works_count'] == 10

    institutions = OpenAlexInstitutionsSource(StubClient(Response({'results':[{
        'id':'https://openalex.org/I1','display_name':'Example Institute','homepage_url':'https://example.edu',
        'type':'education','country_code':'US','works_count':100,'cited_by_count':200,
        'geo':{'city':'Boston','region':'Massachusetts','country':'United States'},
    }]})))
    institution = run(institutions.search(q(institutions), 24))[0]
    assert institution.url == 'https://example.edu'
    assert institution.metadata['country_code'] == 'US'


def test_nonprofit_and_grant_opportunity_sources():
    nonprofits = ProPublicaNonprofitsSource(StubClient(Response({'organizations':[{
        'ein':123456789,'name':'Example Foundation','city':'New York','state':'NY',
        'ntee_code':'T20','score':10.5,
    }]})))
    org = run(nonprofits.search(q(nonprofits, 'foundation'), 24))[0]
    assert org.title == 'Example Foundation'
    assert org.metadata['ein'] == '123456789'
    assert org.authority == 'institutional'

    grants = GrantsGovSource(StubClient(Response({'data':{'oppHits':[{
        'id':'321','number':'ABC-1','title':'Public Fellowship','agencyName':'Agency',
        'openDate':'09/01/2026','closeDate':'12/01/2026','oppStatus':'posted','docType':'synopsis',
    }]}})))
    opportunity = run(grants.search(q(grants, 'fellowship'), 24))[0]
    assert opportunity.title == 'Public Fellowship'
    assert opportunity.metadata['status'] == 'posted'
    assert opportunity.published_at == datetime(2026,9,1,tzinfo=timezone.utc)
    assert grants.client.calls[0][0] == 'POST'
    assert grants.client.calls[0][2]['json']['oppStatuses'] == 'forecasted|posted'
