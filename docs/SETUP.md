# Setup

Everything below uses free tiers. You do these once.

## 1. Neon Postgres (database)

1. Create a free project at neon.tech. Copy the **pooled** connection string (the host contains `-pooler`). It ends in `?sslmode=require`.
2. This is your `DATABASE_URL`. The schema (`db/schema.sql`) is applied automatically by the worker on every run and by the local dev server.

## 2. Meta developer app (login and Marketing API)

1. developers.facebook.com, My Apps, Create App. Choose the **Business** type.
2. Add the **Facebook Login** product. Under Settings:
   - **Valid OAuth Redirect URIs**: `https://<your-domain>/api/auth/callback`
   - **App Domains** (Settings, Basic): `<your-domain>`
3. Settings, Basic: copy the **App ID** and **App Secret**. Add a privacy policy URL.
4. Permissions: the app asks for `ads_read` (ad data) plus `pages_read_engagement` and `pages_show_list` (Meta only returns video files and video frames to a token with Page access; without them video ads are read from one thumbnail and call-to-action text is missed). While the app is in **Development mode**, only people you add under App Roles (Administrators, Developers, Testers) can log in, and these permissions work for them without App Review. If the login screen does not offer them, add them in the app dashboard under Use cases, Customize, Permissions and features. Users must log out and connect again after the permission list changes. This is enough for you and your testers.
5. Going public later needs Business Verification and App Review for `ads_read` (days to weeks). Not needed now.
6. Use the stable production domain. Preview URLs change on every deploy and will not match the redirect URI.

Tip: if some ad accounts do not appear in the account list, set `META_SCOPES=ads_read,business_management`.

## 3. Vercel (hosting)

1. Import the GitHub repo into Vercel. Framework preset: **Other**. Output directory is read from `vercel.json`.
2. Add environment variables (Production):

| Name | Value |
|---|---|
| `DATABASE_URL` | Neon pooled connection string |
| `ENCRYPTION_KEY` | `openssl rand -base64 32` (32 bytes, base64). Use the same value in GitHub secrets. |
| `APP_URL` | `https://<your-domain>` (no trailing slash) |
| `META_APP_ID` / `META_APP_SECRET` | from step 2 |
| `GITHUB_DISPATCH_TOKEN` | fine-grained GitHub token for this repo with **Actions: read and write** (starts the worker) |
| `ALLOWED_META_USER_IDS` | optional, comma separated Meta user ids allowed to log in |

3. Deploy. Open the site, click "Connect Meta".

## 4. GitHub (the worker)

Repo, Settings, Secrets and variables, Actions:

| Secret | Value |
|---|---|
| `DATABASE_URL` | same as Vercel |
| `ENCRYPTION_KEY` | same as Vercel |
| `OPENROUTER_API_KEY` | your OpenRouter key |

Optional variables (Actions variables): `EXTRACTION_MODEL` (default `qwen/qwen3.8-flash`), `CLUSTER_MODEL` (`openai/gpt-4o-mini`), `INSIGHT_MODEL` (`anthropic/claude-sonnet-4.5`), `META_API_VERSION` (`v23.0`), `EXTRACT_CONCURRENCY` (`6`), `LAB_MIN_ADS` (`15`), `LAB_MIN_SPEND` (`300000`).

Check model names on openrouter.ai if a call fails with a 400 or 404.

## 5. First run

Log in, pick an ad account and a date range, click Generate Creative Intel. The API creates the report and starts the `report-worker` workflow (Actions tab). The report page fills in as each signal arrives.

## Local development (no Meta app, no keys)

Mock mode replays the demo account through the real pipeline.

```bash
python3 -m venv .venv && .venv/bin/pip install -r worker/requirements-dev.txt
npm install
.venv/bin/python dev/pg.py &                                  # local Postgres, URI in .data/pg.uri
export DATABASE_URL="$(cat .data/pg.uri)" ENCRYPTION_KEY="$(openssl rand -base64 32)"
export MOCK_META=1 MOCK_LLM=1 DISPATCH_MODE=local APP_URL=http://localhost:8935
node dev/server.js                                            # http://localhost:8935
```

Tests: `npm test` (API) and `.venv/bin/python -m pytest worker/tests` (worker, about 3 minutes).

## Things to verify with a real account

These parts talk to Meta and the LLM providers and cannot be tested offline. Check them on the first real run:

- The account list and the ad insights pull (field names are in `worker/meta_client.py`).
- Thumbnails: the request asks Meta for 480px creative thumbnails. If Meta rejects the syntax, the code falls back to the default size.
- Video extraction: the model reads Meta's short-lived video URL. If it cannot, the ad falls back to its thumbnail and is marked "fallback".
- Model names on OpenRouter.

Optional GitHub secret `OPENROUTER_API_KEYS`: comma separated list of extra OpenRouter keys. The worker spreads calls across them (and `OPENROUTER_API_KEY`). Optional variable `WINDOW_DAYS` (default 60) sets how many days insights and the Lab look at.
