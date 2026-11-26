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
- **Worker config fix.** Optional settings that GitHub Actions passes as empty strings (for example `EXTRACT_CONCURRENCY`) now count as unset, which stops the worker crashing at start.
- **Top bar.** The signed-in name and Log out now sit in one quiet pill (initial, name, divider, Log out) next to the theme toggle instead of loose red text.
- **Stage data and top-bar fixes (first live run).** Only 12 of 58 ads were read properly: for video ads Meta returned no file link, so the model saw one thumbnail with no end card and found no CTA; and the clustering model skipped whole fields (CTA, proof points). Now: video links are fetched one video at a time and the Meta error is logged; when no file is available the model gets up to 4 frames from the video (including the end card); thumbnail-only ads get one retry; clustering asks again for any skipped field and fills in only the missing labels without touching existing ones. In the report, stage pills with no data in the selected range are hidden, and the loading pill sits centred between the title and the account and date controls.
- **Video access and proof points.** The log of the first live run showed Meta rejecting video file and frame requests (error 283) for a token with only `ads_read`. Login now also asks for `pages_read_engagement` and `pages_show_list` (existing users reconnect once). Proof point labels were being dropped because their ids are `ad_id::point`; they now map back to the ad. Clustering logs what each field returned.
- **Header layout.** The loading pill now lives in the same row as the account and date selectors (fixed width, text truncates, so changing progress text can no longer push the selectors onto a second line). The filter-chip row under the filter bar is removed.
- **Long runs and video access.** The 571-ad run was cut off by the 90 minute job limit (extraction about 60 min at 6 in parallel, clustering about 30 min). Now: 16 creatives are read in parallel, the job limit is 240 minutes, and clustering only retries a field when most of it was skipped (the old retry doubled clustering time for little gain). Meta refused video files for videos owned by Pages the login does not manage (errors 10 and 283), so the worker now also looks them up in the ad account's own video library, which needs only `ads_read`, before falling back to frames and then one thumbnail.
- **Ad copy as evidence.** The ad account's video library did not contain the ads' videos (they belong to Pages the login does not manage; Meta needs Page Public Content Access, an app review, for those). The worker now also pulls each creative's primary text, headline, description and CTA button from Ads Manager (needs only `ads_read`) and gives them to the extraction model as supporting evidence, which is how call to action and angle text are filled for videos that cannot be watched.
- **2-month window for insights and the Lab, several API keys.** Insights and the Experimentation Lab now always run on the last 60 days up to today (`WINDOW_DAYS`), whatever range the report shows, so a short report still gets full insights. After the selected range is classified (signal B), the worker pulls the 60-day window, reads only the ads it has not read before (the per-ad cache), and builds insights and the Lab from it; the report page says "Processing 2 months of data" and the insight cards keep shimmering, with rotating status lines, until they are ready. Same-day repeats for an account copy the finished insights and Lab instead of recomputing. Several OpenRouter keys can be set (`OPENROUTER_API_KEYS`, comma separated): calls rotate across them, a rate-limited key rests and a rejected key is dropped. Extraction runs 12 reads per key in parallel, and clustering runs batches side by side after the first one has seeded the label vocabulary.
- **UI audit.** Skeleton shimmer is now visible in light mode (own tokens), light-mode small text raised to readable contrast, user avatar and badge contrast, header controls and stat cards wrap on phones with no sideways scroll, and the insight loader shows contextual status copy.
- **Faster Meta pull.** A 3-month Shesha report (1,830 ads) spent about 12 minutes on the pull alone: creative details were read 50 ads at a time one after another, 1,259 thumbnails were saved at about 2.6 per second before the page could open, and the previous-period totals ran after the ads. Now: creative details load 6 batches at once and are skipped for ads read in the last 24 hours (so the 60-day window pull reuses the range's ads), previous-period totals load alongside the ads, Meta pages are 500 ads, writes to the database are batched, and thumbnails download (24 at a time) in the background after signal A instead of before it, so the page opens as soon as the numbers are in.
- **Meta API budget.** To protect the app's rate limit: previous-period totals are one account-level call (the Total Ads trend is dropped, spend, revenue and ROAS trends stay); insight rows for an account and date range are cached for 6 hours, so repeat reports and the 60-day window cost no Meta calls; creative details are re-read only after 7 days; when Meta refuses video access the worker probes three videos and stops instead of making one failing call per video (a 1,800-ad account was making over a thousand of those); creative details load 3 batches at a time; the worker reads Meta's usage headers and slows down at 75% and pauses at 90% of the budget or when Meta says when access returns; each run logs how many Meta requests it made.
- **Cancel, and a Meta call budget built into the design.** A **Cancel** button sits in the loading pill of the report page: it marks the report cancelled, cancels the GitHub Actions job (found through the run name `report <id>`), and the worker also stops at its next progress update (queued reads are dropped), so nothing keeps spending Meta calls or model credits; a stopped report shows "Report stopped" with **Generate again**, and what was already pulled stays cached. For Meta: (1) only one report talks to Meta at a time (a Postgres advisory lock, `MetaGate`); others wait and the page says "Waiting for another report to finish pulling from Meta", because Meta's call budget belongs to the whole app; (2) the worker reads Meta's usage headers and slows down at 75% and pauses at 90%; (3) insight rows are cached per account and date range for 6 hours, creative details for 7 days; (4) creative details ask only for the sub-fields the app reads; (5) video access is probed with three calls and abandoned if refused; (6) previous-period totals are one account-level call; (7) every run logs how many Meta requests it made.
- **Empty Meta answers.** A report that finds no ads with spend now says why (account not readable by the login, account not active, no spend in that range but spend before so try an earlier range, spend at account level only, no ads yet) from three small diagnostic calls, and the empty answer is never cached, so a retry asks Meta again. A failure that is reported to the user (no ads, expired login) no longer makes the GitHub job fail, so it does not send a failure email; unexpected crashes still do.
- **Database hang-ups on long runs.** A 3-month Shesha report (1,772 ads) died after 2 hours with `SSL connection has been closed unexpectedly`: model calls between database writes left the connection idle for minutes and Neon closed it, and the worker could not recover (its own failure handler used the same dead connection, so the report stayed on "running"). The worker's database connection now sends TCP keepalives and reconnects and repeats the statement when the line drops (all worker statements are upserts or updates, so repeating is safe). The Meta gate keeps a plain connection because its lock belongs to the session. Covered by a test that kills the connection mid-run.
- **Same account, same range: instant for the next person.** When someone asks for a report that another user already finished for the same ad account and exact date range within the last 6 hours (`REPORT_REUSE_HOURS`), the app copies that finished report (row, every payload, per-ad metrics) for them with a database copy and starts no worker: the report opens complete in about a second. Access is still checked against the new user's own Meta login first, and the copy belongs to them alone. **Try again** and **Generate again** bypass it and build a fresh report.
- **No repeated model work.** The costliest steps (reading each creative, clustering, product naming) are done once per creative, for the whole ad account, whoever asks. Closed two leaks: thumbnail-only reads were being re-read once on the next report (rule removed: any finished read is final), and an ad the model skipped an angle for was re-sent to clustering on every report (now at most twice per ad, `cluster_attempts`). New: ads that run the same Meta creative (copies in other ad sets) are worked out once; the models see one ad per `creative_id` and the reading, angle labels and product are copied to the others with one SQL statement (`cache.share_results`). On the Shesha account 2,012 ads share 1,478 creatives, so about a quarter of the ads need no model call at all. Date ranges that overlap an earlier report only pay for ads never seen before; Meta spend and ROAS for the new range are fetched again because they are cheap.
