from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Disposition = Literal['attention', 'watch', 'background']
Authority = Literal['primary', 'institutional', 'community', 'aggregator', 'unknown']


class SourceProfile(BaseModel):
    name: str
    category: str
    description: str
    authority: Authority = 'unknown'
    queryable: bool = True
    signal_kind: str = 'content'
    cost: Literal['low', 'medium', 'high'] = 'low'
    enabled: bool = True


class SourceQuery(BaseModel):
    source: str
    query: str = ''
    purpose: str = ''
    limit: int = Field(default=10, ge=1, le=50)


class QueryPlan(BaseModel):
    goal: str
    horizon_hours: int = Field(default=72, ge=1, le=24 * 365)
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    desired_signals: list[str] = Field(default_factory=list)
    source_queries: list[SourceQuery] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)


class RawItem(BaseModel):
    id: str
    source: str
    source_category: str = ''
    title: str
    url: str
    summary: str = ''
    published_at: datetime | None = None
    query: str = ''
    authority: Authority = 'unknown'
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Candidate(RawItem):
    heuristic_score: float = 0.0
    lexical_score: float = 0.0
    recency_score: float = 0.0
    source_weight: float = 1.0
    history_novelty: float = 1.0
    seen_count: int = 0
    matched_terms: list[str] = Field(default_factory=list)


class Screening(BaseModel):
    item_id: str
    relevance: float = Field(ge=0, le=1)
    novelty: float = Field(ge=0, le=1)
    actionability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    reason: str
    signal: str = ''
    disposition: Disposition = 'background'


class Digest(BaseModel):
    headline: str = ''
    what_changed: list[str] = Field(default_factory=list)
    possible_actions: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class RankedItem(Candidate):
    relevance: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0
    confidence: float = 0.0
    importance: float = 0.0
    reason: str = ''
    signal: str = ''
    disposition: Disposition = 'background'
    score: float = 0.0


class RunRequest(BaseModel):
    input: str = Field(min_length=2, max_length=5000)
    horizon_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    max_output_items: int | None = Field(default=None, ge=1, le=100)


class RunResult(BaseModel):
    run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    plan: QueryPlan
    digest: Digest
    raw_count: int
    filtered_count: int
    items: list[RankedItem]
    model_used_for_planning: bool
    model_used_for_screening: bool
    source_errors: dict[str, str] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)


class SavedGoal(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=2, max_length=5000)
    horizon_hours: int = Field(default=72, ge=1, le=24 * 365)
    enabled: bool = True


class FeedbackRequest(BaseModel):
    item_id: str
    source: str
    useful: bool
    note: str = Field(default='', max_length=1000)
