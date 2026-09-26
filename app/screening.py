from __future__ import annotations

import json

from .llm import OpenAICompatibleLLM
from .models import (
    BlindSpot, Candidate, CognitiveMap, Digest, QueryPlan, RankedItem, Screening, SourceProfile,
)


class SemanticScreener:
    def __init__(self, llm: OpenAICompatibleLLM, profiles: dict[str, SourceProfile]):
        self.llm = llm
        self.profiles = profiles

    async def screen(
        self,
        plan: QueryPlan,
        candidates: list[Candidate],
        cognitive_context: dict | None = None,
    ) -> tuple[Digest, CognitiveMap, list[RankedItem], bool]:
        context = cognitive_context or {}
        if not candidates:
            cognitive = self._fallback_cognitive_map(context)
            return (
                Digest(headline='No qualifying items found.', unresolved=plan.uncertainties),
                cognitive,
                [],
                self.llm.available,
            )
        if self.llm.available:
            try:
                compact = [self._compact(x) for x in candidates[:72]]
                payload = {
                    'cognitive_context': context,
                    'candidates': compact,
                }
                data = await self.llm.json(
                    self._system_prompt(plan),
                    json.dumps(payload, ensure_ascii=False),
                )
                digest = Digest.model_validate(data.get('digest', {}))
                cognitive = CognitiveMap.model_validate(data.get('cognitive_map', {}))
                screenings = {
                    s.item_id: s
                    for s in (Screening.model_validate(x) for x in data.get('items', []))
                }
                ranked = [self._merge(c, screenings.get(c.id)) for c in candidates]
                ranked.sort(key=lambda x: x.score, reverse=True)
                return digest, cognitive, ranked, True
            except Exception:
                pass

        underexplored = {
            x.get('category') for x in context.get('underexplored_categories', [])
            if isinstance(x, dict) and x.get('category')
        }
        ranked = [self._fallback(c, underexplored) for c in candidates]
        ranked.sort(key=lambda x: x.score, reverse=True)
        digest = Digest(
            headline=f'{len(ranked)} candidates survived deterministic filtering.',
            what_changed=[x.title for x in ranked[:3]],
            unresolved=plan.uncertainties,
        )
        return digest, self._fallback_cognitive_map(context), ranked, False

    def _system_prompt(self, plan: QueryPlan) -> str:
        return f'''You are the final semantic attention filter and cognitive calibration layer.
Your task is not to summarize everything. It is to decide what deserves scarce human attention and to identify where the current cognitive model may be incomplete or stale.

Goal: {plan.goal}
Desired signals: {plan.desired_signals}
Known uncertainties: {plan.uncertainties}
Working assumptions: {plan.working_assumptions}
Exploration questions: {plan.exploration_questions}
Stop conditions: {plan.stop_conditions}

The input JSON contains long-term cognitive context plus current candidates.
Coverage records distinguish "not searched" from "searched with few/no results". Never turn an empty search into evidence of absence.

Return JSON with exactly:
{{
  "digest": {{
    "headline": "one sentence",
    "what_changed": ["0-6 concise changes"],
    "possible_actions": ["0-5 bounded next actions"],
    "unresolved": ["0-6 uncertainties worth preserving"]
  }},
  "cognitive_map": {{
    "long_unseen": [
      {{
        "area": "...",
        "why_unseen": "...",
        "evidence_gap": "...",
        "suggested_probe": "...",
        "severity": 0..1
      }}
    ],
    "distant_environments": [
      {{
        "name": "...",
        "description": "...",
        "distance": 0..1,
        "why_distant": "...",
        "entry_points": ["public/legal/real entry points"],
        "hidden_rules": ["defaults newcomers may not know"],
        "connectors": ["roles or types of people who connect entrants"],
        "paths": ["common transitions or sequences"],
        "timing": ["application/seasonal/sequence timing"],
        "low_cost_entries": ["lower-cost substitutes or peripheral entries"],
        "evidence_item_ids": ["candidate ids"]
      }}
    ],
    "reinterpretations": [
      {{
        "trigger": "observed change that may require reframing",
        "old_frame": "previous plausible explanation",
        "new_frame": "new plausible explanation",
        "confidence": 0..1,
        "evidence_item_ids": ["candidate ids"]
      }}
    ],
    "model_failures": [
      {{
        "assumption_id": "id from context when applicable, otherwise empty",
        "assumption": "specific working assumption",
        "signal": "observed counter-signal",
        "why_it_matters": "...",
        "severity": 0..1,
        "strength": "weak|watch|strong",
        "evidence_item_ids": ["candidate ids"]
      }}
    ],
    "next_explorations": ["0-8 high-value probes that would reduce cognitive uncertainty"]
  }},
  "items": [
    {{
      "item_id": "...",
      "relevance": 0..1,
      "novelty": 0..1,
      "actionability": 0..1,
      "confidence": 0..1,
      "importance": 0..1,
      "model_pressure": 0..1,
      "environment_distance": 0..1,
      "reason": "one short sentence",
      "signal": "specific new fact/change represented by the item, or empty",
      "disposition": "attention|watch|background"
    }}
  ]
}}

Calibration questions that MUST shape the cognitive_map:
1. What has probably not entered the user's attention for a long time?
2. Which environments are farthest from the user's observed information history?
3. Which current changes could make the user reinterpret the present?
4. Which signals indicate an existing model or assumption may be failing?

Rules:
- Blind spot means insufficient observation/search coverage, not "the world contains nothing there."
- Cognitive distance is about unfamiliar structure: people, organizations/places, entry points, default rules, paths, timing, trust/connectors, costs and substitutes.
- A model failure requires identifiable counterevidence. Do not manufacture contradictions.
- A reinterpretation must preserve the old and new frames separately; do not present a speculative new frame as settled fact.
- Treat source authority as evidence context, not automatic truth.
- Community/social signals are useful for discovery but usually require verification.
- Repeated items should receive lower novelty unless they materially changed.
- "attention" is for decision-changing evidence, meaningful model pressure, a newly reachable environment, or required action.
- Prefer a small number of attention items.
- Do not infer personal background, class, political views, health, or other sensitive traits from browsing history or source coverage.'''

    def _compact(self, item: Candidate) -> dict:
        profile = self.profiles.get(item.source)
        return {
            'item_id': item.id,
            'source': item.source,
            'source_category': item.source_category,
            'authority': item.authority,
            'source_description': profile.description if profile else '',
            'title': item.title,
            'summary': item.summary[:1500],
            'published_at': item.published_at.isoformat() if item.published_at else None,
            'query': item.query,
            'heuristic_score': round(item.heuristic_score, 3),
            'history_novelty': round(item.history_novelty, 3),
            'seen_count': item.seen_count,
            'metadata': item.metadata,
        }

    @staticmethod
    def _merge(item: Candidate, s: Screening | None) -> RankedItem:
        if s is None:
            return SemanticScreener._fallback(item, set())
        score = (
            .22 * s.relevance
            + .15 * s.novelty
            + .16 * s.importance
            + .13 * s.actionability
            + .10 * s.confidence
            + .12 * s.model_pressure
            + .06 * s.environment_distance
            + .06 * min(1.0, item.heuristic_score)
        )
        return RankedItem(
            **item.model_dump(),
            relevance=s.relevance,
            novelty=s.novelty,
            actionability=s.actionability,
            confidence=s.confidence,
            importance=s.importance,
            model_pressure=s.model_pressure,
            environment_distance=s.environment_distance,
            reason=s.reason,
            signal=s.signal,
            disposition=s.disposition,
            score=score,
        )

    @staticmethod
    def _fallback(item: Candidate, underexplored: set[str]) -> RankedItem:
        base = min(1.0, item.heuristic_score)
        distance = .65 if item.source_category and item.source_category in underexplored else 0
        score = min(1.0, base + .05 * distance)
        if score >= .72:
            disposition = 'attention'
        elif score >= .46:
            disposition = 'watch'
        else:
            disposition = 'background'
        matched = ', '.join(item.matched_terms[:5]) or 'recency/diversity/history'
        return RankedItem(
            **item.model_dump(),
            relevance=base,
            novelty=item.history_novelty,
            actionability=0,
            confidence=.35,
            importance=base,
            model_pressure=0,
            environment_distance=distance,
            reason=f'Deterministic fallback matched: {matched}.',
            signal='',
            disposition=disposition,
            score=score,
        )

    @staticmethod
    def _fallback_cognitive_map(context: dict) -> CognitiveMap:
        blindspots = []
        for row in context.get('underexplored_categories', [])[:6]:
            if not isinstance(row, dict) or not row.get('category'):
                continue
            blindspots.append(BlindSpot(
                area=row['category'],
                why_unseen=row.get('reason', 'Limited observation history.'),
                evidence_gap=f"Recorded searches: {row.get('searches', 0)}; observed items: {row.get('items', 0)}.",
                suggested_probe=f"Run a bounded exploratory query in {row['category']} and compare it with familiar categories.",
                severity=.6 if row.get('searches', 0) == 0 else .45,
            ))
        return CognitiveMap(
            long_unseen=blindspots,
            next_explorations=[x.suggested_probe for x in blindspots[:4]],
        )
