from __future__ import annotations

import json
import re

from .llm import OpenAICompatibleLLM
from .models import QueryPlan, SourceProfile, SourceQuery


class GoalPlanner:
    def __init__(self, llm: OpenAICompatibleLLM, profiles: dict[str, SourceProfile]):
        self.llm = llm
        self.profiles = profiles

    async def plan(
        self,
        user_input: str,
        horizon_hours: int | None = None,
        cognitive_context: dict | None = None,
    ) -> tuple[QueryPlan, bool]:
        context = cognitive_context or {}
        if self.llm.available:
            try:
                data = await self.llm.json(self._system_prompt(context), user_input)
                plan = QueryPlan.model_validate(data)
                plan.source_queries = [q for q in plan.source_queries if q.source in self.profiles]
                if horizon_hours is not None:
                    plan.horizon_hours = horizon_hours
                if not plan.source_queries:
                    plan.source_queries = self._fallback_queries(user_input, context)
                return plan, True
            except Exception:
                pass
        return self._fallback_plan(user_input, horizon_hours, context), False

    def _system_prompt(self, cognitive_context: dict) -> str:
        source_lines = []
        for p in self.profiles.values():
            source_lines.append(
                f'- {p.name} | category={p.category} | authority={p.authority} | '
                f'signal={p.signal_kind} | queryable={p.queryable}: {p.description}'
            )
        sources = '\n'.join(source_lines)
        context = json.dumps(cognitive_context, ensure_ascii=False)[:12000]
        return f'''You translate a person's current information need into a bounded, heterogeneous search plan.
The objective is not merely to answer the stated question. It is to increase the probability that important differences enter the person's cognitive system while minimizing human attention cost.

Available sources:
{sources}

Long-term cognitive context:
{context}

The plan must actively consider four calibration questions:
1. What has this person/system probably not seen for a long time?
2. Which environments are most distant from the person's current information exposure?
3. Which changes could force a reinterpretation of the current situation?
4. Which signals would indicate that an existing working model or assumption is failing?

Return one JSON object with exactly these fields:
- goal: concise operational goal
- horizon_hours: integer; default 72 unless the request implies another horizon
- keywords: 5-18 high-signal terms and useful synonyms, multilingual when useful
- exclude_keywords: obvious noise terms
- desired_signals: 3-12 concrete changes/evidence that would alter a decision
- source_queries: array of {{source, query, purpose, mode, limit}}
  - mode is one of goal | blindspot | counterevidence | environment | verification
  - use only available source names
  - prefer heterogeneous information-generation mechanisms
  - reserve some search budget for blind spots/counterevidence when long-term context justifies it
  - at most 2 queries per source
- uncertainties: important unknowns search should discriminate
- stop_conditions: conditions under which enough information has been found for the current purpose
- working_assumptions: 0-8 assumptions implicit in the request or supplied cognitive context that could be falsified
- exploration_questions: 0-8 questions aimed at unseen environments, missing candidates, or counterevidence

Routing rules:
1. Do not equate public availability with effective visibility. Search for entry points, eligibility, timing, connectors and low-cost access when the goal involves an unfamiliar environment.
2. Differentiate discovery from verification: community/social sources can expose weak signals; primary/institutional sources should verify consequential claims.
3. Search for candidate-space expansion, not only confirmation of already named options.
4. Use underexplored source categories when they can plausibly contain decision-changing information.
5. A failed or empty search is not evidence that the thing does not exist.
6. When examining an environment, seek: people, organizations/places, entry points, default rules, paths, timing, trust/connector structure, costs and substitutes.
7. Search plans are provisional. Never invent facts or claim that a source contains something before querying it.'''

    def _fallback_queries(self, text: str, cognitive_context: dict | None = None) -> list[SourceQuery]:
        query = ' '.join(text.split())[:240]
        by_category: dict[str, str] = {}
        for name, profile in self.profiles.items():
            by_category.setdefault(profile.category, name)

        underexplored = [
            x.get('category') for x in (cognitive_context or {}).get('underexplored_categories', [])
            if isinstance(x, dict) and x.get('category')
        ]
        ordered_categories = []
        for category in underexplored + list(by_category):
            if category in by_category and category not in ordered_categories:
                ordered_categories.append(category)

        selected = ordered_categories[:14]
        queries = []
        under_set = set(underexplored)
        for category in selected:
            source = by_category[category]
            queries.append(SourceQuery(
                source=source,
                query=query,
                purpose='Probe an underexplored information environment.' if category in under_set else 'Fallback heterogeneous search.',
                mode='blindspot' if category in under_set else 'goal',
                limit=10,
            ))
        return queries

    def _fallback_plan(self, text: str, horizon_hours: int | None, cognitive_context: dict | None = None) -> QueryPlan:
        terms = [t.lower() for t in re.findall(r'[A-Za-z0-9_+.#-]{3,}|[\u4e00-\u9fff]{2,}', text)]
        keywords: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if term not in seen:
                seen.add(term)
                keywords.append(term)
            if len(keywords) >= 14:
                break
        under = (cognitive_context or {}).get('underexplored_categories', [])
        exploration = [
            f"What material signals might exist in the underexplored {x.get('category')} environment?"
            for x in under[:4] if isinstance(x, dict) and x.get('category')
        ]
        return QueryPlan(
            goal=' '.join(text.split())[:500],
            horizon_hours=horizon_hours or 72,
            keywords=keywords,
            desired_signals=[
                'material change', 'credible counterevidence', 'new actionable option',
                'meaningful risk', 'evidence that a working assumption is stale',
            ],
            source_queries=self._fallback_queries(text, cognitive_context),
            uncertainties=['Model planning unavailable; routing is category-balanced rather than semantically optimized.'],
            stop_conditions=['Enough independent evidence exists to support, reject, or reframe the current action.'],
            exploration_questions=exploration,
        )
