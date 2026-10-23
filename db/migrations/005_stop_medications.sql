-- 005_stop_medications
--
-- Medication orders can be stopped, with a record of who stopped them and why.
-- A note that explicitly stops a drug stops it straight away; a stop the AI only
-- infers becomes a care task that proposes it, and the medication is stopped only
-- if a clinician accepts that task.
-- Rollback: db/migrations/005_stop_medications.down.sql

alter table public.medication_orders
    add column if not exists stopped_by  text,             -- clinician ID
    add column if not exists stop_reason text;

-- A care task can carry an action that runs when a clinician accepts it
alter table public.care_tasks
    add column if not exists proposed_action     text check (proposed_action in ('stop_medication')),
    add column if not exists medication_order_id uuid references public.medication_orders (id);
