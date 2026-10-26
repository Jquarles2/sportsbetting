-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run.
-- It creates the three tables BetGuru uses. It is safe to run again.

-- Your no-bet list (teams, players, games you never want in a parlay).
create table if not exists nobet (
  kind text not null,
  name text not null,
  created_at timestamptz not null default now(),
  primary key (kind, name)
);

-- Every parlay leg you save, and how it turned out once the game was graded.
create table if not exists picks_log (
  id bigint generated always as identity primary key,
  logged_on date not null,
  sport text not null,
  risk text not null,
  game text not null,
  start text,
  market text not null,
  pick text not null,
  team text,
  line double precision,
  price double precision,
  p double precision,
  result text not null default 'pending',
  graded_on date,
  unique (logged_on, sport, risk, game, market, pick)
);

-- Saved Odds API answers, so an app restart doesn't re-spend your monthly request budget.
create table if not exists cache (
  key text primary key,
  day date not null,
  value jsonb not null
);

-- Lock the tables so only your secret key (kept in Streamlit secrets) can read or write them.
-- With no policies, Supabase's public "anon" key sees nothing.
alter table nobet enable row level security;
alter table picks_log enable row level security;
alter table cache enable row level security;
