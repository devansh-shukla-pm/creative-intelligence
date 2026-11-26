-- Creative Intelligence: Postgres schema (Neon in production, any Postgres locally).
-- Idempotent: safe to run on every deploy / worker start.

CREATE TABLE IF NOT EXISTS users (
  id              text PRIMARY KEY,            -- Meta user id
  name            text,
  token_enc       text NOT NULL,               -- AES-256-GCM encrypted long-lived Meta token
  token_expires_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_login_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  id_hash     text PRIMARY KEY,                -- sha256 of the cookie value
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

-- One row per generated report (ad account + date range).
CREATE TABLE IF NOT EXISTS reports (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id    text NOT NULL,                 -- Meta ad account id without the act_ prefix
  account_name  text,
  currency      text,
  date_from     date NOT NULL,
  date_to       date NOT NULL,
  status        text NOT NULL DEFAULT 'queued',   -- queued | running | done | failed
  stage         text,                              -- pulling | extracting | clustering | naming | assembling | insights | lab
  signal_a      timestamptz,                       -- Meta data ready
  signal_b      timestamptz,                       -- classification ready (SKU data ready)
  signal_c      timestamptz,                       -- insights ready
  signal_d      timestamptz,                       -- Experimentation Lab ready
  progress      jsonb NOT NULL DEFAULT '{}'::jsonb, -- {message, done, total}
  error         text,
  dispatched_at timestamptz,
  heartbeat_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
-- Insights and the Lab always look at the last WINDOW_DAYS up to today, whatever range the report shows.
ALTER TABLE reports ADD COLUMN IF NOT EXISTS window_from date;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS window_to   date;
CREATE INDEX IF NOT EXISTS reports_user_idx ON reports(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS reports_lookup_idx ON reports(user_id, account_id, date_from, date_to);

-- Report payloads, one row per kind so a signal only rewrites its own piece.
-- kind: data | cmt_ads | cmt_dims | audit | insights | lab
CREATE TABLE IF NOT EXISTS report_payloads (
  report_id   uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  body        jsonb NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, kind)
);

-- Raw Meta metrics for the ads in one report (depend on the date range).
CREATE TABLE IF NOT EXISTS report_ads (
  report_id  uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  ad_id      text NOT NULL,
  metrics    jsonb NOT NULL,
  PRIMARY KEY (report_id, ad_id)
);

-- Per-ad cache that survives across reports: creative info + extraction + cluster labels + product.
-- This is what makes a second report on the same account cheap: only new ads hit the LLMs.
CREATE TABLE IF NOT EXISTS ad_cache (
  account_id          text NOT NULL,
  ad_id               text NOT NULL,
  creative            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- name, media_type, preview_link, campaign, media urls
  extraction          jsonb,                                -- extraction prompt output
  extraction_status   text,                                 -- ok | fallback | failed | skipped
  extraction_attempts int NOT NULL DEFAULT 0,
  cluster_labels      jsonb,                                -- {problem_statement_text: label, ...}
  product             jsonb,                                -- {product, category, is_multi}
  updated_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, ad_id)
);

-- Stable vocabularies per account: cluster labels per field, product names.
CREATE TABLE IF NOT EXISTS account_memory (
  account_id      text PRIMARY KEY,
  cluster_memory  jsonb NOT NULL DEFAULT '{}'::jsonb,
  product_memory  jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Ad thumbnails (small JPEGs) live in Postgres: free, no object store to run.
CREATE TABLE IF NOT EXISTS thumbs (
  account_id    text NOT NULL,
  ad_id         text NOT NULL,
  content_type  text NOT NULL DEFAULT 'image/jpeg',
  bytes         bytea NOT NULL,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, ad_id)
);

-- Meta insight rows already pulled for an account and date range: the same request within a few hours is answered from here,
-- not from Meta (protects the app's API rate limit).
CREATE TABLE IF NOT EXISTS insights_cache (
  account_id  text NOT NULL,
  date_from   date NOT NULL,
  date_to     date NOT NULL,
  rows        jsonb NOT NULL,
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, date_from, date_to)
);

-- How many times an ad has been sent to the clustering prompt, so an ad the model keeps skipping a field for is not re-sent forever.
ALTER TABLE ad_cache ADD COLUMN IF NOT EXISTS cluster_attempts int NOT NULL DEFAULT 0;

-- Meta results stored per ad per day, so any date range is a sum of stored days and only days we do not have are pulled.
CREATE TABLE IF NOT EXISTS ad_daily (
  account_id  text NOT NULL,
  ad_id       text NOT NULL,
  day         date NOT NULL,
  spend       double precision NOT NULL,
  impressions double precision NOT NULL DEFAULT 0,
  clicks      double precision NOT NULL DEFAULT 0,
  link_clicks double precision NOT NULL DEFAULT 0,
  purchases   double precision NOT NULL DEFAULT 0,
  value       double precision NOT NULL DEFAULT 0,
  atc         double precision NOT NULL DEFAULT 0,
  lpv         double precision NOT NULL DEFAULT 0,
  frequency   double precision NOT NULL DEFAULT 0,
  PRIMARY KEY (account_id, ad_id, day)
);
CREATE INDEX IF NOT EXISTS ad_daily_day_idx ON ad_daily (account_id, day);

-- Names that go with an ad id (the daily rows stay small).
CREATE TABLE IF NOT EXISTS ad_names (
  account_id    text NOT NULL,
  ad_id         text NOT NULL,
  ad_name       text,
  campaign_id   text,
  campaign_name text,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, ad_id)
);

-- Days already pulled for an account (a day with no spend is pulled too). pulled_at says whether the day was final when pulled.
CREATE TABLE IF NOT EXISTS insight_days (
  account_id text NOT NULL,
  day        date NOT NULL,
  pulled_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, day)
);
