-- 006_allergy_warnings
--
-- Possible cross-reactivity with a documented allergy (e.g. a penicillin allergy
-- and meropenem) doesn't block a prescription, but the warning is stored on the
-- medication order so it stays visible on the ward board while the drug is given.
-- Direct conflicts are refused by the allergy rules and never stored.
-- Rollback: db/migrations/006_allergy_warnings.down.sql

alter table public.medication_orders
    add column if not exists allergy_warning text;
