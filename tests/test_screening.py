import json

from app.models import Candidate, QueryPlan, SourceProfile
from app.screening import SemanticScreener


class NoLLM:
    available=False


async def test_fallback_screening_sorted_and_exposes_blindspots():
    profiles={'x':SourceProfile(name='x',category='test',description='x')}
    s=SemanticScreener(NoLLM(),profiles)
    high=Candidate(id='b',source='x',source_category='test',title='b',url='https://b',heuristic_score=.8)
    low=Candidate(id='a',source='x',source_category='known',title='a',url='https://a',heuristic_score=.2)
    context={'underexplored_categories':[{'category':'test','searches':0,'items':0,'reason':'never searched'}]}
    digest,cognitive,ranked,used=await s.screen(QueryPlan(goal='x'),[low,high],context)
    assert not used
    assert ranked[0].id=='b'
    assert ranked[0].disposition=='attention'
    assert ranked[0].environment_distance == .65
    assert digest.headline
    assert cognitive.long_unseen[0].area == 'test'
    assert cognitive.next_explorations


async def test_model_screening_merges_cognitive_map_and_item_pressure():
    class ModelLLM:
        available=True

        async def json(self, system, user):
            assert 'Goal: decide' in system
            assert 'What has probably not entered' in system
            payload = json.loads(user)
            assert payload['candidates'][0]['source_description'] == 'trusted source'
            assert payload['candidates'][1]['source_description'] == ''
            assert payload['cognitive_context']['assumptions'][0]['id'] == 'a1'
            return {
                'digest':{'headline':'Decision-changing release','what_changed':['new API']},
                'cognitive_map':{
                    'long_unseen':[{
                        'area':'institutions','why_unseen':'low coverage','evidence_gap':'few searches',
                        'suggested_probe':'search institution paths','severity':.7,
                    }],
                    'distant_environments':[{
                        'name':'institutional buyers','distance':.8,'why_distant':'few observations',
                        'entry_points':['public working group'],'evidence_item_ids':['important'],
                    }],
                    'reinterpretations':[{
                        'trigger':'new API','old_frame':'closed stack','new_frame':'open integration layer',
                        'confidence':.7,'evidence_item_ids':['important'],
                    }],
                    'model_failures':[{
                        'assumption_id':'a1','assumption':'API stays closed','signal':'API shipped',
                        'why_it_matters':'integration path changed','severity':.9,'strength':'strong',
                        'evidence_item_ids':['important'],
                    }],
                    'next_explorations':['verify adoption outside launch coverage'],
                },
                'items':[{
                    'item_id':'important','relevance':.9,'novelty':.8,'actionability':.7,
                    'confidence':.9,'importance':.9,'model_pressure':.95,'environment_distance':.7,
                    'reason':'It changes the integration plan.','signal':'API shipped',
                    'disposition':'attention',
                }],
            }

    profiles={'x':SourceProfile(name='x',category='software',description='trusted source')}
    screener=SemanticScreener(ModelLLM(),profiles)
    high=Candidate(id='important',source='x',title='Important',url='https://x',heuristic_score=.8)
    low=Candidate(id='missing',source='unknown',title='Fallback',url='https://y',heuristic_score=.3)
    context={'assumptions':[{'id':'a1','statement':'API stays closed'}]}
    digest, cognitive, ranked, used=await screener.screen(QueryPlan(goal='decide'),[high,low],context)
    assert used is True
    assert digest.headline == 'Decision-changing release'
    assert cognitive.model_failures[0].strength == 'strong'
    assert cognitive.distant_environments[0].entry_points == ['public working group']
    assert ranked[0].id == 'important'
    assert ranked[0].signal == 'API shipped'
    assert ranked[0].model_pressure == .95
    assert ranked[1].id == 'missing'
    assert ranked[1].disposition == 'background'


async def test_screening_empty_and_model_failure_paths():
    class BrokenLLM:
        available=True

        async def json(self, system, user):
            raise RuntimeError('offline')

    plan=QueryPlan(goal='x',uncertainties=['unknown'])
    context={'underexplored_categories':[{'category':'network','searches':0,'items':0,'reason':'not searched'}]}
    screener=SemanticScreener(BrokenLLM(),{})
    digest, cognitive, ranked, used=await screener.screen(plan,[],context)
    assert digest.unresolved == ['unknown']
    assert cognitive.long_unseen[0].area == 'network'
    assert ranked == []
    assert used is True
    item=Candidate(id='x',source='x',title='Fallback',url='https://x',heuristic_score=.5)
    digest, cognitive, ranked, used=await screener.screen(plan,[item],context)
    assert used is False
    assert digest.what_changed == ['Fallback']
    assert ranked[0].disposition == 'watch'
