from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import httpx

from .config import Settings
from .filtering import balanced_cap, deterministic_filter
from .llm import OpenAICompatibleLLM
from .models import RunRequest, RunResult
from .planner import GoalPlanner
from .screening import SemanticScreener
from .sources import build_sources
from .store import Store


class AttentionPipeline:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, store: Store):
        self.client = client
        self.settings = settings
        self.store = store
        self.sources = build_sources(client, settings)
        self.profiles = {name: source.profile for name, source in self.sources.items()}
        self.llm = OpenAICompatibleLLM(client, settings)
        self.planner = GoalPlanner(self.llm, self.profiles)
        self.screener = SemanticScreener(self.llm, self.profiles)
        self._semaphore = asyncio.Semaphore(settings.source_concurrency)

    async def run(self, request: RunRequest) -> RunResult:
        plan, planned_with_model = await self.planner.plan(request.input, request.horizon_hours)
        tasks = [self._run_source(q, plan.horizon_hours) for q in plan.source_queries if q.source in self.sources]
        results = await asyncio.gather(*tasks) if tasks else []

        raw = []
        errors: dict[str, str] = {}
        for source_name, items, error in results:
            raw.extend(items)
            if error:
                errors[source_name] = error
        raw = balanced_cap(raw, self.settings.max_raw_items)
        history = self.store.history([x.id for x in raw])
        source_weights = self.store.source_weights()
        filtered = deterministic_filter(
            raw, plan, history=history, source_weights=source_weights,
            max_items=self.settings.max_filtered_items,
            per_source_quota=max(4, self.settings.max_filtered_items // max(1, len(self.sources) // 2)),
        )
        digest, ranked, screened_with_model = await self.screener.screen(plan, filtered)
        output_limit = request.max_output_items or self.settings.max_output_items
        ranked = ranked[:output_limit]

        result = RunResult(
            run_id=uuid.uuid4().hex[:16], plan=plan, digest=digest,
            raw_count=len(raw), filtered_count=len(filtered), items=ranked,
            model_used_for_planning=planned_with_model,
            model_used_for_screening=screened_with_model,
            source_errors=errors,
            source_counts=dict(Counter(x.source for x in raw)),
        )
        self.store.observe_items(raw)
        self.store.record_run(result)
        return result

    async def _run_source(self, query, horizon_hours):
        source = self.sources[query.source]
        async with self._semaphore:
            try:
                items = await source.search(query, horizon_hours)
                self.store.record_source_health(query.source, True)
                return query.source, items, ''
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
                self.store.record_source_health(query.source, False, error)
                return query.source, [], error
