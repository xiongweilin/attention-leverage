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
        run_id = uuid.uuid4().hex[:16]
        cognitive_context = self.store.cognitive_context(self.profiles)
        plan, planned_with_model = await self.planner.plan(
            request.input,
            request.horizon_hours,
            cognitive_context,
        )
        tasks = [
            self._run_source(q, plan.horizon_hours)
            for q in plan.source_queries
            if q.source in self.sources
        ]
        results = await asyncio.gather(*tasks) if tasks else []

        raw = []
        errors: dict[str, str] = {}
        query_events: list[dict] = []
        for query, items, error in results:
            raw.extend(items)
            if error:
                errors[query.source] = error
            profile = self.profiles.get(query.source)
            query_events.append({
                'source': query.source,
                'category': profile.category if profile else '',
                'query': query.query,
                'purpose': query.purpose,
                'mode': query.mode,
                'result_count': len(items),
                'ok': not bool(error),
            })
        self.store.record_query_events(run_id, query_events)

        raw = balanced_cap(raw, self.settings.max_raw_items)
        history = self.store.history([x.id for x in raw])
        source_weights = self.store.source_weights()
        filtered = deterministic_filter(
            raw,
            plan,
            history=history,
            source_weights=source_weights,
            max_items=self.settings.max_filtered_items,
            per_source_quota=max(
                4,
                self.settings.max_filtered_items // max(1, len(self.sources) // 2),
            ),
        )
        digest, cognitive_map, ranked, screened_with_model = await self.screener.screen(
            plan,
            filtered,
            cognitive_context,
        )
        output_limit = request.max_output_items or self.settings.max_output_items
        ranked = ranked[:output_limit]

        result = RunResult(
            run_id=run_id,
            plan=plan,
            digest=digest,
            cognitive_map=cognitive_map,
            raw_count=len(raw),
            filtered_count=len(filtered),
            items=ranked,
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
                return query, items, ''
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
                self.store.record_source_health(query.source, False, error)
                return query, [], error
