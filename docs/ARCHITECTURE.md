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
