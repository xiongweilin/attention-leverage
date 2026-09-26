from app.models import Candidate, QueryPlan, SourceProfile
from app.screening import SemanticScreener


class NoLLM:
    available=False


async def test_fallback_screening_sorted():
    profiles={'x':SourceProfile(name='x',category='test',description='x')}
    s=SemanticScreener(NoLLM(),profiles)
    high=Candidate(id='b',source='x',title='b',url='https://b',heuristic_score=.8)
    low=Candidate(id='a',source='x',title='a',url='https://a',heuristic_score=.2)
    digest,ranked,used=await s.screen(QueryPlan(goal='x'),[low,high])
    assert not used
    assert ranked[0].id=='b'
    assert ranked[0].disposition=='attention'
    assert digest.headline
