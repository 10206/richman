-- 001_init.sql — Supabase(Postgres) 초기 스키마
-- app/db/store.py (SQLiteStore)와 동일한 논리 스키마.
-- Supabase SQL Editor에서 실행. 개인용 백엔드(service key 접근)라 RLS는 켜되
-- 정책 없이 service role만 접근하도록 둔다.

create table if not exists daily_scores (
    date        date not null,
    market      text not null,
    sector      text not null,
    score       double precision,
    trend       double precision,
    volume      double precision,
    macro       double precision,
    w_trend     double precision,
    w_volume    double precision,
    w_macro     double precision,
    signal      text,
    stance      text,
    regime      text,
    unique (date, market, sector)
);
create index if not exists idx_daily_scores_lookup on daily_scores (market, sector, date desc);

create table if not exists regime_history (
    date        date not null,
    market      text not null,
    regime      text,
    r_score     double precision,
    l_score     double precision,
    local_trend double precision,
    unique (date, market)
);
create index if not exists idx_regime_history_lookup on regime_history (market, date desc);

create table if not exists macro_snapshots (
    date        date not null,
    market      text not null,
    payload     jsonb not null,
    unique (date, market)
);

create table if not exists notification_events (
    id          bigint generated always as identity primary key,
    created_at  timestamptz not null default now(),
    market      text not null,
    sector      text,
    event_type  text not null,
    title       text not null,
    body        text not null,
    immediate   boolean not null default false,
    delivered   boolean not null default false
);
create index if not exists idx_notifications_pending on notification_events (delivered, id);

create table if not exists news_items (
    id          bigint generated always as identity primary key,
    date        date not null,
    market      text not null,
    sector      text not null,
    title       text,
    url         text,
    source      text,
    sentiment   double precision,
    unique (market, sector, url)
);
create index if not exists idx_news_items_lookup on news_items (market, sector, date desc);

create table if not exists news_summaries (
    date        date not null,
    market      text not null,
    sector      text not null,
    summary     text,
    unique (date, market, sector)
);

-- RLS: service key(백엔드)만 접근. anon 접근 차단.
alter table daily_scores        enable row level security;
alter table regime_history      enable row level security;
alter table macro_snapshots     enable row level security;
alter table notification_events enable row level security;
alter table news_items          enable row level security;
alter table news_summaries      enable row level security;
