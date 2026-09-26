from pathlib import Path

from app.models import Digest, FeedbackRequest, QueryPlan, RawItem, RunResult, SavedGoal
from app.store import Store


def test_store_tracks_history_feedback_and_goals(tmp_path: Path):
    store=Store(str(tmp_path/'a.db'))
    x=RawItem(id='x',source='s',title='t',url='https://x')
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
    store.add_feedback(FeedbackRequest(item_id='x', source='helpful', useful=True))
    store.add_feedback(FeedbackRequest(item_id='y', source='helpful', useful=True))
    store.add_feedback(FeedbackRequest(item_id='z', source='helpful', useful=True))
    store.add_feedback(FeedbackRequest(item_id='w', source='helpful', useful=True))
    store.add_feedback(FeedbackRequest(item_id='x', source='unhelpful', useful=False))
    store.add_feedback(FeedbackRequest(item_id='y', source='unhelpful', useful=False))
    store.add_feedback(FeedbackRequest(item_id='z', source='unhelpful', useful=False))
    store.add_feedback(FeedbackRequest(item_id='w', source='unhelpful', useful=False))
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
