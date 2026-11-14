# Creative Intelligence

A report that turns Meta ad data into creative insight. The user logs in with Meta, picks an ad account and a date range, and gets: how the account performs, which creative choices are behind that performance, and a data-backed creative recipe with a predicted ROAS.

Three tabs: **Creative Overview**, **Insights & Actionables**, **Experimentation Lab**.

Two ways to run it:

| | What it is | Where |
|---|---|---|
| **Live app** | Meta login, real ad data, the two prompts, caching, backend calculations. Hosted on Vercel, worker on GitHub Actions. | `app/index.html` (landing), `app/report.html`, `api/`, `worker/` |
| **Demo** | One self-contained HTML file with a demo account embedded. No server needed. | `app/creative-intelligence.html` |

Open the demo right now: `open app/creative-intelligence.html` (thumbnails sit next to it in `app/`).

## How the live app works

```
Browser ──► Vercel (api/*.js): Meta login, accounts, create report, status, data, thumbnails
                │ reads and writes                  │ starts (workflow_dispatch)
                ▼                                   ▼
          Neon Postgres  ◄──────────────  GitHub Actions worker (Python + Node, no time limit)
          users, sessions, reports,         1. pull ads + insights from Meta              → Signal A
          per-ad cache, cluster/product     2. extraction prompt (reads each creative)
          memory, report payloads,          3. clustering prompt (groups text into angles)
          ad thumbnails                     4. product naming (one clean name per product)
                                            5. assemble datasets                           → Signal B
                                            6. insight pack + insight prompt + checks      → Signal C
                                            7. Experimentation Lab (ridge + CatBoost)      → Signal D
```

- The report page opens as soon as Signal A arrives and fills in as B, C and D arrive. Locked tabs say why on hover.
- Everything is cached per ad. A second report on the same account sends nothing to the LLMs again.
- Calculations (ad records, Story Matrix aggregates, insights, Lab) happen in the worker. The browser renders, and still runs the ranking engine, heatmaps and table sorting from the ad records.
- Costs: Vercel, Neon and GitHub Actions free tiers. No object storage: thumbnails live in Postgres, videos are never stored.

More: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Deploying: [docs/SETUP.md](docs/SETUP.md).

## Run it locally (no Meta app, no API keys)

Mock mode replays the demo account through the real pipeline: real database, real caching, real insight pack builder, real Lab model.

```bash
python3 -m venv .venv && .venv/bin/pip install -r worker/requirements-dev.txt
npm install
.venv/bin/python dev/pg.py &                       # local Postgres, URI is written to .data/pg.uri
export DATABASE_URL="$(cat .data/pg.uri)" ENCRYPTION_KEY="$(openssl rand -base64 32)"
export MOCK_META=1 MOCK_LLM=1 DISPATCH_MODE=local APP_URL=http://localhost:8935
node dev/server.js                                 # http://localhost:8935
```

Tests: `npm test` (API and build checks) and `.venv/bin/python -m pytest worker/tests` (about 4 minutes).

## Repository layout

```
app/
  index.html                  Landing page: Connect Meta, pick account and dates, recent reports
  report.html                 LIVE report page (built; loads its data from the API)
  creative-intelligence.html  DEMO page (built; demo data embedded)
  src/app.template.html       The one source for both pages. Edit this, then run: python3 scripts/build_app.py
  demo/*.json                 The demo account's datasets
  thumbs/ cre-thumbs/ ...     Demo thumbnails (the live app serves thumbnails from the database)
api/                          Vercel functions (auth, me, accounts, report/create|status|boot|list, thumb)
lib/                          Server code: config, Postgres, crypto, sessions, Meta, reports, worker dispatch
db/schema.sql                 Postgres schema (idempotent)
worker/                       Python worker
  run.py                        entry point: python -m worker.run --report <id>
  meta_client.py, sources.py    Meta pulls (insights, creatives, video urls, thumbnails, previous period)
  llm.py                        OpenRouter client (retries, deadline, regenerate on bad JSON)
  extract.py, cluster.py, naming.py   the three LLM steps, each with its cache
  assemble.py                   builds the datasets the UI reads
  insights.py                   pack builder + insight prompt + verification
  lab/                          Experimentation Lab model
  mock.py, fixtures/            offline Meta and LLM stand-ins
prompts/                      Every prompt (extraction, clustering, product naming, insights; older ones in archive/)
insight-engine/               Candidate-pack builder and verifier for the insight prompt (Node)
experimentation-lab/          Research scripts and results behind the Lab model
prd/                          PRD 1 and PRD 2 (.docx) and the scripts that generate them
docs/                         Architecture, setup, methodology, project context
scripts/                      build_app.py (builds both pages), extract_datasets.py (one-time refactor)
.github/workflows/            report.yml (the worker), test.yml (CI)
```

## Prompts

| Prompt | Input | Output |
|---|---|---|
| `extraction_prompt.md` | One ad creative (video, image or carousel) | Fixed fields plus free-text fields (problem, hook, USP, use case, CTA and more). Every ad not already cached. |
| `clustering_prompt.md` | Free-text values of new ads plus the account's saved labels | Angles per field. Labels are reused across runs. |
| `product_naming_prompt.md` | Raw Product values plus existing product names | One clean name and category per product; bundles flagged. |
| `insight_unified_prompt.txt` | Candidate pack from `insight-engine/build_insight_inputs.js` | Up to 4 insight cards. Quotes numbers only from the pack. |

All maths (ROAS, counts, spend, rankings) is done in code, never by a prompt.

## Experimentation Lab

For one product, the Lab scores every supported combination of angles and returns the best recipe with a predicted ROAS.

- **Method:** ads are weighted by spend, angle effects are shrunk toward the product average, and a regularised statistical model is averaged with CatBoost.
- **Testing:** every report is back-tested on held-out ads. On the demo account the blend's error was 0.328 against 0.375 for the product average, and a label-shuffle test confirmed the signal is real. The size of the gain per product could not be confirmed with 251 ads, so the UI says "predicted" and suggests a test against a control.
- **Eligibility:** a product needs enough ads and spend, and angles with 2+ ads in every stage (defaults: 15 ads, 3 lakh spend, set by `LAB_MIN_ADS` and `LAB_MIN_SPEND`).
- The worker module (`worker/lab/model.py`) reproduces the research results exactly; `worker/tests/test_lab.py` checks it against `experimentation-lab/steps_data.json`.

## What is verified and what is not

Verified by tests and by running it: the API, sessions, ownership checks, token encryption, caching, the full pipeline offline (Meta and LLM mocked), dataset assembly, the insight pack builder, the Lab model, and both app builds in a browser (landing, live progressive loading, locks, demo).

Not testable without credentials, so check them on the first real run (details in `docs/SETUP.md`): the Meta login and Marketing API calls, thumbnail sizing, video extraction through Meta's short-lived video URLs, and the OpenRouter model names.

## Product docs

- `prd/PRD_1_Creative_Intelligence_Report.docx`: landing page, staged loading and unlock signals, the tabs, edge cases, metrics. Appendix A holds the insight prompt.
- `prd/PRD_2_Input_Data_Processing.docx`: the data pull, extraction, clustering, product naming, caching, failure handling. Appendices hold the prompts and a sample API record.

## Placeholders

- **Generate Creative** and **Take Action** buttons do nothing yet (out of scope for this version).
- Summary-card trends in the live app compare with the previous period of equal length and only show when no filter narrows the numbers. The demo shows illustrative placeholders.

## Build log

Every commit that changes behaviour adds a line here.

- **API foundation.** Postgres schema, Meta login (mock mode for local dev), encrypted token storage, sessions, report create / status / boot endpoints, owner-only thumbnails, local dev server, API tests, architecture doc.
- **Worker.** Full pipeline for one report: Meta pull with retries and an async fallback, thumbnails in Postgres, extraction (video, carousel, image, thumbnail fallback) with per-ad cache, clustering with cluster memory, product naming, dataset assembly, insight pack + prompt + verification, the Lab as a module that reproduces the validated numbers. Offline mock mode. GitHub Actions workflows. Setup guide.
- **Live front end.** One template builds two pages (demo and live). Landing page with Meta login and recent reports. The report page loads real data, polls signals A to D, locks Insights until B and the Lab until D, shimmers the insight cards until C, shows contextual progress, a failure banner with retry, real previous-period trends, per-account currency, and the Generate Report flow for a new account or range. Live build embeds no demo data (tested).
- **Hosting.** Vercel project connected to this repo (auto-deploys on push), Neon database provisioned through the Vercel integration, schema applied, encryption key shared between Vercel and the GitHub Actions secrets. Fresh databases create their tables on first use. Stale Lab UI files moved to `experimentation-lab/archive/`.
- **Worker start.** The API now starts the worker with `workflow_dispatch` instead of `repository_dispatch`, so the GitHub token only needs the fine-grained permission "Actions: read and write" (the old call needed "Contents: write"). The first live login and account list worked.
