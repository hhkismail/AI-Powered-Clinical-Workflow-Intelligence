-- Ophia database schema (Supabase / PostgreSQL)
--
-- The complete current schema. On a fresh project, run this in the Supabase
-- SQL editor (or psql), then seed.sql for the demo data.
-- A database created before a change should apply the files in db/migrations/
-- instead, in order. Safe to re-run: every statement uses IF NOT EXISTS.

create table if not exists public.patients (
    patient_id           text primary key,
    name                 text not null,
    age                  integer,
    allergies            text[],
    active_prescriptions text[],
    medical_history      text,
    acuity               text check (acuity in ('critical', 'serious', 'stable')),
    acuity_updated_at    timestamptz,
    created_at           timestamptz default now()
);

-- Beds and other bookable resources. reserve-bed only books ICU_BED and GEN_WARD;
-- DIAGNOSTIC rows (e.g. an MRI suite) are listed but not reservable as beds.
create table if not exists public.hospital_resources (
    id                  text primary key,                 -- e.g. RES-ICU-01
    resource_name       text not null,                    -- e.g. Ventilator Bed 01
    resource_type       text not null,                    -- ICU_BED | GEN_WARD | DIAGNOSTIC
    department          text,
    wing                text,
    status              text check (status in ('available', 'occupied', 'maintenance', 'cleaning')),
    assigned_to_patient text references public.patients (patient_id),
    -- A bed is occupied exactly when a patient is assigned (no "ghost" occupied beds)
    constraint hospital_resources_occupied_has_patient
        check ((status = 'occupied') = (assigned_to_patient is not null))
);

-- One row per processed note: the LLM's extracted diagnoses and prescriptions.
create table if not exists public.clinical_notes (
    id              uuid primary key default gen_random_uuid(),
    patient_id      text references public.patients (patient_id),
    raw_input       text,
    structured_data jsonb,                                -- {"diagnoses": [...], "prescriptions": [...]}
    processed_at    timestamptz default now()
);

create table if not exists public.appointments (
    id               text primary key,
    patient_id       text references public.patients (patient_id),
    department       text,
    appointment_date date,
    timeframe_days   integer,
    reason           text
);

-- ----- Ward board (added in migrations/001_ward_board.sql) -----

-- What each patient is receiving. Written by the AI pipeline from clinical notes.
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

-- What should happen next. AI suggestions start as 'suggested' and only become
-- real work once a clinician accepts them.
create table if not exists public.care_tasks (
    id             uuid primary key default gen_random_uuid(),
    patient_id     text not null references public.patients (patient_id),
    description    text not null,                         -- e.g. Prep for transthoracic echocardiogram
    category       text not null default 'other'
                   check (category in ('prep', 'monitoring', 'lab', 'imaging', 'consult', 'medication', 'other')),
    -- 'cancelled': still open when the patient was discharged
    status         text not null default 'suggested'
                   constraint care_tasks_status_check
                   check (status in ('suggested', 'accepted', 'rejected', 'done', 'cancelled')),
    suggested_by   text not null default 'ai' check (suggested_by in ('ai', 'clinician')),
    source_note_id uuid references public.clinical_notes (id),
    created_at     timestamptz not null default now(),
    decided_at     timestamptz,                           -- when it was accepted or rejected
    decided_by     text,                                  -- clinician ID
    completed_at   timestamptz
);

create index if not exists medication_orders_active_by_patient
    on public.medication_orders (patient_id) where status = 'active';
create index if not exists care_tasks_open_by_patient
    on public.care_tasks (patient_id) where status in ('suggested', 'accepted');

-- No policies: only the server-side secret key can access these tables
alter table public.medication_orders enable row level security;
alter table public.care_tasks enable row level security;
