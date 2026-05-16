-- PingHook V4 — full schema
-- Run this in your Supabase SQL editor.
-- Drops all previous tables and recreates them cleanly.

-- ── Drop old tables ─────────────────────────────────────────────────────────
drop table if exists public.analytics_events cascade;
drop table if exists public.webhook_logs cascade;
drop table if exists public.users cascade;

-- ── Users ────────────────────────────────────────────────────────────────────
create table public.users (
  id         uuid primary key default gen_random_uuid(),
  api_key    text not null unique,
  is_active  boolean not null default true,
  created_at timestamptz not null default timezone('utc', now())
);
create index users_api_key_idx on public.users (api_key);
alter table public.users enable row level security;

-- ── Platform identities (authentication) ─────────────────────────────────────
-- Who the user IS on each platform — separate from where pings are delivered.
create table public.platform_identities (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  platform    text not null,   -- 'telegram' | 'slack' | 'discord'
  platform_id text not null,   -- telegram chat_id, slack user_id, etc.
  created_at  timestamptz not null default timezone('utc', now()),
  unique (platform, platform_id)
);
create index platform_identities_user_idx on public.platform_identities (user_id);
alter table public.platform_identities enable row level security;

-- ── Channels (delivery targets) ───────────────────────────────────────────────
-- Where pings are actually sent — distinct from authentication.
create table public.channels (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  type        text not null,   -- 'telegram' | 'slack' | 'discord'
  destination text not null,   -- chat_id for telegram, webhook_url for slack/discord
  label       text,            -- friendly name e.g. "#dev-alerts"
  is_active   boolean not null default true,
  created_at  timestamptz not null default timezone('utc', now())
);
create index channels_user_idx on public.channels (user_id);
alter table public.channels enable row level security;

-- ── Alerting rules ────────────────────────────────────────────────────────────
-- Multiple rules per user, evaluated as AND conditions.
create table public.alerting_rules (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.users(id) on delete cascade,
  rule_type  text not null,    -- 'keyword_match' | 'dedup' | 'quiet_hours' | 'label_filter'
  config     jsonb not null default '{}',
  is_active  boolean not null default true,
  created_at timestamptz not null default timezone('utc', now())
);
create index alerting_rules_user_idx on public.alerting_rules (user_id);
alter table public.alerting_rules enable row level security;

-- ── Usage logs ────────────────────────────────────────────────────────────────
-- Every request including rate-limited and suppressed ones.
create table public.usage_logs (
  id                uuid primary key default gen_random_uuid(),
  api_key           text not null,
  label             text not null default '',
  payload_size      integer not null default 0,
  status            text not null,   -- 'success' | 'failed' | 'rate_limited' | 'suppressed'
  suppressed_by     text,            -- rule_type that triggered suppression
  channels_notified integer not null default 0,
  created_at        timestamptz not null default timezone('utc', now())
);
create index usage_logs_api_key_idx on public.usage_logs (api_key, created_at desc);
create index usage_logs_status_idx  on public.usage_logs (status, created_at desc);
alter table public.usage_logs enable row level security;

-- ── Rate limits ───────────────────────────────────────────────────────────────
create table public.rate_limits (
  api_key             text primary key,
  requests_today      integer not null default 0,
  requests_this_hour  integer not null default 0,
  last_reset_daily    timestamptz not null default timezone('utc', now()),
  last_reset_hourly   timestamptz not null default timezone('utc', now())
);
alter table public.rate_limits enable row level security;

-- ── Dedup log ─────────────────────────────────────────────────────────────────
-- Keyed by user_id (not api_key) so dedup windows survive key regeneration.
create table public.dedup_log (
  user_id   uuid not null references public.users(id) on delete cascade,
  label     text not null,
  last_sent timestamptz not null,
  primary key (user_id, label)
);
alter table public.dedup_log enable row level security;

-- ── Atomic rate-limit counter increment ───────────────────────────────────────
create or replace function increment_rate_counters(p_api_key text)
returns void language sql as $$
  update public.rate_limits
  set requests_today     = requests_today + 1,
      requests_this_hour = requests_this_hour + 1
  where api_key = p_api_key;
$$;
