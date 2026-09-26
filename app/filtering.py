from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Candidate, QueryPlan, RawItem

TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\u4e00-\u9fff]+", " ", value.lower())).strip()


def _canonical_url(url: str) -> str:
    try:
        p = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_KEYS]
        path = p.path.rstrip("/") or "/"
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ""))
    except Exception:
        return url


def _term_matches(item: RawItem, plan: QueryPlan) -> tuple[float, list[str]]:
    hay = _norm_text(f"{item.title} {item.summary}")
    if not hay:
        return 0.0, []
    matched = [term for term in plan.keywords if _norm_text(term) and _norm_text(term) in hay]
    excluded = [term for term in plan.exclude_keywords if _norm_text(term) and _norm_text(term) in hay]
    if excluded:
        return -1.0, matched
    denom = max(2, min(8, len(plan.keywords) or 2))
    return min(1.0, len(matched) / denom), matched


def _recency_score(published_at: datetime | None, horizon_hours: int) -> float:
    if published_at is None:
        return 0.35
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (datetime.now(timezone.utc) - published_at.astimezone(timezone.utc)).total_seconds() / 3600)
    scale = max(6.0, horizon_hours / 2)
    return math.exp(-age_hours / scale)


def deterministic_filter(
    items: list[RawItem],
    plan: QueryPlan,
    *,
    max_items: int = 60,
    per_source_quota: int = 12,
) -> list[Candidate]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=plan.horizon_hours * 1.5)
    scored: list[Candidate] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []

    for item in items:
        if item.published_at is not None:
            pub = item.published_at if item.published_at.tzinfo else item.published_at.replace(tzinfo=timezone.utc)
            if pub < cutoff:
                continue

        canonical = _canonical_url(item.url)
        title_norm = _norm_text(item.title)
        if canonical and canonical in seen_urls:
            continue
        if title_norm and any(SequenceMatcher(None, title_norm, prior).ratio() >= 0.93 for prior in seen_titles[-120:]):
            continue

        lexical, matched = _term_matches(item, plan)
        if lexical < 0:
            continue
        recency = _recency_score(item.published_at, plan.horizon_hours)
        heuristic = 0.62 * lexical + 0.38 * recency
        scored.append(Candidate(**item.model_dump(), heuristic_score=heuristic, matched_terms=matched))
        if canonical:
            seen_urls.add(canonical)
        if title_norm:
            seen_titles.append(title_norm)

    scored.sort(key=lambda x: x.heuristic_score, reverse=True)
    selected: list[Candidate] = []
    counts: dict[str, int] = defaultdict(int)

    for item in scored:
        if counts[item.source] == 0:
            selected.append(item)
            counts[item.source] += 1
            if len(selected) >= max_items:
                return selected

    for item in scored:
        if item in selected or counts[item.source] >= per_source_quota:
            continue
        selected.append(item)
        counts[item.source] += 1
        if len(selected) >= max_items:
            break
    return selected
