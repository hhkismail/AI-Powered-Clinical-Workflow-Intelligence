-- Rollback for 001_ward_board. Deletes all medication orders and care tasks.

drop table if exists public.care_tasks;
drop table if exists public.medication_orders;

alter table public.patients
    drop column if exists acuity_updated_at,
    drop column if exists acuity;
