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
from .sources.transport import classify_source_error
from .store import Store


class AttentionPipeline:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        store: Store,
        direct_client: httpx.AsyncClient | None = None,
    ):
        self.client = client
        self.settings = settings
        self.store = store
        self.sources = (
            build_sources(client, settings)
            if direct_client is None
            else build_sources(client, settings, direct_client)
        )
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
        for query, items, error, fallback_result in results:
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
                'result_count': 0 if error else len(items),
                'ok': not bool(error),
            })
            if fallback_result:
                fallback_query, fallback_count, fallback_error = fallback_result
                fallback_profile = self.profiles[fallback_query.source]
                query_events.append({
                    'source': fallback_query.source,
                    'category': fallback_profile.category,
                    'query': fallback_query.query,
                    'purpose': fallback_query.purpose,
                    'mode': fallback_query.mode,
                    'result_count': fallback_count,
                    'ok': not bool(fallback_error),
                })
                if fallback_error:
                    errors[fallback_query.source] = fallback_error
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
                return query, items, '', None
            except Exception as exc:
                failure_type, http_status, error = classify_source_error(exc)
                self.store.record_source_health(
                    query.source, False, error, failure_type, http_status,
                )
                fallback_name = (
                    self.settings.source_config.get('sources', {})
                    .get(query.source, {}).get('fallback_source', '')
                )
                if (
                    failure_type not in {'timeout', 'connect_error', 'transport_error', 'server_error'}
                    or not fallback_name
                    or fallback_name == query.source
                    or fallback_name not in self.sources
                ):
                    return query, [], error, None

                fallback_query = query.model_copy(update={'source': fallback_name})
                try:
                    fallback_items = await self.sources[fallback_name].search(
                        fallback_query, horizon_hours,
                    )
                    self.store.record_source_health(fallback_name, True)
                    return query, fallback_items, error, (fallback_query, len(fallback_items), '')
                except Exception as fallback_exc:
                    fallback_type, fallback_status, fallback_error = classify_source_error(fallback_exc)
                    self.store.record_source_health(
                        fallback_name, False, fallback_error, fallback_type, fallback_status,
                    )
                    return query, [], error, (fallback_query, 0, fallback_error)
