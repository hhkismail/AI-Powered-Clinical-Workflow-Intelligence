-- 007_note_requests
--
-- The public demo's AI budget (ingestion/demo_budget.py): one row per note
-- submitted on the deployed site, so visitors past the budget get the mock AI
-- instead of using up the shared Groq key. The client is a salted hash of the
-- visitor's address, never the address itself. Cleared by the nightly reset.
-- Rollback: db/migrations/007_note_requests.down.sql

create table if not exists public.note_requests (
    id         bigint generated always as identity primary key,
    client     text not null,                                   -- salted hash, not an IP address
    ai         text not null check (ai in ('llm', 'mock')),
    created_at timestamptz not null default now()
);

create index if not exists note_requests_client_time on public.note_requests (client, created_at);
create index if not exists note_requests_time on public.note_requests (created_at);

alter table public.note_requests enable row level security;
