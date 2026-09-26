from __future__ import annotations

import json

from .llm import OpenAICompatibleLLM
from .models import Candidate, Digest, QueryPlan, RankedItem, Screening, SourceProfile


class SemanticScreener:
    def __init__(self, llm: OpenAICompatibleLLM, profiles: dict[str, SourceProfile]):
        self.llm = llm
        self.profiles = profiles

    async def screen(self, plan: QueryPlan, candidates: list[Candidate]) -> tuple[Digest, list[RankedItem], bool]:
        if not candidates:
            return Digest(headline='No qualifying items found.', unresolved=plan.uncertainties), [], self.llm.available
        if self.llm.available:
            try:
                compact = [self._compact(x) for x in candidates[:72]]
                data = await self.llm.json(self._system_prompt(plan), json.dumps(compact, ensure_ascii=False))
                digest = Digest.model_validate(data.get('digest', {}))
                screenings = {s.item_id: s for s in (Screening.model_validate(x) for x in data.get('items', []))}
                ranked = [self._merge(c, screenings.get(c.id)) for c in candidates]
                ranked.sort(key=lambda x: x.score, reverse=True)
                return digest, ranked, True
            except Exception:
                pass
        ranked = [self._fallback(c) for c in candidates]
        ranked.sort(key=lambda x: x.score, reverse=True)
        digest = Digest(
            headline=f'{len(ranked)} candidates survived deterministic filtering.',
            what_changed=[x.title for x in ranked[:3]],
            unresolved=plan.uncertainties,
        )
        return digest, ranked, False

    def _system_prompt(self, plan: QueryPlan) -> str:
        return f'''You are the final semantic attention filter. Your task is not to summarize everything; it is to decide what deserves scarce human attention now.

Goal: {plan.goal}
Desired signals: {plan.desired_signals}
Known uncertainties: {plan.uncertainties}
Stop conditions: {plan.stop_conditions}

Each candidate contains source category, authority class, history novelty, and a deterministic score. Treat source authority as evidence context, not automatic truth. Community/social signals may be valuable for discovery but usually need verification. Repeated items should receive lower novelty unless they materially changed.

Return JSON with exactly:
{{
  "digest": {{
    "headline": "one sentence",
    "what_changed": ["0-6 concise changes"],
    "possible_actions": ["0-5 bounded next actions"],
    "unresolved": ["0-6 uncertainties worth preserving"]
  }},
  "items": [
    {{
      "item_id": "...",
      "relevance": 0..1,
      "novelty": 0..1,
      "actionability": 0..1,
      "confidence": 0..1,
      "importance": 0..1,
      "reason": "one short sentence",
      "signal": "specific new fact/change represented by the item, or empty",
      "disposition": "attention|watch|background"
    }}
  ]
}}

Rules:
- attention: likely to change a decision, create a new option, invalidate an assumption, or require action.
- watch: meaningful but not yet decision-changing, or needs independent confirmation.
- background: useful context but not worth interrupting the user.
- Prefer a small number of attention items.
- Do not infer facts absent from the candidates. Do not turn uncertainty into a negative conclusion.'''

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
            return SemanticScreener._fallback(item)
        score = (
            .27 * s.relevance + .18 * s.novelty + .18 * s.importance + .16 * s.actionability +
            .11 * s.confidence + .10 * min(1.0, item.heuristic_score)
        )
        return RankedItem(
            **item.model_dump(), relevance=s.relevance, novelty=s.novelty,
            actionability=s.actionability, confidence=s.confidence, importance=s.importance,
            reason=s.reason, signal=s.signal, disposition=s.disposition, score=score,
        )

    @staticmethod
    def _fallback(item: Candidate) -> RankedItem:
        score = min(1.0, item.heuristic_score)
        if score >= .72:
            disposition = 'attention'
        elif score >= .46:
            disposition = 'watch'
        else:
            disposition = 'background'
        matched = ', '.join(item.matched_terms[:5]) or 'recency/diversity/history'
        return RankedItem(
            **item.model_dump(), relevance=score, novelty=item.history_novelty,
            actionability=0, confidence=.35, importance=score,
            reason=f'Deterministic fallback matched: {matched}.', signal='',
            disposition=disposition, score=score,
        )
