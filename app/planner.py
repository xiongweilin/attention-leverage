from __future__ import annotations

import re

from .llm import OpenAICompatibleLLM
from .models import QueryPlan, SourceQuery

SOURCE_DESCRIPTIONS = {
    "google_news": "broad current news and mainstream coverage",
    "gdelt": "global multilingual news/event coverage",
    "hackernews": "technology/startup practitioner discussion",
    "github": "software projects, tools and repository activity",
    "openalex": "scholarly works across disciplines",
    "arxiv": "recent technical/scientific preprints",
    "crossref": "published scholarly literature and metadata",
    "stackexchange": "practical technical questions and answers",
    "rss": "configured trusted or niche RSS/Atom feeds",
}


class GoalPlanner:
    def __init__(self, llm: OpenAICompatibleLLM, enabled_sources: list[str]):
        self.llm = llm
        self.enabled_sources = enabled_sources

    async def plan(self, user_input: str, horizon_hours: int | None = None) -> tuple[QueryPlan, bool]:
        if self.llm.available:
            try:
                data = await self.llm.json(
                    system=self._system_prompt(),
                    user=user_input,
                )
                plan = QueryPlan.model_validate(data)
                plan.source_queries = [q for q in plan.source_queries if q.source in self.enabled_sources]
                if horizon_hours is not None:
                    plan.horizon_hours = horizon_hours
                if not plan.source_queries:
                    plan.source_queries = self._fallback_queries(user_input)
                return plan, True
            except Exception:
                pass
        return self._fallback_plan(user_input, horizon_hours), False

    def _system_prompt(self) -> str:
        sources = "\n".join(
            f"- {name}: {SOURCE_DESCRIPTIONS[name]}"
            for name in self.enabled_sources
            if name in SOURCE_DESCRIPTIONS
        )
        return f"""You convert a person's current information need into a bounded search plan.
The objective is not maximum content. It is to maximize the chance that decision-changing information is discovered while minimizing later human attention.

Available sources:
{sources}

Return one JSON object with exactly these top-level fields:
- goal: concise operational goal
- horizon_hours: integer, default 72 unless the request implies another horizon
- keywords: 4-12 high-signal terms, including useful synonyms
- exclude_keywords: obvious noise terms if any
- desired_signals: 2-8 kinds of changes/evidence that would change a decision
- source_queries: array of objects {{source, query, purpose, limit}}, using only available sources, at most 3 queries per source
- uncertainties: important unknowns that search should help discriminate

Use heterogeneous sources when useful. Prefer source-specific query wording. Do not invent facts. Search plans are provisional, not conclusions."""

    def _fallback_queries(self, text: str) -> list[SourceQuery]:
        query = " ".join(text.split())[:240]
        return [
            SourceQuery(source=s, query=query, purpose="fallback broad search", limit=10)
            for s in self.enabled_sources
        ]

    def _fallback_plan(self, text: str, horizon_hours: int | None) -> QueryPlan:
        terms = [
            t.lower()
            for t in re.findall(r"[A-Za-z0-9_+.#-]{3,}|[\u4e00-\u9fff]{2,}", text)
        ]
        seen: set[str] = set()
        keywords = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                keywords.append(term)
            if len(keywords) >= 12:
                break
        return QueryPlan(
            goal=" ".join(text.split())[:500],
            horizon_hours=horizon_hours or 72,
            keywords=keywords,
            desired_signals=["material change", "credible counterevidence", "new actionable option"],
            source_queries=self._fallback_queries(text),
            uncertainties=["Model planning unavailable; source queries use the raw input."],
        )
