from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Candidate, QueryPlan, RawItem

TRACKING_KEYS = {'utm_source','utm_medium','utm_campaign','utm_term','utm_content','gclid','fbclid','ref','source'}
AUTHORITY_WEIGHT = {'primary': 1.08, 'institutional': 1.04, 'community': 0.96, 'aggregator': 0.94, 'unknown': 0.95}


def norm_text(value: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\u4e00-\u9fff]+', ' ', value.lower())).strip()


def canonical_url(url: str) -> str:
    try:
        p = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_KEYS]
        path = p.path.rstrip('/') or '/'
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ''))
    except Exception:
        return url


def term_matches(item: RawItem, plan: QueryPlan) -> tuple[float, list[str]]:
    hay = norm_text(f'{item.title} {item.summary}')
    matched = [term for term in plan.keywords if norm_text(term) and norm_text(term) in hay]
    if any(norm_text(term) and norm_text(term) in hay for term in plan.exclude_keywords):
        return -1.0, matched
    if not plan.keywords:
        return 0.35, []
    denom = max(2, min(8, len(plan.keywords)))
    return min(1.0, len(matched) / denom), matched


def recency_score(published_at: datetime | None, horizon_hours: int) -> float:
    if published_at is None:
        return 0.3
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600)
    scale = max(8.0, horizon_hours / 2)
    return math.exp(-age_hours / scale)


def balanced_cap(items: list[RawItem], limit: int) -> list[RawItem]:
    if len(items) <= limit:
        return items
    buckets: dict[str, list[RawItem]] = {}
    for item in items:
        buckets.setdefault(item.source, []).append(item)
    out: list[RawItem] = []
    while len(out) < limit and buckets:
        for source in list(buckets):
            bucket = buckets[source]
            if bucket:
                out.append(bucket.pop(0))
                if len(out) >= limit:
                    break
            if not bucket:
                buckets.pop(source, None)
    return out


def deterministic_filter(
    items: list[RawItem],
    plan: QueryPlan,
    *,
    history: dict[str, dict] | None = None,
    source_weights: dict[str, float] | None = None,
    max_items: int = 72,
    per_source_quota: int = 10,
) -> list[Candidate]:
    history = history or {}
    source_weights = source_weights or {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=plan.horizon_hours * 2)
    scored: list[Candidate] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []

    for item in items:
        if item.published_at is not None:
            pub = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                continue
        canon = canonical_url(item.url)
        title_norm = norm_text(item.title)
        if canon and canon in seen_urls:
            continue
        if title_norm and any(SequenceMatcher(None, title_norm, prior).ratio() >= .94 for prior in seen_titles[-180:]):
            continue

        lexical, matched = term_matches(item, plan)
        if lexical < 0:
            continue
        recency = recency_score(item.published_at, plan.horizon_hours)
        hist = history.get(item.id, {})
        seen_count = int(hist.get('seen_count', 0) or 0)
        novelty = 1.0 if seen_count == 0 else max(.15, 1 / math.sqrt(seen_count + 1))
        sw = source_weights.get(item.source, 1.0) * AUTHORITY_WEIGHT.get(item.authority, .95)
        heuristic = (0.46 * lexical + 0.26 * recency + 0.18 * novelty + 0.10) * sw
        scored.append(Candidate(
            **item.model_dump(), heuristic_score=min(1.25, heuristic), lexical_score=lexical,
            recency_score=recency, source_weight=sw, history_novelty=novelty,
            seen_count=seen_count, matched_terms=matched,
        ))
        if canon:
            seen_urls.add(canon)
        if title_norm:
            seen_titles.append(title_norm)

    scored.sort(key=lambda x: x.heuristic_score, reverse=True)
    selected: list[Candidate] = []
    counts: dict[str, int] = defaultdict(int)
    categories: set[str] = set()

    # First pass preserves heterogeneous categories.
    for item in scored:
        if item.source_category and item.source_category not in categories:
            selected.append(item); counts[item.source] += 1; categories.add(item.source_category)
            if len(selected) >= max_items:
                return selected

    # Second pass ensures each source can contribute once.
    for item in scored:
        if item in selected:
            continue
        if counts[item.source] == 0:
            selected.append(item); counts[item.source] += 1
            if len(selected) >= max_items:
                return selected

    for item in scored:
        if item in selected or counts[item.source] >= per_source_quota:
            continue
        selected.append(item); counts[item.source] += 1
        if len(selected) >= max_items:
            break
    return selected
