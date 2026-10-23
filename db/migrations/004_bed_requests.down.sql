-- Rollback for 004_bed_requests. Deletes the waiting list and its history.

drop table if exists public.bed_requests;
