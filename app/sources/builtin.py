from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from .base import Source
from .utils import parse_datetime, strip_html, xml_feed_entries
from ..models import RawItem, SourceProfile, SourceQuery


def profile(name, category, description, authority='unknown', queryable=True, signal_kind='content', cost='low'):
    return SourceProfile(name=name, category=category, description=description, authority=authority,
                         queryable=queryable, signal_kind=signal_kind, cost=cost)


class GoogleNewsSource(Source):
    profile = profile('google_news','news','Broad current-news aggregation across publishers.','aggregator',True,'news')
    async def search(self, query, horizon_hours):
        url = f"https://news.google.com/rss/search?q={quote_plus(query.query)}&hl=en-US&gl=US&ceid=US:en"
        r = await self.client.get(url); r.raise_for_status()
        return [self.item(title=e['title'], url=e['link'], summary=strip_html(e['summary']),
                          published_at=parse_datetime(e['published']), query=query.query)
                for e in xml_feed_entries(r.content, url)[:query.limit] if e.get('link')]


class GDELTSource(Source):
    profile = profile('gdelt','global_news','Global multilingual news/event index useful for geographic and cross-outlet coverage.','aggregator',True,'event/news')
    async def search(self, query, horizon_hours):
        params={'query':query.query,'mode':'ArtList','maxrecords':query.limit,'format':'json','sort':'HybridRel','timespan':f'{max(1,int(horizon_hours))}h'}
        r=await self.client.get('https://api.gdeltproject.org/api/v2/doc/doc',params=params); r.raise_for_status()
        out=[]
        for a in r.json().get('articles',[])[:query.limit]:
            out.append(self.item(title=a.get('title',''),url=a.get('url',''),summary=a.get('seendate',''),published_at=parse_datetime(a.get('seendate')),
                query=query.query,metadata={'domain':a.get('domain'),'language':a.get('language'),'country':a.get('sourcecountry')}))
        return out


class HackerNewsSource(Source):
    profile = profile('hackernews','community_tech','Technology/startup practitioner discussion and weak signals.','community',True,'discussion')
    async def search(self, query, horizon_hours):
        cutoff=int((datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).timestamp())
        r=await self.client.get('https://hn.algolia.com/api/v1/search_by_date',params={'query':query.query,'tags':'story','hitsPerPage':query.limit,'numericFilters':f'created_at_i>{cutoff}'})
        r.raise_for_status(); out=[]
        for h in r.json().get('hits',[])[:query.limit]:
            url=h.get('url') or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            out.append(self.item(title=h.get('title') or '',url=url,summary=strip_html(h.get('story_text') or ''),published_at=parse_datetime(h.get('created_at')),
                query=query.query,metadata={'points':h.get('points'),'comments':h.get('num_comments'),'author':h.get('author')}))
        return out


class BlueskySource(Source):
    profile = profile('bluesky','social','Public Bluesky post search for fast-moving social weak signals.','community',True,'social')
    async def search(self, query, horizon_hours):
        r=await self.client.get('https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts',params={'q':query.query,'limit':query.limit,'sort':'latest'}); r.raise_for_status()
        out=[]; cutoff=datetime.now(timezone.utc)-timedelta(hours=horizon_hours*1.5)
        for p in r.json().get('posts',[]):
            when=parse_datetime(p.get('indexedAt') or (p.get('record') or {}).get('createdAt'))
            if when and when<cutoff: continue
            author=p.get('author') or {}; handle=author.get('handle',''); uri=p.get('uri',''); rkey=uri.rsplit('/',1)[-1] if uri else ''
            url=f'https://bsky.app/profile/{handle}/post/{rkey}' if handle and rkey else 'https://bsky.app/'
            text=(p.get('record') or {}).get('text','')
            out.append(self.item(title=(text[:160] or f'Post by {handle}'),url=url,summary=text,published_at=when,query=query.query,
                metadata={'author':author.get('displayName') or handle,'likes':p.get('likeCount'),'reposts':p.get('repostCount'),'replies':p.get('replyCount')},stable_key=uri))
        return out[:query.limit]


class GitHubSource(Source):
    profile = profile('github','open_source','Repository search for new tools, implementations and ecosystem movement.','primary',True,'software')
    def __init__(self,client,token=''):
        super().__init__(client); self.token=token
    async def search(self, query, horizon_hours):
        since=(datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).date().isoformat(); q=f'{query.query} pushed:>={since}'
        headers={'Accept':'application/vnd.github+json'}
        if self.token: headers['Authorization']=f'Bearer {self.token}'
        r=await self.client.get('https://api.github.com/search/repositories',params={'q':q,'sort':'updated','order':'desc','per_page':query.limit},headers=headers); r.raise_for_status()
        return [self.item(title=x.get('full_name',''),url=x.get('html_url',''),summary=x.get('description') or '',published_at=parse_datetime(x.get('pushed_at') or x.get('updated_at')),
            query=query.query,metadata={'stars':x.get('stargazers_count'),'forks':x.get('forks_count'),'language':x.get('language')},stable_key=str(x.get('id'))) for x in r.json().get('items',[])[:query.limit]]


class NpmSource(Source):
    profile = profile('npm','package_registry','npm registry search for JavaScript/TypeScript package changes and alternatives.','primary',True,'package')
    async def search(self, query, horizon_hours):
        r=await self.client.get('https://registry.npmjs.org/-/v1/search',params={'text':query.query,'size':query.limit}); r.raise_for_status(); out=[]
        for x in r.json().get('objects',[])[:query.limit]:
            p=x.get('package') or {}; name=p.get('name','')
            out.append(self.item(title=f"{name} {p.get('version','')}",url=(p.get('links') or {}).get('npm') or f'https://www.npmjs.com/package/{name}',summary=p.get('description') or '',
                published_at=parse_datetime(p.get('date') or p.get('time')),query=query.query,metadata={'score':x.get('score',{}).get('final'),'publisher':(p.get('publisher') or {}).get('username')},stable_key=name))
        return out


class CratesSource(Source):
    profile = profile('crates','package_registry','crates.io search for Rust packages and ecosystem changes.','primary',True,'package')
    async def search(self, query, horizon_hours):
        r=await self.client.get('https://crates.io/api/v1/crates',params={'q':query.query,'per_page':query.limit,'sort':'recent-downloads'}); r.raise_for_status(); out=[]
        for c in r.json().get('crates',[])[:query.limit]:
            name=c.get('id') or c.get('name','')
            out.append(self.item(title=f"{name} {c.get('max_version','')}",url=f'https://crates.io/crates/{name}',summary=c.get('description') or '',published_at=parse_datetime(c.get('updated_at')),
                query=query.query,metadata={'downloads':c.get('downloads'),'recent_downloads':c.get('recent_downloads'),'repository':c.get('repository')},stable_key=name))
        return out


class StackExchangeSource(Source):
    profile = profile('stackexchange','community_qa','Stack Overflow questions expose implementation pain, adoption and failure modes.','community',True,'questions')
    async def search(self, query, horizon_hours):
        cutoff=int((datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).timestamp())
        params={'site':'stackoverflow','q':query.query,'sort':'creation','order':'desc','pagesize':query.limit,'fromdate':cutoff}
        r=await self.client.get('https://api.stackexchange.com/2.3/search/advanced',params=params); r.raise_for_status()
        return [self.item(title=strip_html(x.get('title','')),url=x.get('link',''),published_at=parse_datetime(x.get('creation_date')),query=query.query,
            metadata={'score':x.get('score'),'answers':x.get('answer_count'),'is_answered':x.get('is_answered')},stable_key=str(x.get('question_id'))) for x in r.json().get('items',[])[:query.limit]]


class OpenAlexSource(Source):
    profile = profile('openalex','research','Broad scholarly-work index across disciplines.','aggregator',True,'research')
    async def search(self, query, horizon_hours):
        since=(datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).date().isoformat()
        r=await self.client.get('https://api.openalex.org/works',params={'search':query.query,'per-page':query.limit,'filter':f'from_publication_date:{since}'}); r.raise_for_status(); out=[]
        for w in r.json().get('results',[])[:query.limit]:
            loc=w.get('primary_location') or {}; out.append(self.item(title=w.get('display_name',''),url=loc.get('landing_page_url') or w.get('doi') or w.get('id',''),published_at=parse_datetime(w.get('publication_date')),query=query.query,
                metadata={'citations':w.get('cited_by_count'),'type':w.get('type'),'open_access':(w.get('open_access') or {}).get('is_oa')},stable_key=w.get('id','')))
        return out


class ArxivSource(Source):
    profile = profile('arxiv','research_preprint','Recent scientific/technical preprints directly from arXiv.','primary',True,'preprint')
    async def search(self, query, horizon_hours):
        params={'search_query':f'all:"{query.query}"','start':0,'max_results':query.limit,'sortBy':'submittedDate','sortOrder':'descending'}
        r=await self.client.get('https://export.arxiv.org/api/query',params=params); r.raise_for_status(); cutoff=datetime.now(timezone.utc)-timedelta(hours=horizon_hours*2); out=[]
        for e in xml_feed_entries(r.content,'https://arxiv.org'):
            when=parse_datetime(e.get('published')); 
            if when and when<cutoff: continue
            out.append(self.item(title=e.get('title',''),url=e.get('link',''),summary=strip_html(e.get('summary','')),published_at=when,query=query.query))
        return out[:query.limit]


class CrossrefSource(Source):
    profile = profile('crossref','research_published','DOI metadata for newly published scholarly work.','institutional',True,'publication')
    async def search(self, query, horizon_hours):
        since=(datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).date().isoformat()
        r=await self.client.get('https://api.crossref.org/works',params={'query.bibliographic':query.query,'rows':query.limit,'filter':f'from-pub-date:{since}','sort':'published','order':'desc'}); r.raise_for_status(); out=[]
        for w in r.json().get('message',{}).get('items',[])[:query.limit]:
            title=(w.get('title') or [''])[0]; when=_crossref_date(w)
            out.append(self.item(title=title,url=w.get('URL',''),summary=strip_html(w.get('abstract') or ''),published_at=when,query=query.query,
                metadata={'publisher':w.get('publisher'),'type':w.get('type'),'citations':w.get('is-referenced-by-count')},stable_key=w.get('DOI','')))
        return out


def _crossref_date(w):
    for key in ('published-online','published-print','published','created'):
        obj=w.get(key) or {}; parts=(obj.get('date-parts') or [[]])[0]
        if parts:
            vals=(parts+[1,1])[:3]
            try: return datetime(vals[0],vals[1],vals[2],tzinfo=timezone.utc)
            except Exception: pass
        if obj.get('date-time'): return parse_datetime(obj['date-time'])
    return None


class EuropePMCSource(Source):
    profile = profile('europepmc','biomed_research','Biomedical literature/preprint search with citation and abstract metadata.','institutional',True,'biomedical_research')
    async def search(self, query, horizon_hours):
        r=await self.client.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',params={'query':f'{query.query} sort_date:y','format':'json','pageSize':query.limit,'resultType':'core'}); r.raise_for_status(); out=[]
        for x in r.json().get('resultList',{}).get('result',[])[:query.limit]:
            ident=x.get('pmcid') or x.get('pmid') or x.get('doi') or x.get('id',''); url=f'https://europepmc.org/article/{x.get("source","MED")}/{x.get("id",ident)}'
            out.append(self.item(title=x.get('title',''),url=url,summary=x.get('abstractText') or '',published_at=parse_datetime(x.get('firstPublicationDate') or x.get('electronicPublicationDate')),
                query=query.query,metadata={'citations':x.get('citedByCount'),'journal':x.get('journalTitle'),'is_open_access':x.get('isOpenAccess')},stable_key=str(ident)))
        return out


class ClinicalTrialsSource(Source):
    profile = profile('clinicaltrials','clinical_trials','ClinicalTrials.gov study registry for trial status and intervention signals.','primary',True,'clinical_trial')
    async def search(self, query, horizon_hours):
        fields='NCTId,BriefTitle,OverallStatus,LastUpdatePostDate,Conditions,Interventions,Phases,BriefSummary'
        params={'format':'json','pageSize':query.limit,'query.term':query.query,'fields':fields,'sort':'LastUpdatePostDate:desc'}
        r=await self.client.get('https://clinicaltrials.gov/api/v2/studies',params=params); r.raise_for_status(); out=[]
        for s in r.json().get('studies',[])[:query.limit]:
            p=s.get('protocolSection') or {}; ident=p.get('identificationModule') or {}; status=p.get('statusModule') or {}; desc=p.get('descriptionModule') or {}; design=p.get('designModule') or {}; cond=p.get('conditionsModule') or {}; arms=p.get('armsInterventionsModule') or {}
            nct=ident.get('nctId',''); interventions=[i.get('name','') for i in arms.get('interventions',[])[:5]]
            out.append(self.item(title=ident.get('briefTitle',''),url=f'https://clinicaltrials.gov/study/{nct}',summary=desc.get('briefSummary') or '',published_at=parse_datetime(status.get('lastUpdatePostDateStruct',{}).get('date')),
                query=query.query,metadata={'status':status.get('overallStatus'),'phases':','.join(design.get('phases',[]) or []),'conditions':', '.join(cond.get('conditions',[])[:5]),'interventions':', '.join(interventions)},stable_key=nct))
        return out


class FederalRegisterSource(Source):
    profile = profile('federal_register','regulation','U.S. Federal Register proposed rules, final rules, notices and presidential documents.','primary',True,'regulatory')
    async def search(self, query, horizon_hours):
        params={'conditions[term]':query.query,'per_page':query.limit,'order':'newest'}
        r=await self.client.get('https://www.federalregister.gov/api/v1/documents.json',params=params); r.raise_for_status(); out=[]
        for x in r.json().get('results',[])[:query.limit]:
            out.append(self.item(title=x.get('title',''),url=x.get('html_url') or x.get('pdf_url') or '',summary=x.get('abstract') or '',published_at=parse_datetime(x.get('publication_date')),
                query=query.query,metadata={'type':x.get('type'),'document_number':x.get('document_number'),'agencies':', '.join(a.get('name','') for a in (x.get('agencies') or [])[:5])},stable_key=x.get('document_number','')))
        return out


class SECSource(Source):
    profile = profile('sec','company_disclosure','SEC EDGAR recent company filings; requires a descriptive SEC_USER_AGENT.','primary',True,'filing')
    def __init__(self,client,user_agent): super().__init__(client); self.user_agent=user_agent
    async def search(self, query, horizon_hours):
        headers={'User-Agent':self.user_agent,'Accept-Encoding':'gzip, deflate'}
        tick=await self.client.get('https://www.sec.gov/files/company_tickers.json',headers=headers); tick.raise_for_status(); terms=query.query.lower().split(); matches=[]
        matches = _matching_companies(tick.json().values(), terms)
        out=[]; cutoff=datetime.now(timezone.utc)-timedelta(hours=horizon_hours*2)
        for company in matches:
            cik=str(company.get('cik_str','')).zfill(10); r=await self.client.get(f'https://data.sec.gov/submissions/CIK{cik}.json',headers=headers); r.raise_for_status(); recent=(r.json().get('filings') or {}).get('recent') or {}
            out.extend(_recent_sec_filings(self, company, recent, query, cutoff))
            if len(out) >= query.limit:
                return out[:query.limit]
        return out[:query.limit]


def _matching_companies(companies, terms: list[str], limit: int = 3) -> list[dict]:
    matches = []
    for company in companies:
        searchable = f"{company.get('ticker', '')} {company.get('title', '')}".lower()
        if any(term in searchable for term in terms if len(term) >= 2):
            matches.append(company)
            if len(matches) >= limit:
                break
    return matches


def _recent_sec_filings(source, company: dict, recent: dict, query, cutoff: datetime) -> list[RawItem]:
    forms = recent.get('form', [])[:80]
    dates = recent.get('filingDate') or [''] * len(forms)
    accessions = recent.get('accessionNumber') or [''] * len(forms)
    documents = recent.get('primaryDocument') or [''] * len(forms)
    descriptions = recent.get('primaryDocDescription') or [''] * len(forms)
    cik = str(int(str(company.get('cik_str', '0')).zfill(10)))
    out = []
    for index, form in enumerate(forms):
        filing = _sec_filing_item(source, company, form, dates[index], accessions[index], documents[index],
                                  descriptions[index], cik, query, cutoff)
        if filing is not None:
            out.append(filing)
    return out


def _sec_filing_item(source, company, form, filing_date, accession, document, description, cik, query, cutoff):
    published = parse_datetime(filing_date)
    if published and published < cutoff:
        return None
    accession_number = accession.replace('-', '')
    url = (f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number}/{document}'
           if accession and document else f'https://www.sec.gov/edgar/browse/?CIK={cik}')
    return source.item(
        title=f"{company.get('ticker')} {form} — {company.get('title')}", url=url,
        summary=description or '', published_at=published, query=query.query,
        metadata={'form':form,'ticker':company.get('ticker'),'company':company.get('title'),'accession':accession},
        stable_key=accession,
    )


class WorldBankSource(Source):
    profile = profile('worldbank','macro_data','World Bank indicators for broad macro/development data signals.','institutional',True,'macro_data')
    INDICATORS={
        'gdp':('NY.GDP.MKTP.CD','GDP (current US$)'), 'growth':('NY.GDP.MKTP.KD.ZG','GDP growth'),
        'inflation':('FP.CPI.TOTL.ZG','Inflation, consumer prices'), 'unemployment':('SL.UEM.TOTL.ZS','Unemployment'),
        'population':('SP.POP.TOTL','Population'), 'poverty':('SI.POV.DDAY','Poverty headcount'),
        'internet':('IT.NET.USER.ZS','Individuals using the Internet'), 'co2':('EN.ATM.CO2E.PC','CO2 emissions per capita'),
        'life expectancy':('SP.DYN.LE00.IN','Life expectancy'), 'trade':('NE.TRD.GNFS.ZS','Trade (% of GDP)'),
        'fdi':('BX.KLT.DINV.WD.GD.ZS','FDI net inflows (% GDP)'), 'debt':('GC.DOD.TOTL.GD.ZS','Central government debt'),
    }
    async def search(self, query, horizon_hours):
        q=query.query.lower(); choices=[v for k,v in self.INDICATORS.items() if k in q]
        if not choices: choices=[self.INDICATORS['gdp'],self.INDICATORS['inflation'],self.INDICATORS['unemployment']]
        out=[]
        for code,label in choices[:3]:
            r=await self.client.get(f'https://api.worldbank.org/v2/country/WLD/indicator/{code}',params={'format':'json','mrnev':1,'per_page':5}); r.raise_for_status(); data=r.json()
            rows=data[1] if isinstance(data,list) and len(data)>1 and data[1] else []
            for x in rows[:1]:
                out.append(self.item(title=f"{label}: {x.get('value')} ({x.get('date')})",url=f'https://data.worldbank.org/indicator/{code}',summary=f"World aggregate. Indicator {code}.",query=query.query,
                    metadata={'indicator':code,'value':x.get('value'),'period':x.get('date'),'country':(x.get('country') or {}).get('value')},stable_key=f'{code}:{x.get("date")}:{x.get("value")}'))
        return out[:query.limit]


class ReliefWebSource(Source):
    profile = profile('reliefweb','humanitarian','UN OCHA ReliefWeb reports for humanitarian crises and disaster response.','institutional',True,'humanitarian')
    def __init__(self,client,appname): super().__init__(client); self.appname=appname
    async def search(self, query, horizon_hours):
        body={'query':{'value':query.query},'limit':query.limit,'preset':'latest','fields':{'include':['title','url','date.created','source.name','country.name','body-html']}}
        r=await self.client.post('https://api.reliefweb.int/v2/reports',params={'appname':self.appname},json=body); r.raise_for_status(); out=[]
        for x in r.json().get('data',[])[:query.limit]:
            f=x.get('fields') or {}; sources=f.get('source') or []; countries=f.get('country') or []
            out.append(self.item(title=f.get('title',''),url=f.get('url') or '',summary=strip_html(f.get('body-html') or '')[:2000],published_at=parse_datetime((f.get('date') or {}).get('created')),
                query=query.query,metadata={'sources':', '.join(s.get('name','') for s in sources[:4]),'countries':', '.join(c.get('name','') for c in countries[:4])},stable_key=str(x.get('id'))))
        return out


class CisaKevSource(Source):
    profile = profile('cisa_kev','cybersecurity','CISA authoritative catalog of vulnerabilities known to be exploited in the wild.','primary',False,'security_alert')
    async def search(self, query, horizon_hours):
        r=await self.client.get('https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json'); r.raise_for_status(); q=query.query.lower(); terms=[t for t in q.split() if len(t)>2]; cutoff=datetime.now(timezone.utc)-timedelta(hours=horizon_hours*3); out=[]
        for x in reversed(r.json().get('vulnerabilities',[])):
            hay=f"{x.get('vendorProject','')} {x.get('product','')} {x.get('vulnerabilityName','')} {x.get('shortDescription','')}".lower(); when=parse_datetime(x.get('dateAdded'))
            if terms and not any(t in hay for t in terms): continue
            if when and when<cutoff and terms: continue
            cve=x.get('cveID',''); out.append(self.item(title=f"{cve} — {x.get('vulnerabilityName','')}",url=f'https://www.cisa.gov/known-exploited-vulnerabilities-catalog?search_api_fulltext={cve}',summary=x.get('shortDescription') or '',published_at=when,query=query.query,
                metadata={'vendor':x.get('vendorProject'),'product':x.get('product'),'due_date':x.get('dueDate'),'ransomware':x.get('knownRansomwareCampaignUse')},stable_key=cve))
            if len(out)>=query.limit: break
        return out


class NvdSource(Source):
    profile = profile('nvd','cybersecurity','NIST NVD CVE search for newly published/updated vulnerabilities.','institutional',True,'vulnerability')
    def __init__(self,client,api_key=''): super().__init__(client); self.api_key=api_key
    async def search(self, query, horizon_hours):
        start=datetime.now(timezone.utc)-timedelta(hours=min(horizon_hours*2,24*120)); end=datetime.now(timezone.utc)
        params={'keywordSearch':query.query,'resultsPerPage':query.limit,'pubStartDate':start.isoformat(timespec='milliseconds').replace('+00:00','Z'),'pubEndDate':end.isoformat(timespec='milliseconds').replace('+00:00','Z')}
        headers={'apiKey':self.api_key} if self.api_key else {}
        r=await self.client.get('https://services.nvd.nist.gov/rest/json/cves/2.0',params=params,headers=headers); r.raise_for_status(); out=[]
        for row in r.json().get('vulnerabilities',[])[:query.limit]:
            c=row.get('cve') or {}; cve=c.get('id',''); desc=next((d.get('value','') for d in c.get('descriptions',[]) if d.get('lang')=='en'),'')
            metrics=c.get('metrics') or {}; score=None
            for k in ('cvssMetricV40','cvssMetricV31','cvssMetricV30','cvssMetricV2'):
                if metrics.get(k): score=((metrics[k][0].get('cvssData') or {}).get('baseScore')); break
            out.append(self.item(title=f'{cve} — {desc[:140]}',url=f'https://nvd.nist.gov/vuln/detail/{cve}',summary=desc,published_at=parse_datetime(c.get('published')),
                query=query.query,metadata={'cvss':score,'status':c.get('vulnStatus')},stable_key=cve))
        return out


class UsgsSource(Source):
    profile = profile('usgs','natural_hazards','USGS earthquake event feed for significant seismic events.','primary',False,'hazard')
    async def search(self, query, horizon_hours):
        start=(datetime.now(timezone.utc)-timedelta(hours=horizon_hours)).isoformat(); params={'format':'geojson','starttime':start,'orderby':'time','limit':query.limit,'minmagnitude':4.5}
        r=await self.client.get('https://earthquake.usgs.gov/fdsnws/event/1/query',params=params); r.raise_for_status(); out=[]
        for f in r.json().get('features',[])[:query.limit]:
            p=f.get('properties') or {}; out.append(self.item(title=p.get('title',''),url=p.get('url',''),summary=f"Magnitude {p.get('mag')} at {p.get('place','')}",published_at=parse_datetime((p.get('time') or 0)/1000),query=query.query,
                metadata={'magnitude':p.get('mag'),'place':p.get('place'),'alert':p.get('alert'),'tsunami':p.get('tsunami')},stable_key=f.get('id','')))
        return out


class NasaEonetSource(Source):
    profile = profile('nasa_eonet','natural_hazards','NASA EONET open natural-event tracker for fires, storms, volcanoes and other hazards.','primary',False,'hazard')
    async def search(self, query, horizon_hours):
        days=max(1,min(365,math.ceil(horizon_hours/24))); r=await self.client.get('https://eonet.gsfc.nasa.gov/api/v3/events',params={'status':'open','days':days,'limit':query.limit}); r.raise_for_status(); out=[]
        for e in r.json().get('events',[])[:query.limit]:
            geometry=e.get('geometry') or []; when=parse_datetime(geometry[-1].get('date')) if geometry else None; cats=e.get('categories') or []
            link=(e.get('sources') or [{}])[0].get('url') or e.get('link') or 'https://eonet.gsfc.nasa.gov/'
            out.append(self.item(title=e.get('title',''),url=link,summary=e.get('description') or '',published_at=when,query=query.query,
                metadata={'categories':', '.join(c.get('title','') for c in cats),'closed':e.get('closed')},stable_key=e.get('id','')))
        return out


class GreenhouseSource(Source):
    profile = profile('greenhouse','jobs','Configured Greenhouse public job boards for target-company hiring signals.','primary',False,'jobs')
    def __init__(self,client,boards): super().__init__(client); self.boards=boards
    async def search(self, query, horizon_hours):
        terms=[t.lower() for t in query.query.split() if len(t)>2]
        semaphore=asyncio.Semaphore(6)

        async def read_board(board):
            async with semaphore:
                return await _read_greenhouse_board(self, board, terms, query)

        batches=await asyncio.gather(*(read_board(board) for board in self.boards))
        out=[item for batch in batches for item in batch]
        out.sort(key=lambda x:x.published_at or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
        return out[:query.limit]


def _greenhouse_board(board) -> tuple[str, str]:
    if isinstance(board, dict):
        token = board.get('token', '')
        return token, board.get('name', token)
    token = str(board)
    return token, token


def _greenhouse_matches(job: dict, terms: list[str]) -> bool:
    location = (job.get('location') or {}).get('name', '')
    searchable = f"{job.get('title', '')} {strip_html(job.get('content') or '')} {location}".lower()
    return not terms or any(term in searchable for term in terms)


async def _read_greenhouse_board(source, board, terms: list[str], query) -> list[RawItem]:
    token, label = _greenhouse_board(board)
    if not token:
        return []
    try:
        response = await source.client.get(
            f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs',
            params={'content':'true'},
        )
        response.raise_for_status()
    except Exception:
        return []
    return [
        _greenhouse_item(source, job, token, label, query)
        for job in response.json().get('jobs', [])
        if _greenhouse_matches(job, terms)
    ]


def _greenhouse_item(source, job: dict, token: str, label: str, query) -> RawItem:
    location = (job.get('location') or {}).get('name')
    content = strip_html(job.get('content') or '')
    return source.item(
        title=f"{job.get('title', '')} — {label}", url=job.get('absolute_url', ''),
        summary=content[:1800], published_at=parse_datetime(job.get('updated_at')), query=query.query,
        metadata={'company':label,'location':location}, stable_key=f'{token}:{job.get("id")}',
    )


class RSSSource(Source):
    profile = profile('rss','trusted_feeds','Configured RSS/Atom feeds for official, niche and long-tail sources.','unknown',False,'feed')
    def __init__(self,client,feeds): super().__init__(client); self.feeds=feeds
    async def search(self, query, horizon_hours):
        terms=[t.lower() for t in query.query.split() if len(t)>2]
        semaphore=asyncio.Semaphore(8)

        async def read_feed(feed):
            url, label, authority = _rss_feed_details(feed)
            async with semaphore:
                return await _read_rss_feed(self, url, label, authority, terms, query)

        batches=await asyncio.gather(*(read_feed(feed) for feed in self.feeds))
        out=[item for batch in batches for item in batch]
        out.sort(key=lambda x:x.published_at or datetime.min.replace(tzinfo=timezone.utc),reverse=True)
        return out[:query.limit]


def _rss_feed_details(feed) -> tuple[str, str, str | None]:
    if isinstance(feed, dict):
        url = feed.get('url', '')
        return url, feed.get('name', url), feed.get('authority')
    url = str(feed)
    return url, url, None


def _rss_entry_matches(entry: dict, terms: list[str]) -> bool:
    searchable = f"{entry.get('title', '')} {strip_html(entry.get('summary', ''))}".lower()
    return not terms or any(term in searchable for term in terms)


async def _read_rss_feed(source, url: str, label: str, authority: str | None, terms: list[str], query):
    try:
        response = await source.client.get(url)
        response.raise_for_status()
    except Exception:
        return []
    items = []
    for entry in xml_feed_entries(response.content, url)[:40]:
        if not _rss_entry_matches(entry, terms):
            continue
        item = source.item(
            title=entry.get('title', ''), url=entry.get('link', ''),
            summary=strip_html(entry.get('summary', '')),
            published_at=parse_datetime(entry.get('published')), query=query.query,
            metadata={'feed':label},
        )
        if authority in ('primary','institutional','community','aggregator','unknown'):
            item.authority = authority
        items.append(item)
    return items
