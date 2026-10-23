-- 002_bed_integrity_and_discharge
--
-- 1. A bed is 'occupied' exactly when a patient is assigned to it. The original
--    demo data had a bed marked occupied with nobody in it (RES-CARD-01); it is
--    made available first so the rule can be added.
-- 2. Care tasks gain a 'cancelled' status, used when a patient is discharged
--    with tasks still open.
-- Rollback: db/migrations/002_bed_integrity_and_discharge.down.sql

update public.hospital_resources
   set status = 'available'
 where status = 'occupied' and assigned_to_patient is null;

alter table public.hospital_resources
    add constraint hospital_resources_occupied_has_patient
    check ((status = 'occupied') = (assigned_to_patient is not null));

alter table public.care_tasks drop constraint care_tasks_status_check;
alter table public.care_tasks
    add constraint care_tasks_status_check
    check (status in ('suggested', 'accepted', 'rejected', 'done', 'cancelled'));
