from datetime import datetime, timezone

from app.filtering import balanced_cap, deterministic_filter
from app.models import QueryPlan, RawItem


def item(i, source, category, title, url, authority='community'):
    return RawItem(id=str(i), source=source, source_category=category, title=title, url=url,
                   published_at=datetime.now(timezone.utc), query='ai agents', authority=authority)


def test_balanced_cap_preserves_sources():
    items=[item(i,'a','x',str(i),f'https://a/{i}') for i in range(10)] + [item(20+i,'b','y',str(i),f'https://b/{i}') for i in range(3)]
    assert [x.source for x in balanced_cap(items,6)] == ['a','b','a','b','a','b']


def test_filter_preserves_category_diversity_and_dedupes():
    plan=QueryPlan(goal='track agent infra',keywords=['agent','infrastructure'])
    items=[
        item(1,'github','open_source','Agent infrastructure release','https://x/a?utm_source=z','primary'),
        item(2,'news','news','Agent infrastructure release','https://x/a','aggregator'),
        item(3,'paper','research','Agent infrastructure benchmark','https://x/b','institutional'),
        item(4,'social','social','Agent runtime failure report','https://x/c','community'),
    ]
    out=deterministic_filter(items,plan,max_items=3,per_source_quota=2)
    assert len(out)==3
    assert len({x.source_category for x in out})==3
