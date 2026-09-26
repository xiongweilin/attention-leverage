from __future__ import annotations

import re

from .llm import OpenAICompatibleLLM
from .models import QueryPlan, SourceProfile, SourceQuery


class GoalPlanner:
    def __init__(self, llm: OpenAICompatibleLLM, profiles: dict[str, SourceProfile]):
        self.llm = llm
        self.profiles = profiles

    async def plan(self, user_input: str, horizon_hours: int | None = None) -> tuple[QueryPlan, bool]:
        if self.llm.available:
            try:
                data = await self.llm.json(self._system_prompt(), user_input)
                plan = QueryPlan.model_validate(data)
                plan.source_queries = [q for q in plan.source_queries if q.source in self.profiles]
                if horizon_hours is not None:
                    plan.horizon_hours = horizon_hours
                if not plan.source_queries:
                    plan.source_queries = self._fallback_queries(user_input)
                return plan, True
            except Exception:
                pass
        return self._fallback_plan(user_input, horizon_hours), False

    def _system_prompt(self) -> str:
        source_lines = []
        for p in self.profiles.values():
            source_lines.append(
                f'- {p.name} | category={p.category} | authority={p.authority} | '
                f'signal={p.signal_kind} | queryable={p.queryable}: {p.description}'
            )
        sources = '\n'.join(source_lines)
        return f'''You translate a person's current information need into a bounded, heterogeneous search plan.
The objective is to maximize the probability of discovering decision-changing information while minimizing later human attention.

Available sources:
{sources}

Return one JSON object with exactly these fields:
- goal: concise operational goal
- horizon_hours: integer; default 72 unless the request implies another horizon
- keywords: 5-16 high-signal terms and useful synonyms, multilingual when useful
- exclude_keywords: obvious noise terms
- desired_signals: 3-10 concrete changes/evidence that would alter a decision
- source_queries: array of {{source, query, purpose, limit}}; use only available source names; prefer 6-14 heterogeneous sources when the goal is broad; at most 2 queries per source
- uncertainties: important unknowns search should discriminate
- stop_conditions: conditions under which enough information has been found for the current purpose

Routing rules:
1. Select different information-generation mechanisms, not many near-duplicate news sources.
2. Use primary/institutional sources to verify claims and community/social sources to discover weak signals.
3. Include non-queryable event feeds only when their domain can materially affect the goal.
4. Do not route every request to every source; breadth should be justified by the goal.
5. Search plans are provisional. Never invent facts or claim that a source contains something before querying it.'''

    def _fallback_queries(self, text: str) -> list[SourceQuery]:
        query = ' '.join(text.split())[:240]
        by_category: dict[str, str] = {}
        for name, profile in self.profiles.items():
            by_category.setdefault(profile.category, name)
        selected = list(by_category.values())[:14]
        return [SourceQuery(source=s, query=query, purpose='fallback heterogeneous search', limit=10) for s in selected]

    def _fallback_plan(self, text: str, horizon_hours: int | None) -> QueryPlan:
        terms = [t.lower() for t in re.findall(r'[A-Za-z0-9_+.#-]{3,}|[\u4e00-\u9fff]{2,}', text)]
        keywords: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                seen.add(term)
                keywords.append(term)
            if len(keywords) >= 14:
                break
        return QueryPlan(
            goal=' '.join(text.split())[:500],
            horizon_hours=horizon_hours or 72,
            keywords=keywords,
            desired_signals=['material change', 'credible counterevidence', 'new actionable option', 'meaningful risk'],
            source_queries=self._fallback_queries(text),
            uncertainties=['Model planning unavailable; routing is category-balanced rather than semantically optimized.'],
            stop_conditions=['Enough independent evidence exists to support or reject the current action.'],
        )
