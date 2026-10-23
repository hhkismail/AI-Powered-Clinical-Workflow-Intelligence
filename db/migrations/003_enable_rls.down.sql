-- Rollback for 003_enable_rls. Re-opens these tables to the publishable key.

alter table public.patients disable row level security;
alter table public.hospital_resources disable row level security;
alter table public.clinical_notes disable row level security;
alter table public.appointments disable row level security;
