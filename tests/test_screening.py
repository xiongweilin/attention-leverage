import json

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


async def test_model_screening_merges_known_items_and_falls_back_for_missing_ones():
    class ModelLLM:
        available=True

        async def json(self, system, user):
            assert 'Goal: decide' in system
            payload = json.loads(user)
            assert payload[0]['source_description'] == 'trusted source'
            assert payload[1]['source_description'] == ''
            return {
                'digest':{'headline':'Decision-changing release','what_changed':['new API']},
                'items':[{
                    'item_id':'important','relevance':.9,'novelty':.8,'actionability':.7,
                    'confidence':.9,'importance':.9,'reason':'It changes the integration plan.',
                    'signal':'API shipped','disposition':'attention',
                }],
            }

    profiles={'x':SourceProfile(name='x',category='software',description='trusted source')}
    screener=SemanticScreener(ModelLLM(),profiles)
    high=Candidate(id='important',source='x',title='Important',url='https://x',heuristic_score=.8)
    low=Candidate(id='missing',source='unknown',title='Fallback',url='https://y',heuristic_score=.3)
    digest, ranked, used=await screener.screen(QueryPlan(goal='decide'),[high,low])
    assert used is True
    assert digest.headline == 'Decision-changing release'
    assert ranked[0].id == 'important'
    assert ranked[0].signal == 'API shipped'
    assert ranked[1].id == 'missing'
    assert ranked[1].disposition == 'background'


async def test_screening_empty_and_model_failure_paths():
    class BrokenLLM:
        available=True

        async def json(self, system, user):
            raise RuntimeError('offline')

    plan=QueryPlan(goal='x',uncertainties=['unknown'])
    screener=SemanticScreener(BrokenLLM(),{})
    digest, ranked, used=await screener.screen(plan,[])
    assert digest.unresolved == ['unknown']
    assert ranked == []
    assert used is True
    item=Candidate(id='x',source='x',title='Fallback',url='https://x',heuristic_score=.5)
    digest, ranked, used=await screener.screen(plan,[item])
    assert used is False
    assert digest.what_changed == ['Fallback']
    assert ranked[0].disposition == 'watch'
