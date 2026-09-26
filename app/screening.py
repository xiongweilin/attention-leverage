from __future__ import annotations

import json

from .llm import OpenAICompatibleLLM
from .models import Candidate, QueryPlan, RankedItem, Screening


class SemanticScreener:
    def __init__(self, llm: OpenAICompatibleLLM):
        self.llm = llm

    async def screen(self, plan: QueryPlan, candidates: list[Candidate]) -> tuple[list[RankedItem], bool]:
        if not candidates:
            return [], self.llm.available
        if self.llm.available:
            try:
                screenings: dict[str, Screening] = {}
                for start in range(0, len(candidates), 12):
                    batch = candidates[start : start + 12]
                    data = await self.llm.json(
                        system=self._system_prompt(plan),
                        user=json.dumps([self._compact(x) for x in batch], ensure_ascii=False),
                    )
                    for raw in data.get("items", []):
                        s = Screening.model_validate(raw)
                        screenings[s.item_id] = s
                ranked = [self._merge(c, screenings.get(c.id)) for c in candidates]
                ranked.sort(key=lambda x: x.score, reverse=True)
                return ranked, True
            except Exception:
                pass
        ranked = [self._fallback(c) for c in candidates]
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked, False

    def _system_prompt(self, plan: QueryPlan) -> str:
        return f"""You are the final semantic attention filter for an information aggregation system.
Goal: {plan.goal}
Desired signals: {plan.desired_signals}
Known uncertainties: {plan.uncertainties}

Judge only from the supplied title, summary, source and metadata. Do not add unsupported facts.
Return JSON {{"items": [...]}}. Each item must contain:
- item_id
- relevance, novelty, actionability, confidence: numbers 0..1
- reason: one short sentence explaining why this deserves or does not deserve attention
- signal: the concrete change/evidence, if any
- disposition: attention | watch | background

Reserve "attention" for items likely to change a decision or require action. Prefer a small number of high-value items over broad coverage."""

    @staticmethod
    def _compact(item: Candidate) -> dict:
        return {
            "item_id": item.id,
            "source": item.source,
            "title": item.title,
            "summary": item.summary[:1200],
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "query": item.query,
            "heuristic_score": round(item.heuristic_score, 3),
        }

    @staticmethod
    def _merge(item: Candidate, s: Screening | None) -> RankedItem:
        if s is None:
            return SemanticScreener._fallback(item)
        score = (
            0.34 * s.relevance
            + 0.20 * s.novelty
            + 0.20 * s.actionability
            + 0.16 * s.confidence
            + 0.10 * item.heuristic_score
        )
        return RankedItem(
            **item.model_dump(),
            relevance=s.relevance,
            novelty=s.novelty,
            actionability=s.actionability,
            confidence=s.confidence,
            reason=s.reason,
            signal=s.signal,
            disposition=s.disposition,
            score=score,
        )

    @staticmethod
    def _fallback(item: Candidate) -> RankedItem:
        score = item.heuristic_score
        if score >= 0.72:
            disposition = "attention"
        elif score >= 0.42:
            disposition = "watch"
        else:
            disposition = "background"
        matched = ", ".join(item.matched_terms[:5]) or "recency/source diversity"
        return RankedItem(
            **item.model_dump(),
            relevance=score,
            novelty=0.0,
            actionability=0.0,
            confidence=0.35,
            reason=f"Deterministic fallback matched: {matched}.",
            signal="",
            disposition=disposition,
            score=score,
        )
