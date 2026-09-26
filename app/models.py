from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Disposition = Literal['attention', 'watch', 'background']
Authority = Literal['primary', 'institutional', 'community', 'aggregator', 'unknown']
QueryMode = Literal['goal', 'blindspot', 'counterevidence', 'environment', 'verification']
AssumptionStatus = Literal['active', 'challenged', 'retired']
AssumptionOrigin = Literal['user', 'inferred']
ChallengeStrength = Literal['weak', 'watch', 'strong']


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
    mode: QueryMode = 'goal'
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
    working_assumptions: list[str] = Field(default_factory=list)
    exploration_questions: list[str] = Field(default_factory=list)


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
    model_pressure: float = Field(default=0, ge=0, le=1)
    environment_distance: float = Field(default=0, ge=0, le=1)
    reason: str
    signal: str = ''
    disposition: Disposition = 'background'


class Digest(BaseModel):
    headline: str = ''
    what_changed: list[str] = Field(default_factory=list)
    possible_actions: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class BlindSpot(BaseModel):
    area: str
    why_unseen: str = ''
    evidence_gap: str = ''
    suggested_probe: str = ''
    severity: float = Field(default=.5, ge=0, le=1)


class EnvironmentInsight(BaseModel):
    name: str
    description: str = ''
    distance: float = Field(default=.5, ge=0, le=1)
    why_distant: str = ''
    entry_points: list[str] = Field(default_factory=list)
    hidden_rules: list[str] = Field(default_factory=list)
    connectors: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    timing: list[str] = Field(default_factory=list)
    low_cost_entries: list[str] = Field(default_factory=list)
    evidence_item_ids: list[str] = Field(default_factory=list)


class Reinterpretation(BaseModel):
    trigger: str
    old_frame: str = ''
    new_frame: str = ''
    confidence: float = Field(default=.5, ge=0, le=1)
    evidence_item_ids: list[str] = Field(default_factory=list)


class ModelChallenge(BaseModel):
    assumption_id: str = ''
    assumption: str
    signal: str
    why_it_matters: str = ''
    severity: float = Field(default=.5, ge=0, le=1)
    strength: ChallengeStrength = 'watch'
    evidence_item_ids: list[str] = Field(default_factory=list)


class CognitiveMap(BaseModel):
    long_unseen: list[BlindSpot] = Field(default_factory=list)
    distant_environments: list[EnvironmentInsight] = Field(default_factory=list)
    reinterpretations: list[Reinterpretation] = Field(default_factory=list)
    model_failures: list[ModelChallenge] = Field(default_factory=list)
    next_explorations: list[str] = Field(default_factory=list)


class RankedItem(Candidate):
    relevance: float = 0.0
    novelty: float = 0.0
    actionability: float = 0.0
    confidence: float = 0.0
    importance: float = 0.0
    model_pressure: float = 0.0
    environment_distance: float = 0.0
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
    cognitive_map: CognitiveMap = Field(default_factory=CognitiveMap)
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


class AssumptionInput(BaseModel):
    statement: str = Field(min_length=2, max_length=2000)
    scope: str = Field(default='', max_length=500)
    confidence: float = Field(default=.6, ge=0, le=1)


class Assumption(BaseModel):
    id: str
    statement: str
    scope: str = ''
    confidence: float = Field(default=.6, ge=0, le=1)
    status: AssumptionStatus = 'active'
    origin: AssumptionOrigin = 'user'
    created_at: str = ''
    updated_at: str = ''
    last_challenged_at: str = ''
