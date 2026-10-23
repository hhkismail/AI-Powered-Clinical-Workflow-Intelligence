-- 003_enable_rls
--
-- Row-level security on the original four tables, with no policies. Until now
-- anyone holding the publishable key (which is designed to be public) could read
-- or delete every patient record. After this, only the server-side secret key can
-- use these tables, matching medication_orders and care_tasks (migration 001).
--
-- The browser never talks to Supabase directly: both pages go through server.py,
-- and the orchestrator reads patient history with the secret key.
-- Rollback: db/migrations/003_enable_rls.down.sql

alter table public.patients enable row level security;
alter table public.hospital_resources enable row level security;
alter table public.clinical_notes enable row level security;
alter table public.appointments enable row level security;
