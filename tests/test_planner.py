from app.models import SourceProfile
from app.planner import GoalPlanner


class NoLLM:
    available=False


async def test_fallback_plan_uses_category_balanced_sources():
    profiles={
        'a':SourceProfile(name='a',category='news',description='a'),
        'b':SourceProfile(name='b',category='news',description='b'),
        'c':SourceProfile(name='c',category='research',description='c'),
    }
    plan,used=await GoalPlanner(NoLLM(),profiles).plan('跟踪 agent runtime 变化',48)
    assert not used
    assert plan.horizon_hours==48
    assert {q.source for q in plan.source_queries}=={'a','c'}
