-- Rollback for 006_allergy_warnings.

alter table public.medication_orders
    drop column if exists allergy_warning;
