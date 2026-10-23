-- 001_ward_board: data behind the ward board
--
-- Adds what each bed card shows: how sick the patient is (patients.acuity),
-- what they're receiving (medication_orders) and what should happen next
-- (care_tasks). The AI pipeline writes these from clinical notes; AI-suggested
-- tasks start as 'suggested' and only become real work once a clinician accepts them.
--
-- Row-level security is enabled with no policies, so only the server-side
-- secret key can read or write these tables; the publishable key cannot.
-- Rollback: db/migrations/001_ward_board.down.sql

alter table public.patients
    add column if not exists acuity text check (acuity in ('critical', 'serious', 'stable')),
    add column if not exists acuity_updated_at timestamptz;

create table if not exists public.medication_orders (
    id             uuid primary key default gen_random_uuid(),
    patient_id     text not null references public.patients (patient_id),
    drug           text not null,
    dose           text,                                  -- e.g. 25mg
    route          text check (route in ('oral', 'iv', 'im', 'subcutaneous', 'inhaled', 'topical', 'other')),
    frequency      text,                                  -- e.g. twice daily, continuous infusion
    status         text not null default 'active' check (status in ('active', 'completed', 'stopped')),
    source_note_id uuid references public.clinical_notes (id),
    started_at     timestamptz not null default now(),
    ended_at       timestamptz
);

create table if not exists public.care_tasks (
    id             uuid primary key default gen_random_uuid(),
    patient_id     text not null references public.patients (patient_id),
    description    text not null,                         -- e.g. Prep for transthoracic echocardiogram
    category       text not null default 'other'
                   check (category in ('prep', 'monitoring', 'lab', 'imaging', 'consult', 'medication', 'other')),
    status         text not null default 'suggested'
                   check (status in ('suggested', 'accepted', 'rejected', 'done')),
    suggested_by   text not null default 'ai' check (suggested_by in ('ai', 'clinician')),
    source_note_id uuid references public.clinical_notes (id),
    created_at     timestamptz not null default now(),
    decided_at     timestamptz,                           -- when it was accepted or rejected
    decided_by     text,                                  -- clinician ID
    completed_at   timestamptz
);

-- The board loads active medications and open tasks per patient
create index if not exists medication_orders_active_by_patient
    on public.medication_orders (patient_id) where status = 'active';
create index if not exists care_tasks_open_by_patient
    on public.care_tasks (patient_id) where status in ('suggested', 'accepted');

alter table public.medication_orders enable row level security;
alter table public.care_tasks enable row level security;
