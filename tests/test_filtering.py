from datetime import datetime, timezone

from app.filtering import deterministic_filter
from app.models import QueryPlan, RawItem


def item(i, source, title, url):
    return RawItem(
        id=str(i), source=source, title=title, url=url, summary="",
        published_at=datetime.now(timezone.utc), query="ai agents",
    )


def test_filter_deduplicates_and_preserves_source_diversity():
    plan = QueryPlan(goal="track ai agent infrastructure", keywords=["ai", "agent", "infrastructure"])
    items = [
        item(1, "github", "AI agent infrastructure release", "https://x.test/a?utm_source=z"),
        item(2, "google_news", "AI agent infrastructure release", "https://x.test/a"),
        item(3, "openalex", "Agent infrastructure benchmark", "https://x.test/b"),
        item(4, "hackernews", "New agent runtime", "https://x.test/c"),
    ]
    out = deterministic_filter(items, plan, max_items=3, per_source_quota=2)
    assert len(out) == 3
    assert len({x.source for x in out}) == 3
    assert len({x.url.split("?")[0] for x in out}) == 3
