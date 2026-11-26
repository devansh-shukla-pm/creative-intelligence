# Architecture

Goal: a standalone Creative Intelligence app that logs in with Meta, pulls ad data, classifies it with the two prompts, and fills every view. Built for the lowest cost: everything runs on free tiers.

```
Browser (static app)
   |  login, accounts, create report, poll status, load data
   v
Vercel  --  api/*.js (thin Node functions: auth, accounts, report create/status/boot, thumbnails)
   |                                  \
   | reads/writes                      \ dispatches (workflow_dispatch)
   v                                    v
Neon Postgres  <------------------  GitHub Actions "worker" (Python + Node, no time limits)
 users, sessions, reports,             1. pull ads + insights from Meta
 ad_cache, account_memory,             2. extraction prompt  (multimodal LLM, cached per ad)
 report payloads, thumbnails           3. clustering prompt  (text LLM, cluster memory)
                                       4. product naming     (one clean name per product)
                                       5. assemble payloads  -> Signal A, then B
                                       6. insights (node pack builder + insight prompt) -> Signal C
                                       7. Experimentation Lab (CatBoost + ridge)       -> Signal D
```

## Why this shape

| Decision | Reason |
|---|---|
| Heavy work in a GitHub Actions job, not in Vercel functions | Vercel functions have short time limits. The job has none, runs Python and Node, and is free for private repos (2000 min/month). |
| Postgres only, no object storage | Thumbnails are small JPEGs stored in Postgres and served by `/api/thumb`. Videos are never stored: the extraction model reads Meta's short-lived video URL during the job, and "View" links open Meta's own ad preview link. Nothing to pay for and nothing to expire. |
| Meta token only on the server | The browser never sees it. It is stored AES-256-GCM encrypted. |
| Per-ad cache keyed by `(account_id, ad_id)` | A new report on the same account only processes new ads. Cluster memory and product names keep labels stable across runs. |
| Calculations in the backend | Ad records, dimension aggregates, insight pack and Lab are computed by the worker. The browser only renders. The ranking engine, heatmaps and table sorting still run in the browser from the ad records. |
| Same dataset shapes as the prototype | The UI reads six datasets (ads, explorer rows, dimension aggregates, ranking rows, insights, Lab). The worker produces exactly those. |

## Signals

| Signal | Set when | Unlocks |
|---|---|---|
| A | Meta data pulled and stored | filters, Performance Summary, Format Split, Spend Efficiency, Metric Explorer |
| B | Extraction, clustering and product naming finished | SKU filter, stage charts, Story Matrix, Insights tab |
| C | Insight pack built and insight prompt finished | the 4 insight cards |
| D | Lab computed | Experimentation Lab tab |

The worker sets each signal as soon as its piece is ready, then the browser (polling every few seconds) loads only the payloads it does not have yet.

## The app pages

`app/src/app.template.html` is the single source of the UI. `scripts/build_app.py` builds two pages from it:

- `app/report.html` (live): no data inside. A blocking script loads `/api/report/boot?id=...` (the user's own report, checked by session), then the page polls the same endpoint every 3 seconds until all four signals are in. Only the pieces the browser does not have yet are sent.
- `app/creative-intelligence.html` (demo): the demo account's datasets are embedded. It simulates the same four signals with timers. Used for the Claude artifact and for viewing without a server.

`app/index.html` is the landing page: Connect Meta, choose an ad account and a date range, Generate Creative Intel, and a list of recent reports.

The hosted site never contains demo data (`.vercelignore` plus a test).

## Reports and caching

- A report is `(user, ad account, date range)`. Asking again for the same range within 6 hours returns the existing report.
- Extraction results, cluster labels and product names are cached per ad and survive across reports and date ranges.
- A failed report can be re-run. It continues from the caches, so already processed ads cost nothing.

## Security

- Meta OAuth with a signed, expiring `state` and an HttpOnly session cookie (`SameSite=Lax`, `Secure` in production).
- Reports are only readable by the user that created them.
- Optional allowlist of Meta user ids (`ALLOWED_META_USER_IDS`). In Meta's Development mode only app roles can log in anyway.
- Per-user limits on report creation protect LLM spend.
- Secrets live in Vercel and GitHub environment variables, never in the repo.

## Insights and Lab window
The report page shows the range the user picked, but insights and the Lab always use the last `WINDOW_DAYS` (60) up to today. After signal B the worker calls `stage_window`: it pulls that window from Meta (aggregates are cheap), reads only ads not yet in `ad_cache`, groups and names them, then builds insights (signal C) and the Lab (signal D) from that dataset. `reports.window_from/window_to` tell the page which dates they cover. If the same user already finished the same account and window today, the finished payloads are copied (`cache.reuse_window_results`).

## API keys
`OPENROUTER_API_KEYS` (comma separated) plus `OPENROUTER_API_KEY`. `worker/llm.py` rotates keys per call, rests a key for 20 s on HTTP 429 and drops a key that returns 401, 402 or 403 while others remain.

## Meta call budget
Meta rate limits belong to the app (all users together) and to each ad account, so the worker treats Meta as a scarce shared resource:
- `db.MetaGate`: a Postgres advisory lock held only while calls are made. One report talks to Meta at a time; others wait and show it on the page.
- `meta_client._watch_usage`: reads `x-app-usage` and `x-business-use-case-usage`; sleeps at 75%, 30 s at 90%, or as long as Meta says when access returns.
- Caches: `insights_cache` (account + range, 6 h), `ad_cache.creative` (7 days), thumbnails and video access outcome (no repeat failing calls).
- Typical call count for a 1,800-ad, 3-month account: about 4 insight pages, 37 creative-detail batches the first time (none after), 1 previous-period call, about 4 video probes, plus the 60-day window (about 3 pages). Each run prints `[meta] requests made by this run: N`.

## Cancelling
`POST /api/report/cancel` sets the report to `cancelled`, then cancels the Actions run. `Report.progress()` raises `ReportCancelled` when the row is cancelled, so every long step stops at its next update; `finish()` and `fail()` never overwrite `cancelled`.

## Reuse across users
`createReport` order: (1) same user, same account and range within 6 h: open that report; (2) any other user's finished report for the same account and exact range within 6 h: `copyReport` clones it (no worker); (3) otherwise create a report and dispatch the worker. The worker then reuses ad-level caches (`ad_cache`, `thumbs`, `account_memory`, `insights_cache`) that are keyed by ad account, so even a new range for a known account only pays for new ads.

## What is never repeated
`ad_cache` is keyed by ad account and ad id, shared by all users. Per ad it stores the creative details, the extraction, angle labels and product; `extraction_status` ok, fallback, skipped or failed is final. `cache.share_results` copies finished work between ads with the same `creative_id`, and `_classify` sends only one ad per creative to the models. Clustering re-sends an ad only when it has never been clustered, or at most twice if the model skipped a field. Only Meta spend and ROAS (cheap, range-specific) are fetched for every new range.

## Meta numbers: blocks
`blocks.py`: `plan` (stored blocks fully inside the range, best disjoint set by days covered, gaps, fallback to one plain pull when fragmented, recent days split into their own block), `ensure` (pull each gap with `mc.pull_insights`, store a block), `aggregate` (sum blocks per ad, shaped like a Meta insight row so `metrics_from_insight` is unchanged), `stored_totals` (trend arrows without a Meta call). `MetaSource.fetch_metrics` then `attach_creatives`: numbers first, creative details second.
