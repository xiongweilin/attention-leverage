from pathlib import Path

from app.models import FeedbackRequest, RawItem, SavedGoal
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
