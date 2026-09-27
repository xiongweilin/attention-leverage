from pathlib import Path
import sqlite3

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
    store.record_source_health('feed', False, 'HTTP 403', 'http_error', 403)
    health = store.health()[0]
    assert (health['successes'], health['failures']) == (1, 1)
    assert health['current_status'] == 'error'
    assert health['last_failure_type'] == 'http_error'
    assert health['last_http_status'] == 403
    assert health['consecutive_failures'] == 1
    store.record_source_health('feed', True)
    health = store.health()[0]
    assert health['current_status'] == 'ok'
    assert health['consecutive_failures'] == 0
    assert health['last_error'] == 'HTTP 403'
    assert health['last_failure_type'] == 'http_error'
    assert health['last_attempt_at'] == health['last_ok']

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


def test_store_migrates_legacy_source_health_to_latest_known_status(tmp_path: Path):
    database = tmp_path / 'legacy-health.db'
    with sqlite3.connect(database) as db:
        db.execute('''
            CREATE TABLE source_health (
                source TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                last_ok TEXT,
                last_error TEXT,
                last_error_at TEXT
            )
        ''')
        db.executemany(
            'INSERT INTO source_health(source,successes,failures,last_ok,last_error,last_error_at) '
            'VALUES(?,?,?,?,?,?)',
            [
                ('recovered', 3, 1, '2026-09-27T11:00:00+00:00', 'old error', '2026-09-27T10:00:00+00:00'),
                ('failing', 1, 2, '2026-09-27T10:00:00+00:00', 'latest error', '2026-09-27T11:00:00+00:00'),
            ],
        )

    health = {row['source']: row for row in Store(str(database)).health()}
    assert health['recovered']['current_status'] == 'ok'
    assert health['recovered']['last_attempt_at'] == health['recovered']['last_ok']
    assert health['recovered']['last_failure_type'] == 'legacy'
    assert health['failing']['current_status'] == 'error'
    assert health['failing']['last_attempt_at'] == health['failing']['last_error_at']
    assert health['failing']['last_failure_type'] == 'legacy'
