-- Rollback for 005_stop_medications. Stopped orders stay stopped; only the
-- who/why details and the task-to-medication links are removed.

alter table public.care_tasks
    drop column if exists medication_order_id,
    drop column if exists proposed_action;

alter table public.medication_orders
    drop column if exists stop_reason,
    drop column if exists stopped_by;
