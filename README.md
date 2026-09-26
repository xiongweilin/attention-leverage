# attention-leverage

> Expand machine observation. Shrink human attention load.

A small goal-driven information aggregation system built around this pipeline:

```text
input
  ↓
model understanding
  ↓
goal-driven queries across heterogeneous sources
  ↓
deterministic program filtering
  ↓
model semantic screening
  ↓
small decision-oriented output
```

The system is intentionally not an infinite feed. Its job is to search broadly while allowing very little to reach human attention.

## Current MVP

The first version supports:

- natural-language input as the current information goal;
- model-generated `QueryPlan` with time horizon, keywords, desired signals, uncertainties and source-specific searches;
- heterogeneous query sources: Google News RSS, GDELT, Hacker News, GitHub, OpenAlex, arXiv, Crossref, Stack Exchange and configurable RSS/Atom feeds;
- deterministic filtering before semantic model use: freshness, URL normalization, near-duplicate titles, exclusions, lexical relevance, recency and per-source quotas;
- model screening after compression: relevance, novelty, actionability, confidence, a short reason and `attention | watch | background` disposition;
- a minimal dashboard that displays the result as a decision surface rather than an inbox;
- deterministic fallback planning/ranking when no model is configured.

## Why the two model calls are separated

The first model call expands the search space. It translates today's goal into source-specific queries and discriminating signals.

The program layer then cheaply removes obvious redundancy and noise.

The second model call operates only on the reduced candidate set. It answers a different question: which of these items deserves scarce human attention now?

```text
LLM #1: what should the machine look for?
program: what can be removed cheaply and deterministically?
LLM #2: what is worth human attention?
```

## Run

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

An LLM is optional. For model planning and semantic screening, configure an OpenAI-compatible endpoint in `.env`:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=...
```

A GitHub token is optional but recommended for higher API rate limits.

## Source pool

`config/sources.toml` controls which source adapters are active. Generic RSS/Atom feeds can be added there for official sources, niche communities, company changelogs, regulators, journals or other trusted feeds.

A source adapter has one responsibility: turn one goal-specific query into normalized `RawItem` records. New source types should not leak source-specific semantics into the rest of the pipeline.

## Design principles

1. **Broad machine search, narrow human output.** More sources must not mean more reading.
2. **Goal-driven rather than subscription-driven.** Today's input can produce a different search plan from yesterday's.
3. **Heterogeneous evidence.** Mainstream news, practitioner communities, code, research literature and trusted niche feeds should not be collapsed into one source type.
4. **Deterministic compression before model judgment.** Do cheap, inspectable work with code before spending model attention.
5. **Separate discovery from qualification.** Finding an item does not mean it deserves attention.
6. **Preserve uncertainty.** Missing evidence and source failures remain visible; they are not silently converted into negative conclusions.
7. **No infinite feed.** The interface should make the important few obvious and let the rest disappear.

## Projects worth borrowing ideas from

The MVP does not copy their code; it borrows architectural/product ideas from several mature open-source projects:

- [RSSHub](https://github.com/DIYgod/RSSHub): normalize a large variety of upstream sources into machine-consumable feeds.
- [changedetection.io](https://github.com/dgtlmoon/changedetection.io): focus on meaningful change/delta rather than repeatedly presenting whole pages.
- [Huginn](https://github.com/huginn/huginn): event-driven agents and composable information workflows.
- [Folo](https://github.com/RSSNext/Folo): modern feed aggregation and AI-assisted reading UX.
- [Glance](https://github.com/glanceapp/glance): a compact dashboard rather than an attention-maximizing feed.

## Current boundaries

This is an initial prototype, not yet a continuously running personal attention system. It does not yet include:

- persistent history and cross-run novelty detection;
- scheduled/background collection;
- embeddings or learned personal ranking;
- source health/reliability models;
- notification thresholds;
- page-change extraction comparable to changedetection.io;
- source-specific authority/provenance qualification;
- authentication or multi-user isolation.

Those should be added only after the query/filter/screen/output loop proves useful.

## Tests

```bash
pip install -e '.[dev]'
pytest -q
```
