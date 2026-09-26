from datetime import datetime, timezone

from app.filtering import (
    balanced_cap, canonical_url, deterministic_filter, norm_text, recency_score, term_matches,
)
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


def test_normalization_url_canonicalization_terms_and_recency():
    assert norm_text(' A+B / 中文  text ') == 'a b 中文 text'
    assert canonical_url('HTTPS://EXAMPLE.test/a/?utm_source=x&keep=&REF=y#frag') == 'https://example.test/a?keep='

    plan = QueryPlan(goal='find agent infrastructure', keywords=['agent', 'infrastructure'],
                     exclude_keywords=['spam'])
    candidate = item('a', 'src', 'news', 'Agent infrastructure', 'https://x/a')
    score, matched = term_matches(candidate, plan)
    assert score == 1.0
    assert matched == ['agent', 'infrastructure']
    excluded = item('b', 'src', 'news', 'Agent spam', 'https://x/b')
    assert term_matches(excluded, plan)[0] == -1.0
    assert term_matches(candidate, QueryPlan(goal='anything'))[0] == .35
    assert recency_score(None, 24) == .3
    assert recency_score(datetime.now(timezone.utc), 24) > .99
    assert recency_score(datetime(2000, 1, 1), 24) < .01


def test_balanced_cap_handles_small_and_round_robin_inputs():
    a = item('a', 'source-a', 'news', 'a', 'https://a/1')
    b = item('b', 'source-b', 'paper', 'b', 'https://b/1')
    c = item('c', 'source-a', 'news', 'c', 'https://a/2')
    assert balanced_cap([a, b], 2) == [a, b]
    assert [x.id for x in balanced_cap([a, c, b], 2)] == ['a', 'b']
    assert balanced_cap([a, c, b], 0) == []


def test_filter_skips_old_excluded_duplicate_and_applies_history_weights():
    now = datetime.now(timezone.utc)
    plan = QueryPlan(goal='agent release', horizon_hours=24, keywords=['agent'], exclude_keywords=['spam'])
    items = [
        RawItem(id='old', source='old', source_category='news', title='Agent old', url='https://old',
                published_at=now.replace(year=now.year - 2)),
        item('excluded', 'noise', 'news', 'Spam agent report', 'https://x/noise'),
        item('first', 'github', 'open_source', 'Agent toolkit release', 'https://x/a?utm_source=mail', 'primary'),
        item('url-dupe', 'news', 'news', 'Different title', 'https://x/a', 'aggregator'),
        item('title-dupe', 'paper', 'research', 'Agent toolkit release', 'https://x/b', 'institutional'),
        item('second', 'news', 'news', 'Agent runtime update', 'https://x/c', 'community'),
    ]
    candidates = deterministic_filter(
        items, plan, history={'second': {'seen_count': 3}}, source_weights={'news': .75},
        max_items=10, per_source_quota=3,
    )
    assert {candidate.id for candidate in candidates} == {'first', 'second'}
    second = next(candidate for candidate in candidates if candidate.id == 'second')
    assert second.seen_count == 3
    assert second.history_novelty == .5
    assert second.source_weight < 1


def test_filter_selection_caps_sources_and_handles_empty_or_zero_limit():
    plan = QueryPlan(goal='agent', keywords=['agent'])
    items = [item(i, 'one', 'same', f'Agent topic {i}', f'https://x/{i}') for i in range(4)]
    items += [item(10 + i, 'two', 'other', f'Agent other {i}', f'https://y/{i}') for i in range(4)]
    selected = deterministic_filter(items, plan, max_items=5, per_source_quota=2)
    assert len(selected) == 4
    assert {x.source for x in selected} == {'one', 'two'}
    assert deterministic_filter([], plan) == []
