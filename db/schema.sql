-- Ophia database schema (Supabase / PostgreSQL)
--
-- Matches the live project's tables. Run in the Supabase SQL editor (or psql)
-- on a fresh project, then run seed.sql for the demo data.
-- Safe to re-run: every statement uses IF NOT EXISTS.

create table if not exists public.patients (
    patient_id           text primary key,
    name                 text not null,
    age                  integer,
    allergies            text[],
    active_prescriptions text[],
    medical_history      text,
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
    assigned_to_patient text references public.patients (patient_id)
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
