-- 0001_initial.sql — implements 02-data-model.md
-- Forward-only, hand-written, safe to re-run in development (02 §7).

CREATE EXTENSION IF NOT EXISTS citext;

-- ---------------------------------------------------------------- enums (02 §4)
DO $$ BEGIN
  CREATE TYPE run_status AS ENUM
    ('queued','collecting','scoring','analyzing','complete','partial','failed','cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE run_stage AS ENUM
    ('resolve','collect_demand','collect_competition','collect_advertising',
     'collect_density','collect_value','collect_trends','score','analyze','finalize');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE stage_status AS ENUM ('pending','running','ok','failed','skipped');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE signal_key AS ENUM
    ('demand','competition','advertising','density','customer_value','trends');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE signal_band AS ENUM
    ('low','moderate','high','growing','declining','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE verdict AS ENUM ('pursue','watch','pass');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE evidence_status AS ENUM ('ok','absent','error');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE report_generator AS ENUM ('llm','template');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE run_trigger AS ENUM ('user','forced_refresh','scheduled','system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE resolution_method AS ENUM ('exact','alias','fuzzy','manual');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE location_granularity AS ENUM ('country','admin1','city','suburb');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE access_tier AS ENUM ('early_access','internal','disabled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------- 02 §3.1
CREATE TABLE IF NOT EXISTS accounts (
  id              uuid PRIMARY KEY,
  email           citext NOT NULL UNIQUE,
  display_name    text,
  access_tier     access_tier NOT NULL DEFAULT 'early_access',
  run_quota_month int NOT NULL DEFAULT 50,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- 02 §3.2
CREATE TABLE IF NOT EXISTS services (
  id            bigserial PRIMARY KEY,
  slug          text NOT NULL UNIQUE,
  display_name  text NOT NULL,
  parent_id     bigint REFERENCES services(id),
  keyword_seeds jsonb NOT NULL DEFAULT '[]'::jsonb,
  anzsic_code   text,
  is_active     boolean NOT NULL DEFAULT true
);

-- ---------------------------------------------------------------- 02 §3.3
CREATE TABLE IF NOT EXISTS locations (
  id             bigserial PRIMARY KEY,
  slug           text NOT NULL UNIQUE,
  country_code   char(2) NOT NULL,
  admin1         text,
  locality       text,
  granularity    location_granularity NOT NULL,
  display_name   text NOT NULL,
  population     int,
  vendor_geo_ids jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------- 02 §3.4
CREATE TABLE IF NOT EXISTS markets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  service_id  bigint NOT NULL REFERENCES services(id),
  location_id bigint NOT NULL REFERENCES locations(id),
  market_key  text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (service_id, location_id)
);

-- ---------------------------------------------------------------- 02 §3.5
CREATE TABLE IF NOT EXISTS market_aliases (
  id                bigserial PRIMARY KEY,
  raw_input         text NOT NULL UNIQUE,
  market_id         uuid NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
  resolution_method resolution_method NOT NULL,
  confidence        numeric(4,3) NOT NULL,
  first_seen_at     timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  hit_count         int NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------- 02 §3.6
CREATE TABLE IF NOT EXISTS research_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  market_id     uuid NOT NULL REFERENCES markets(id),
  requested_by  uuid REFERENCES accounts(id),
  status        run_status NOT NULL DEFAULT 'queued',
  current_stage run_stage,
  trigger       run_trigger NOT NULL DEFAULT 'user',
  requested_at  timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  completed_at  timestamptz,
  claimed_at    timestamptz,
  claimed_by    text,
  attempt       int NOT NULL DEFAULT 0,
  budget_cents  int NOT NULL,
  spend_cents   int NOT NULL DEFAULT 0,
  idempotency_key text,
  error_code    text,
  error_detail  text
);

CREATE INDEX IF NOT EXISTS research_runs_queue_idx
  ON research_runs (status, requested_at);
CREATE INDEX IF NOT EXISTS research_runs_freshness_idx
  ON research_runs (market_id, completed_at DESC)
  WHERE status IN ('complete','partial');
CREATE UNIQUE INDEX IF NOT EXISTS research_runs_idem_idx
  ON research_runs (requested_by, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
-- 05 §9: one active run per market
CREATE UNIQUE INDEX IF NOT EXISTS research_runs_one_active_idx
  ON research_runs (market_id)
  WHERE status IN ('queued','collecting','scoring','analyzing');

-- ---------------------------------------------------------------- 02 §3.7
CREATE TABLE IF NOT EXISTS run_stages (
  id           bigserial PRIMARY KEY,
  run_id       uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
  stage        run_stage NOT NULL,
  status       stage_status NOT NULL DEFAULT 'pending',
  attempt      int NOT NULL DEFAULT 1,
  started_at   timestamptz,
  finished_at  timestamptz,
  error_code   text,
  error_detail text,
  UNIQUE (run_id, stage, attempt)
);

-- ---------------------------------------------------------------- 02 §3.8
CREATE TABLE IF NOT EXISTS evidence (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
  market_id    uuid NOT NULL REFERENCES markets(id),
  signal       signal_key NOT NULL,
  collector    text NOT NULL,
  vendor       text NOT NULL,
  endpoint     text NOT NULL,
  status       evidence_status NOT NULL,
  payload      jsonb NOT NULL,
  source_url   text,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz,
  cost_cents   numeric(8,4) NOT NULL DEFAULT 0,
  request_hash text NOT NULL
);

CREATE INDEX IF NOT EXISTS evidence_run_signal_idx ON evidence (run_id, signal);
CREATE INDEX IF NOT EXISTS evidence_market_signal_idx
  ON evidence (market_id, signal, fetched_at DESC);
CREATE INDEX IF NOT EXISTS evidence_expiry_idx
  ON evidence (expires_at) WHERE expires_at IS NOT NULL;

-- ---------------------------------------------------------------- 02 §3.9
CREATE TABLE IF NOT EXISTS signals (
  run_id         uuid NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
  signal         signal_key NOT NULL,
  score          numeric(5,2),
  confidence     numeric(4,3) NOT NULL,
  band           signal_band,
  inputs         jsonb NOT NULL DEFAULT '{}'::jsonb,
  method_version text NOT NULL,
  notes          text,
  PRIMARY KEY (run_id, signal)
);

-- ---------------------------------------------------------------- 02 §3.10
CREATE TABLE IF NOT EXISTS scores (
  run_id            uuid PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
  opportunity_score numeric(5,2) NOT NULL,
  verdict           verdict NOT NULL,
  confidence        numeric(4,3) NOT NULL,
  weights_version   text NOT NULL,
  computed_at       timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- 02 §3.11
CREATE TABLE IF NOT EXISTS reports (
  run_id         uuid PRIMARY KEY REFERENCES research_runs(id) ON DELETE CASCADE,
  payload        jsonb NOT NULL,
  generator      report_generator NOT NULL,
  provider       text,
  model          text,
  prompt_version text,
  generated_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- 02 §3.12
CREATE TABLE IF NOT EXISTS source_cache (
  request_hash text PRIMARY KEY,
  vendor       text NOT NULL,
  endpoint     text NOT NULL,
  market_id    uuid REFERENCES markets(id),
  payload      jsonb NOT NULL,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS source_cache_expiry_idx ON source_cache (expires_at);

-- ---------------------------------------------------------------- 02 §3.13
CREATE TABLE IF NOT EXISTS events_outbox (
  id           bigserial PRIMARY KEY,
  event_type   text NOT NULL,
  payload      jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz,
  attempts     int NOT NULL DEFAULT 0,
  last_error   text
);
CREATE INDEX IF NOT EXISTS events_outbox_undelivered_idx
  ON events_outbox (created_at) WHERE delivered_at IS NULL;
