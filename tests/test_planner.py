from app.planner import GoalPlanner


class NoLLM:
    available = False


async def test_fallback_plan_queries_all_enabled_sources():
    planner = GoalPlanner(NoLLM(), ["gdelt", "github", "openalex"])
    plan, used_model = await planner.plan("跟踪 agent runtime 的关键变化", 48)
    assert not used_model
    assert plan.horizon_hours == 48
    assert {q.source for q in plan.source_queries} == {"gdelt", "github", "openalex"}
