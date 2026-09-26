from app.models import Candidate, QueryPlan
from app.screening import SemanticScreener


class NoLLM:
    available = False


async def test_fallback_screening_is_sorted():
    screener = SemanticScreener(NoLLM())
    plan = QueryPlan(goal="x")
    low = Candidate(id="a", source="x", title="a", url="https://a", heuristic_score=.2)
    high = Candidate(id="b", source="x", title="b", url="https://b", heuristic_score=.8)
    ranked, used_model = await screener.screen(plan, [low, high])
    assert not used_model
    assert ranked[0].id == "b"
    assert ranked[0].disposition == "attention"
