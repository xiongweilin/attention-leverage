from pathlib import Path

from app.models import (
    AssumptionInput, CognitiveMap, Digest, EnvironmentInsight, FeedbackRequest,
    ModelChallenge, QueryPlan, RawItem, RunResult, SavedGoal, SourceProfile,
)
from app.store import Store


def test_store_tracks_history_feedback_and_goals(tmp_path: Path):
    store=Store(str(tmp_path/'a.db'))
    x=RawItem(id='x',source='s',source_category='network',title='t',url='https://x',query='people')
    assert store.history(['x'])=={}
    store.observe_items([x]); store.observe_items([x])
    assert store.history(['x'])['x']['seen_count']==2
    store.add_feedback(FeedbackRequest(item_id='x',source='s',useful=True))
    store.add_feedback(FeedbackRequest(item_id='x',source='s',useful=True))
    store.add_feedback(FeedbackRequest(item_id='x',source='s',useful=False))
    assert store.source_weights()['s'] > 1
    store.save_goal(SavedGoal(name='g',prompt='watch x'))
    assert store.list_goals()[0].name=='g'


def test_store_weights_health_run_history_and_goal_deletion(tmp_path: Path):
    store = Store(str(tmp_path / 'state.db'))
    for key in ('x','y','z','w'):
        store.add_feedback(FeedbackRequest(item_id=key, source='helpful', useful=True))
        store.add_feedback(FeedbackRequest(item_id=key, source='unhelpful', useful=False))
    store.add_feedback(FeedbackRequest(item_id='x', source='small-sample', useful=True))
    store.add_feedback(FeedbackRequest(item_id='y', source='small-sample', useful=True))
    weights = store.source_weights()
    assert weights['helpful'] == 1.25
    assert weights['unhelpful'] == .75
    assert 'small-sample' not in weights

    store.record_source_health('feed', True)
    store.record_source_health('feed', False, 'temporary error')
    health = store.health()[0]
    assert (health['successes'], health['failures']) == (1, 1)
    assert health['last_error'] == 'temporary error'

    result = RunResult(
        run_id='run-1', plan=QueryPlan(goal='watch agents'), digest=Digest(headline='A change'),
        raw_count=2, filtered_count=1, items=[],
        model_used_for_planning=False, model_used_for_screening=False,
    )
    store.record_run(result)
    assert store.get_run('run-1')['digest']['headline'] == 'A change'
    assert store.get_run('missing') is None
    assert store.recent_runs(10)[0]['run_id'] == 'run-1'

    store.save_goal(SavedGoal(name='remove-me', prompt='watch releases'))
    store.delete_goal('remove-me')
    assert store.list_goals() == []


def test_store_tracks_query_coverage_assumptions_and_environments(tmp_path: Path):
    store = Store(str(tmp_path / 'cognitive.db'))
    store.record_query_events('run-a', [
        {'source':'people','category':'people_network','query':'connectors','purpose':'find connectors',
         'mode':'environment','result_count':3,'ok':True},
        {'source':'grants','category':'grants_opportunities','query':'fellowship','purpose':'find timing',
         'mode':'blindspot','result_count':0,'ok':True},
    ])
    coverage = {x['category']:x for x in store.coverage()}
    assert coverage['people_network']['searches'] == 1
    assert coverage['people_network']['results'] == 3
    assert coverage['grants_opportunities']['results'] == 0

    assumption = store.save_assumption(AssumptionInput(
        statement='Formal credentials are the main entry barrier', scope='target industry', confidence=.7,
    ))
    assert assumption.status == 'active'
    assert store.list_assumptions()[0].id == assumption.id

    cognitive = CognitiveMap(
        distant_environments=[EnvironmentInsight(
            name='professional association committees', distance=.85,
            entry_points=['public volunteer application'], hidden_rules=['follow up after events'],
        )],
        model_failures=[ModelChallenge(
            assumption_id=assumption.id,
            assumption=assumption.statement,
            signal='Multiple public volunteer entry points exist',
            why_it_matters='The barrier may be relationship-building rather than credentials alone.',
            severity=.8, strength='strong',
        )],
    )
    result = RunResult(
        run_id='run-cognitive', plan=QueryPlan(goal='map entry paths'),
        digest=Digest(headline='Environment changed'), cognitive_map=cognitive,
        raw_count=1, filtered_count=1, items=[],
        model_used_for_planning=True, model_used_for_screening=True,
    )
    store.record_run(result)
    updated = store.list_assumptions()[0]
    assert updated.status == 'challenged'
    assert updated.last_challenged_at
    environments = store.environments()
    assert environments[0]['name'] == 'professional association committees'
    assert environments[0]['times_seen'] == 1

    profiles = {
        'people': SourceProfile(name='people',category='people_network',description='people'),
        'institutions': SourceProfile(name='institutions',category='institutions',description='institutions'),
    }
    context = store.cognitive_context(profiles)
    assert any(x['category']=='institutions' for x in context['underexplored_categories'])
    assert context['recent_model_challenges'][0]['strength'] == 'strong'
    overview = store.cognitive_overview(profiles)
    assert overview['environments'][0]['name'] == 'professional association committees'

    store.delete_assumption(assumption.id)
    assert store.list_assumptions() == []
