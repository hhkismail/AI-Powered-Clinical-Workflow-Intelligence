-- 004_bed_requests: the waiting list for beds
--
-- When a note admits a patient but no suitable bed is free, the request is
-- recorded here instead of being rejected and forgotten. The ward board lists
-- waiting requests (sickest first, then longest waiting) so a clinician can
-- assign a bed as one becomes free, or remove the request.
-- Rollback: db/migrations/004_bed_requests.down.sql

create table if not exists public.bed_requests (
    id              uuid primary key default gen_random_uuid(),
    patient_id      text not null references public.patients (patient_id),
    ward_type       text not null check (ward_type in ('icu', 'observation', 'general')),
    resource_type   text not null check (resource_type in ('ICU_BED', 'GEN_WARD')),
    department      text,                                 -- from the note; preferred when assigning
    clinical_reason text,
    status          text not null default 'waiting' check (status in ('waiting', 'assigned', 'cancelled')),
    requested_at    timestamptz not null default now(),
    resolved_at     timestamptz,                          -- when assigned or cancelled
    resolved_by     text,                                 -- clinician ID, or 'system' for a new note
    assigned_bed_id text references public.hospital_resources (id)
);

-- At most one open request per patient, even if two notes arrive at once
create unique index if not exists bed_requests_one_waiting_per_patient
    on public.bed_requests (patient_id) where status = 'waiting';

alter table public.bed_requests enable row level security;
