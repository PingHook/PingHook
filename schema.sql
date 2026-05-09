-- Create users table
create table public.users (
  id bigint primary key, -- Telegram User ID
  chat_id bigint not null unique, -- Telegram Chat ID
  api_key uuid not null unique default gen_random_uuid(),
  created_at timestamp with time zone default timezone('utc'::text, now()) not null,
  is_active boolean default true not null
);

-- Enable RLS (Row Level Security) - optional for now but good practice
alter table public.users enable row level security;

-- Create policy to allow service role full access (if needed later)
-- For this MVP, we will largely operate with service role key from the backend.

-- Webhook history log
create table public.webhook_logs (
  id          bigserial primary key,
  chat_id     bigint not null,
  labels      text[] default '{}',
  payload     text,
  received_at timestamptz default timezone('utc'::text, now()) not null
);

create index webhook_logs_chat_id_idx on public.webhook_logs (chat_id, received_at desc);
alter table public.webhook_logs enable row level security;

-- Behaviour analytics (rate limit hits, send failures, bot commands)
create table public.analytics_events (
  id          bigserial primary key,
  event_type  text not null,
  chat_id     bigint,
  metadata    jsonb default '{}',
  created_at  timestamptz default timezone('utc'::text, now()) not null
);

create index analytics_events_type_idx    on public.analytics_events (event_type, created_at desc);
create index analytics_events_chat_id_idx on public.analytics_events (chat_id, created_at desc);
alter table public.analytics_events enable row level security;
