from __future__ import annotations

import asyncio

import httpx

from .config import Settings
from .filtering import deterministic_filter
from .llm import OpenAICompatibleLLM
from .models import RawItem, RunRequest, RunResult
from .planner import GoalPlanner
from .screening import SemanticScreener
from .sources import build_sources


class AttentionPipeline:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings
        self.sources = build_sources(client, settings)
        self.llm = OpenAICompatibleLLM(client, settings)
        self.planner = GoalPlanner(self.llm, list(self.sources))
        self.screener = SemanticScreener(self.llm)

    async def run(self, request: RunRequest) -> RunResult:
        plan, planned_with_model = await self.planner.plan(request.input, request.horizon_hours)
        tasks = [self._run_source(q, plan.horizon_hours) for q in plan.source_queries if q.source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        raw: list[RawItem] = []
        errors: dict[str, str] = {}
        for source_name, items, error in results:
            if error:
                errors[source_name] = error
            raw.extend(items)
        raw = raw[: self.settings.max_raw_items]

        filtered = deterministic_filter(
            raw,
            plan,
            max_items=self.settings.max_filtered_items,
            per_source_quota=max(4, self.settings.max_filtered_items // max(1, len(self.sources))),
        )
        ranked, screened_with_model = await self.screener.screen(plan, filtered)
        ranked = ranked[: self.settings.max_output_items]

        return RunResult(
            plan=plan,
            raw_count=len(raw),
            filtered_count=len(filtered),
            items=ranked,
            model_used_for_planning=planned_with_model,
            model_used_for_screening=screened_with_model,
            source_errors=errors,
        )

    async def _run_source(self, query, horizon_hours):
        source = self.sources[query.source]
        try:
            items = await source.search(query, horizon_hours)
            return query.source, items, ""
        except Exception as exc:
            return query.source, [], f"{type(exc).__name__}: {exc}"
