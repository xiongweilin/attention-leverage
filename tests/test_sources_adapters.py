from datetime import datetime, timezone

from app.models import SourceQuery
from app.sources.builtin import (
    ArxivSource, BlueskySource, CisaKevSource, ClinicalTrialsSource, CratesSource,
    CrossrefSource, EuropePMCSource, FederalRegisterSource, GDELTSource, GitHubSource,
    GoogleNewsSource, GreenhouseSource, HackerNewsSource, NasaEonetSource, NpmSource,
    NvdSource, OpenAlexSource, RSSSource, ReliefWebSource, SECSource, StackExchangeSource,
    UsgsSource, WorldBankSource,
)


NOW = datetime.now(timezone.utc)


class Response:
    def __init__(self, payload=None, content=b''):
        self.payload = payload
        self.content = content

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
        return self._next()

    async def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        return self._next()

    def _next(self):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def query(source, text='agent systems', limit=2):
    return SourceQuery(source=source.profile.name, query=text, limit=limit)


def test_news_and_social_adapters_parse_records_and_limits():
    rss = b'<rss><channel><item><title>Agent story</title><link>https://news.test/a</link><description>Summary</description></item></channel></rss>'
    google = GoogleNewsSource(StubClient(Response(content=rss)))
    assert asyncio_run(google.search(query(google), 24))[0].title == 'Agent story'

    gdelt = GDELTSource(StubClient(Response({'articles':[{'title':'Global','url':'https://g.test','seendate':NOW.isoformat(),'domain':'g.test'}]})))
    assert asyncio_run(gdelt.search(query(gdelt), 24))[0].metadata['domain'] == 'g.test'

    hn = HackerNewsSource(StubClient(Response({'hits':[{'title':'HN signal','objectID':'42','created_at':NOW.isoformat(),'points':7}]})))
    hn_item = asyncio_run(hn.search(query(hn), 24))[0]
    assert hn_item.url.endswith('id=42')
    assert hn_item.metadata['points'] == 7

    bluesky = BlueskySource(StubClient(Response({'posts':[{
        'indexedAt':NOW.isoformat(),'uri':'at://did:plc:a/app.bsky.feed.post/p1',
        'author':{'handle':'alice.test'},'record':{'text':'New agent signal'},'likeCount':3,
    }]})))
    sky_item = asyncio_run(bluesky.search(query(bluesky), 24))[0]
    assert sky_item.url == 'https://bsky.app/profile/alice.test/post/p1'
    assert sky_item.metadata['likes'] == 3


def test_package_registry_and_qa_adapters():
    github_client = StubClient(Response({'items':[{'id':1,'full_name':'org/agent','html_url':'https://github.test/r',
                                                   'pushed_at':NOW.isoformat(),'stargazers_count':12}]}))
    github = GitHubSource(github_client, token='secret-not-logged')
    gh_item = asyncio_run(github.search(query(github), 24))[0]
    assert gh_item.title == 'org/agent'
    assert github_client.calls[0][2]['headers']['Authorization'] == 'Bearer secret-not-logged'

    npm = NpmSource(StubClient(Response({'objects':[{'package':{'name':'agent-kit','version':'1.2.0',
        'links':{'npm':'https://npm.test/agent-kit'},'description':'Agent package','date':NOW.isoformat()}}]})))
    assert asyncio_run(npm.search(query(npm), 24))[0].title == 'agent-kit 1.2.0'

    crates = CratesSource(StubClient(Response({'crates':[{'id':'agent-crate','max_version':'2.0',
        'updated_at':NOW.isoformat(),'downloads':10}]})))
    assert asyncio_run(crates.search(query(crates), 24))[0].url.endswith('/agent-crate')

    stack = StackExchangeSource(StubClient(Response({'items':[{'question_id':3,'title':'Agent question',
        'link':'https://stackoverflow.test/q/3','creation_date':int(NOW.timestamp()),'score':2}]})))
    assert asyncio_run(stack.search(query(stack), 24))[0].metadata['score'] == 2


def test_research_adapters_cover_json_and_atom_shapes():
    openalex = OpenAlexSource(StubClient(Response({'results':[{'id':'https://openalex.test/W1','display_name':'Study',
        'publication_date':NOW.date().isoformat(),'primary_location':{'landing_page_url':'https://paper.test'},
        'cited_by_count':9,'open_access':{'is_oa':True}}]})))
    assert asyncio_run(openalex.search(query(openalex), 24))[0].metadata['citations'] == 9

    atom = f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Preprint</title>
        <link href="https://arxiv.test/p/1"/><summary>Abstract</summary>
        <published>{NOW.isoformat()}</published></entry></feed>'''.encode()
    arxiv = ArxivSource(StubClient(Response(content=atom)))
    assert asyncio_run(arxiv.search(query(arxiv), 24))[0].title == 'Preprint'

    crossref = CrossrefSource(StubClient(Response({'message':{'items':[{
        'title':['Published work'],'URL':'https://doi.test/1','DOI':'10.1/x',
        'published-online':{'date-parts':[[2026,9]]},'publisher':'Press',
    }]}})))
    crossref_item = asyncio_run(crossref.search(query(crossref), 24))[0]
    assert crossref_item.published_at.day == 1
    assert crossref_item.metadata['publisher'] == 'Press'

    epmc = EuropePMCSource(StubClient(Response({'resultList':{'result':[{
        'pmid':'123','title':'Medical study','abstractText':'Abstract','firstPublicationDate':NOW.date().isoformat(),
        'citedByCount':4,'journalTitle':'Journal','isOpenAccess':'Y',
    }]}})))
    assert asyncio_run(epmc.search(query(epmc), 24))[0].metadata['citations'] == 4


def test_clinical_trials_regulatory_and_sec_adapters():
    trial = ClinicalTrialsSource(StubClient(Response({'studies':[{'protocolSection':{
        'identificationModule':{'nctId':'NCT1','briefTitle':'Trial'},
        'statusModule':{'overallStatus':'RECRUITING','lastUpdatePostDateStruct':{'date':NOW.date().isoformat()}},
        'descriptionModule':{'briefSummary':'Summary'},'designModule':{'phases':['PHASE2']},
        'conditionsModule':{'conditions':['condition']},'armsInterventionsModule':{'interventions':[{'name':'drug'}]},
    }}]})))
    trial_item = asyncio_run(trial.search(query(trial), 24))[0]
    assert trial_item.metadata['status'] == 'RECRUITING'
    assert trial_item.metadata['interventions'] == 'drug'

    register = FederalRegisterSource(StubClient(Response({'results':[{
        'title':'Proposed rule','html_url':'https://register.test/1','publication_date':NOW.date().isoformat(),
        'document_number':'R-1','agencies':[{'name':'Agency'}],
    }]})))
    assert asyncio_run(register.search(query(register), 24))[0].metadata['agencies'] == 'Agency'

    sec = SECSource(StubClient(
        Response({'1':{'cik_str':123,'ticker':'ACME','title':'Acme Inc'}}),
        Response({'filings':{'recent':{
            'form':['10-K'],'filingDate':[NOW.date().isoformat()],
            'accessionNumber':['0001-26-000001'],'primaryDocument':['report.htm'],
            'primaryDocDescription':['Annual report'],
        }}}),
    ), user_agent='test contact test@example.test')
    sec_item = asyncio_run(sec.search(query(sec, 'ACME'), 48))[0]
    assert sec_item.title.startswith('ACME 10-K')
    assert sec_item.url.endswith('/000126000001/report.htm')
    assert sec_item.metadata['accession'] == '0001-26-000001'


def test_macro_humanitarian_and_security_adapters():
    worldbank = WorldBankSource(StubClient(Response([{},[{'value':1,'date':'2025','country':{'value':'World'}}]])))
    assert asyncio_run(worldbank.search(query(worldbank, 'gdp'), 24))[0].metadata['indicator'] == 'NY.GDP.MKTP.CD'

    reliefweb = ReliefWebSource(StubClient(Response({'data':[{'id':1,'fields':{
        'title':'Relief report','url':'https://relief.test/1','body-html':'<p>Report</p>',
        'source':[{'name':'UN'}],'country':[{'name':'Country'}],'date':{'created':NOW.isoformat()},
    }}]})), appname='test-app')
    report = asyncio_run(reliefweb.search(query(reliefweb), 24))[0]
    assert report.summary == 'Report'
    assert report.metadata['sources'] == 'UN'

    kev = CisaKevSource(StubClient(Response({'vulnerabilities':[{
        'cveID':'CVE-1','vendorProject':'Vendor','product':'Agent','vulnerabilityName':'Agent issue',
        'shortDescription':'Agent exploit','dateAdded':NOW.date().isoformat(),'dueDate':'2026-10-01',
    }]})))
    assert asyncio_run(kev.search(query(kev), 24))[0].metadata['vendor'] == 'Vendor'

    nvd_client = StubClient(Response({'vulnerabilities':[{'cve':{
        'id':'CVE-2','published':NOW.isoformat(),'descriptions':[{'lang':'en','value':'Issue'}],
        'metrics':{'cvssMetricV31':[{'cvssData':{'baseScore':8.1}}]},'vulnStatus':'Analyzed',
    }}]}))
    nvd = NvdSource(nvd_client, api_key='nvd-test')
    nvd_item = asyncio_run(nvd.search(query(nvd), 24))[0]
    assert nvd_item.metadata['cvss'] == 8.1
    assert nvd_client.calls[0][2]['headers']['apiKey'] == 'nvd-test'


def test_hazard_greenhouse_and_rss_adapters():
    usgs = UsgsSource(StubClient(Response({'features':[{'id':'event-1','properties':{
        'title':'M4 event','url':'https://usgs.test/1','mag':4.8,'place':'Test place',
        'time':int(NOW.timestamp()*1000),'alert':'green','tsunami':0,
    }}]})))
    assert asyncio_run(usgs.search(query(usgs), 24))[0].metadata['magnitude'] == 4.8

    eonet = NasaEonetSource(StubClient(Response({'events':[{'id':'E1','title':'Fire','geometry':[{'date':NOW.isoformat()}],
        'categories':[{'title':'Wildfires'}],'sources':[{'url':'https://nasa.test/E1'}]}]})))
    assert asyncio_run(eonet.search(query(eonet), 24))[0].metadata['categories'] == 'Wildfires'

    greenhouse = GreenhouseSource(StubClient(Response({'jobs':[{
        'id':7,'title':'AI Engineer','absolute_url':'https://jobs.test/7','updated_at':NOW.isoformat(),
        'content':'<p>Build agent systems</p>','location':{'name':'Remote'},
    }]})), boards=[{'token':'acme','name':'Acme'}])
    job = asyncio_run(greenhouse.search(query(greenhouse, 'agent'), 24))[0]
    assert job.title == 'AI Engineer — Acme'
    assert job.metadata['location'] == 'Remote'

    feed = b'<rss><channel><item><title>Agent release</title><link>https://feed.test/1</link><description>Agent update</description></item></channel></rss>'
    rss = RSSSource(StubClient(RuntimeError('feed unavailable'), Response(content=feed)), feeds=[
        {'url':'https://broken.test/feed','name':'broken'},
        {'url':'https://feed.test/rss','name':'official','authority':'primary'},
    ])
    feed_items = asyncio_run(rss.search(query(rss, 'agent'), 24))
    assert len(feed_items) == 1
    assert feed_items[0].authority == 'primary'


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
