# attention-leverage

[![CI](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/xiongweilin/attention-leverage/actions/workflows/ci.yml)
[![SonarQube Cloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=metratio_attention-leverage&metric=coverage)](https://sonarcloud.io/summary/new_code?id=metratio_attention-leverage)

> Expand machine observation. Shrink human attention load. Preserve the ability to notice that your model of the world is becoming stale.

`attention-leverage` is a goal-driven information and cognitive-calibration system.

```text
input
  ↓
model understanding + current assumptions + long-term coverage history
  ↓
goal / blind-spot / counterevidence / environment / verification queries
  ↓
heterogeneous public information sources
  ↓
deterministic compression
  ↓
semantic qualification
  ↓
attention output + cognitive map
```

The system is deliberately not an infinite feed. Its purpose is to let machines search much more broadly while letting very little reach human attention.

## The four calibration questions

Every run can now answer four separate questions:

1. **What have you probably not seen for a long time?**
   - Based on search/observation coverage, not unsupported psychological inference.
   - The system distinguishes `not searched` from `searched but no result`.

2. **Which environments are farthest from your current information exposure?**
   - An environment is modeled as people + institutions/places + entry points + default rules + paths + timing + connectors/trust + costs/substitutes.
   - The output tries to identify legal/public/low-cost entry points rather than merely describing status symbols.

3. **Which changes could force you to reinterpret the present?**
   - The old frame and new possible frame are stored separately.
   - A new interpretation remains provisional until evidence is sufficient.

4. **Which signals indicate that an existing model is failing?**
   - Users can save explicit falsifiable working assumptions.
   - The semantic layer can attach counter-signals to those assumptions and mark them challenged.
   - No contradiction is manufactured when evidence is weak.

## Query modes

The first model call produces a `QueryPlan` whose routes carry a mode:

- `goal` — directly answer the current objective;
- `blindspot` — probe categories/environments with little observation history;
- `counterevidence` — search for evidence that would falsify a working assumption;
- `environment` — map people, institutions, entry points, rules, paths and timing;
- `verification` — confirm a consequential weak signal with stronger evidence.

This prevents the system from becoming a pure confirmation engine.

## Long-term cognitive state

SQLite persists more than article history:

- item identity and repeat count;
- query history, source category, query purpose and result count;
- source health;
- saved goals;
- useful / irrelevant feedback;
- explicit working assumptions;
- assumption challenge timestamps;
- recurring distant environments;
- run-level cognitive maps.

The coverage ledger makes a critical distinction:

```text
never searched ≠ searched and found nothing ≠ repeatedly observed
```

A failed source or empty query is therefore not silently converted into evidence of absence.

## Source pool

The default pool now includes 25+ built-in public sources spanning different information-generation mechanisms.

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
| People / institutions | OpenAlex Authors, OpenAlex Institutions |
| Structured entities | Wikidata |
| Foundations / associations / nonprofits | ProPublica Nonprofit Explorer |
| Grants / fellowships / opportunity timing | Grants.gov |
| Long-tail official/niche environments | 24 seeded RSS/Atom feeds + configurable additions |
| Hiring / strategic weak signals | 10 seeded public Greenhouse boards + configurable additions |
| Optional corporate disclosure | SEC EDGAR (`SEC_USER_AGENT`) |
| Optional humanitarian reporting | ReliefWeb (`RELIEFWEB_APPNAME`) |

Ten news outlets repeating the same story are not treated as ten distinct information mechanisms.

## Environment model

When the evidence supports it, the semantic layer can produce an `EnvironmentInsight` containing:

- environment name and why it is cognitively distant;
- public/legal entry points;
- hidden/default rules visible in public behavior;
- connector roles rather than only famous people;
- common paths and transitions;
- application/seasonal timing;
- lower-cost substitutes or peripheral entry routes;
- evidence item IDs.

This is intended to answer questions such as:

> Where do people in this environment naturally meet?  
> Who actually connects newcomers?  
> What do insiders assume everyone already knows?  
> Which opportunities appear before they become obvious?  
> Which nominal barriers are real, and which have alternative public routes?

## Deterministic compression

Before the second model call, code handles cheap and inspectable work:

- URL and near-title deduplication;
- freshness windows;
- exclusion terms;
- lexical relevance;
- history novelty;
- source feedback weights;
- authority context;
- category diversity;
- per-source quotas.

The model therefore sees a compressed candidate set instead of the raw firehose.

## Semantic qualification

Each candidate is evaluated on:

- relevance;
- novelty;
- importance;
- actionability;
- confidence;
- **model pressure** — how strongly it strains an existing interpretation;
- **environment distance** — whether it exposes a structurally unfamiliar environment.

The final output remains `attention | watch | background`, but decision-changing counterevidence and newly reachable environments can now rise even when they are not the most familiar topic.

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

The current model client uses an OpenAI-compatible Responses API endpoint:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=http://127.0.0.1:4101/v1
OPENAI_MODEL=...
LLM_TIMEOUT_SECONDS=90
```

Without model configuration, routing, ranking and basic coverage/blind-spot output still work through deterministic fallbacks.

## Dashboard

The web UI has four surfaces:

- **运行** — current digest, cognitive map and attention-ranked items;
- **认知地图** — low-coverage categories, recurring distant environments and explicit assumptions;
- **历史** — previous runs and how many model/environment challenges they produced;
- **信息源** — current source pool and health.

## Working assumptions

The API/UI can save explicit falsifiable assumptions:

```text
POST /api/assumptions
GET  /api/assumptions
DELETE /api/assumptions/{id}
```

When a run returns evidence-bound model challenges, matching assumptions are marked `challenged` with a timestamp rather than automatically declared false.

## CLI and scheduled use

```bash
attention-leverage "哪些公开入口能让我理解某个陌生行业的实际关系结构？"
attention-leverage --saved "agent-infra"
attention-leverage --saved '*' --json > latest.json
```

Text CLI output includes:

- long-unseen areas;
- distant environments;
- reinterpretation triggers;
- model challenges;
- attention-ranked items.

Scheduling remains outside the semantic core: cron, systemd timers, GitHub Actions or another scheduler can call the same pipeline.

## Adding long-tail environments

The repository ships with 24 verified public RSS/Atom feeds across the Federal Reserve, BIS, SEC, FTC, GitHub, Cloudflare, Kubernetes, Rust, Python and NIST. Use `config/sources.toml` to add schools, associations, foundations, conferences, company changelogs, alumni organizations and other public feeds:

```toml
[sources.rss]
enabled = true
feeds = [
  { name = "Official association", url = "https://example.org/feed.xml", authority = "primary" },
  { name = "Niche community", url = "https://community.example/rss", authority = "community" },
]
```

The repository also ships with 10 public Greenhouse boards (Figma, Coinbase, Scale AI, Airtable, Dropbox, Klaviyo, Vercel, xAI, Upstart and Intercom). Add or replace boards in the same config:

```toml
[sources.greenhouse]
enabled = true
boards = [
  { name = "Target company", token = "targetcompany" },
]
```

## Boundaries

- Discovery is not verification.
- Public information is not necessarily effectively visible to a newcomer.
- A social signal and a primary filing are not semantically equivalent.
- An empty search is not proof of absence.
- Cognitive distance is inferred from system search/observation history, not from sensitive personal attributes.
- The system must not infer class, race, politics, health, religion or other sensitive traits from information coverage.
- Feedback only adjusts source weighting mildly; it must not silently create an information bubble.
- A challenged assumption is not automatically false.
- A plausible reinterpretation is not automatically reality.

## Tests

```bash
pytest -q
```

CI compiles the application, runs coverage tests and then runs SonarQube Cloud on pushes to `main`.
