# attention-leverage

[![CI](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml)
[![SonarQube Cloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=coverage)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage)

> Expand machine observation. Shrink human attention load.

`attention-leverage` is a goal-driven information system built around a strict pipeline:

```text
input
  ↓
model understanding
  ↓
goal-driven querying across heterogeneous sources
  ↓
deterministic program filtering
  ↓
model semantic screening
  ↓
small decision-oriented output
```

The product objective is not “read more with AI.” It is the opposite: let machines search much more widely while allowing very little to reach human attention.

## What the current version adds

This version turns the original prototype into a persistent personal attention layer:

- dynamic model-generated `QueryPlan` instead of a fixed subscription list;
- 20 built-in sources enabled without paid credentials, spanning fundamentally different information-generation mechanisms;
- optional SEC, ReliefWeb and configured Greenhouse job boards;
- configurable RSS/Atom long-tail feeds;
- deterministic deduplication, freshness filtering, exclusion rules, lexical relevance, category diversity and per-source quotas;
- persistent SQLite history so repeated information gets lower novelty on later runs;
- model screening that explicitly separates relevance, novelty, importance, actionability and confidence;
- source authority classes (`primary`, `institutional`, `community`, `aggregator`) carried into the final judgment;
- source-health tracking and graceful partial failure;
- user feedback that gradually adjusts source weights;
- saved goals and a CLI suitable for cron/systemd/GitHub Actions scheduling;
- run history and a dashboard for current results, previous runs and source health.

## Source pool

The default pool covers these mechanisms:

| Domain | Sources |
| --- | --- |
| Broad news / global events | Google News RSS, GDELT |
| Social / practitioner weak signals | Bluesky, Hacker News, Stack Overflow |
| Open-source / package ecosystems | GitHub, npm, crates.io |
| General research | OpenAlex, arXiv, Crossref |
| Biomedical / health | Europe PMC, ClinicalTrials.gov |
| Regulation / public institutions | Federal Register, World Bank |
| Cybersecurity | CISA KEV, NIST NVD |
| Natural hazards | USGS earthquakes, NASA EONET |
| Long-tail / trusted sources | configurable RSS/Atom |
| Optional corporate disclosure | SEC EDGAR (`SEC_USER_AGENT`) |
| Optional humanitarian reporting | ReliefWeb (`RELIEFWEB_APPNAME`) |
| Optional hiring signals | configured Greenhouse public job boards |

This is deliberately heterogeneous. Ten versions of the same news story do not count as ten independent sources.

## Architecture

### 1. Input → model understanding

The first model call does not answer the user. It creates a search plan:

- operational goal;
- time horizon;
- high-signal terms and exclusions;
- the kinds of evidence that would change the decision;
- source-specific queries;
- unknowns that need discrimination;
- stopping conditions.

It is the *search-space expansion* step.

### 2. Goal-driven source routing

Each source advertises metadata such as category, authority class and signal type. The planner can therefore combine, for example:

- a social weak-signal source to discover a new issue;
- a regulatory or registry source to verify whether the issue is real;
- a research source to test whether the mechanism is credible.

The fallback planner remains usable without a model and chooses one source per category instead of blindly querying everything.

### 3. Deterministic compression

Before model judgment, code handles work that should be cheap and inspectable:

- canonical URL deduplication;
- near-duplicate title removal;
- freshness windows;
- explicit exclusion terms;
- lexical relevance;
- history novelty;
- source feedback weighting;
- authority weighting;
- category diversity;
- per-source quotas.

### 4. Semantic qualification

The second model call sees only the compressed candidate set and decides:

- relevance;
- novelty;
- importance;
- actionability;
- confidence;
- `attention | watch | background`.

It also returns a compact digest: what changed, possible bounded actions and unresolved uncertainty.

### 5. Persistence and learning

SQLite stores:

- runs and their output;
- observed item identities and seen counts;
- source health;
- saved goals;
- useful / irrelevant feedback.

History changes the meaning of novelty: an item that repeatedly reappears is not treated as “new” simply because it was fetched again.

## Run

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

The local configuration uses `gpt-6-luna` through the Responses endpoint exposed by
`llm-gateway`'s Agent listener. The listener address is defined by
`llm-gateway/config/gateway.json`; update `OPENAI_BASE_URL` in `.env` if that
checkout uses a different host or port:

```bash
OPENAI_API_KEY=local-gateway
OPENAI_BASE_URL=http://127.0.0.1:4101/v1
OPENAI_MODEL=gpt-6-luna
LLM_TIMEOUT_SECONDS=90
```

The client uses `/responses` and reads streamed text output. Without model
configuration, source routing and ranking use deterministic fallbacks.

## CLI and scheduled use

Run one ad-hoc goal:

```bash
attention-leverage "过去 48 小时有哪些变化可能改变我对 AI agent 基础设施的判断？"
```

Run a saved goal:

```bash
attention-leverage --saved "agent-infra"
```

Run every enabled saved goal, suitable for cron:

```bash
attention-leverage --saved '*' --json > latest.json
```

Scheduling is intentionally outside the semantic core: cron, systemd timers, GitHub Actions or another scheduler can invoke the same deterministic pipeline.

## Adding long-tail sources

`config/sources.toml` can add RSS/Atom feeds with an authority hint:

```toml
[sources.rss]
enabled = true
feeds = [
  { name = "Official agency", url = "https://example.gov/feed.xml", authority = "primary" },
  { name = "Niche community", url = "https://example.org/rss", authority = "community" },
]
```

Greenhouse boards can be added similarly:

```toml
[sources.greenhouse]
enabled = true
boards = [
  { name = "Target company", token = "targetcompany" },
]
```

## Important boundaries

- Discovery is not verification. A social post and an official filing are not semantically equivalent.
- Provider success is not evidence that reality changed.
- More sources do not justify more human reading.
- Missing or failed sources remain explicit uncertainty; they do not become evidence of absence.
- Feedback changes source weighting only mildly. It must not silently create an information bubble.

## Tests

```bash
pytest -q
```

CI also compiles the application before running tests.
