-- Rollback for 002_bed_integrity_and_discharge.
-- Cancelled tasks become 'rejected' (the closest earlier status) so the old
-- check can be restored. The bed made available in 002 is not re-occupied.

alter table public.hospital_resources drop constraint if exists hospital_resources_occupied_has_patient;

update public.care_tasks set status = 'rejected' where status = 'cancelled';
alter table public.care_tasks drop constraint care_tasks_status_check;
alter table public.care_tasks
    add constraint care_tasks_status_check
    check (status in ('suggested', 'accepted', 'rejected', 'done'));
