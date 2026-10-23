"""
Reset the demo data in Supabase to its starting state (same as db/seed.sql).

Each demo run reserves a bed, so after a few runs every bed is occupied and the
demo fails with NO_BEDS_AVAILABLE. By default only the beds are reset; clinical
notes and appointments are kept.

With --clear-board, the ward board is cleared too: all medication orders and
care tasks are deleted and patient acuity is unset. Use it to start a demo
from an empty board.

With --all, everything notes have created is deleted as well (clinical notes,
appointments, the waiting list and the public demo's AI budget log). The
deployed demo does this every night (see app.py).

Usage (from the repo root):
    python tools/reset_demo.py                 # reset the beds
    python tools/reset_demo.py --clear-board   # also clear medications, tasks and acuity
    python tools/reset_demo.py --all           # back to db/seed.sql: also delete notes, appointments, waiting list
    python tools/reset_demo.py --dry-run       # only show what would change (combines with the others)
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

# Demo bed state: id -> (status, assigned_to_patient). Keep in sync with db/seed.sql.
DEMO_BEDS = {
    "RES-ICU-01": ("available", None),
    "RES-ICU-02": ("available", None),
    "RES-ICU-03": ("available", None),
    "RES-ICU-04": ("available", None),
    "RES-ICU-05": ("available", None),
    "RES-ICU-06": ("available", None),
    "RES-NEURO-01": ("available", None),
    "RES-NEURO-02": ("available", None),
    "RES-NEURO-03": ("available", None),
    "RES-NEURO-04": ("available", None),
    "RES-NEURO-05": ("available", None),
    "RES-NEURO-06": ("available", None),
    "RES-CARD-01": ("available", None),
    "RES-CARD-02": ("available", None),
    "RES-CARD-03": ("available", None),
    "RES-CARD-04": ("available", None),
    "RES-CARD-05": ("available", None),
    "RES-CARD-06": ("maintenance", None),
    "RES-EMG-01": ("available", None),
    "RES-EMG-02": ("available", None),
    "RES-EMG-03": ("available", None),
    "RES-EMG-04": ("available", None),
    "RES-EMG-05": ("available", None),
    "RES-EMG-06": ("cleaning", None),
    "RES-MRI-01": ("available", None),
    "RES-CT-01": ("available", None),
}


def reset_beds(supabase, dry_run):
    beds = supabase.table("hospital_resources").select("id, status, assigned_to_patient").execute().data
    current = {bed["id"]: (bed["status"], bed["assigned_to_patient"]) for bed in beds}

    changes = 0
    for bed_id, (status, patient) in DEMO_BEDS.items():
        if bed_id not in current:
            print(f"  {bed_id}: missing from the database (run db/seed.sql)")
            continue
        if current[bed_id] == (status, patient):
            continue
        changes += 1
        print(f"  {bed_id}: {current[bed_id][0]} ({current[bed_id][1] or 'no patient'}) -> {status}")
        if not dry_run:
            supabase.table("hospital_resources").update(
                {"status": status, "assigned_to_patient": patient}
            ).eq("id", bed_id).execute()

    if changes == 0:
        print("Beds are already in their demo state.")
    else:
        print(f"{'Would reset' if dry_run else 'Reset'} {changes} bed(s).")


def clear_board(supabase, dry_run):
    tasks = supabase.table("care_tasks").select("id").execute().data
    meds = supabase.table("medication_orders").select("id").execute().data
    rated = supabase.table("patients").select("patient_id").not_.is_("acuity", "null").execute().data
    verb = "Would delete" if dry_run else "Deleted"
    print(f"{verb} {len(tasks)} care task(s) and {len(meds)} medication order(s); "
          f"{'would clear' if dry_run else 'cleared'} acuity for {len(rated)} patient(s).")
    if dry_run:
        return
    # Delete every row: PostgREST requires a filter, and every row has an id
    if tasks:
        supabase.table("care_tasks").delete().not_.is_("id", "null").execute()
    if meds:
        supabase.table("medication_orders").delete().not_.is_("id", "null").execute()
    if rated:
        supabase.table("patients").update({"acuity": None, "acuity_updated_at": None}) \
            .not_.is_("acuity", "null").execute()


# Tables notes write to, children first (care tasks point at notes and medications)
HISTORY_TABLES = ["bed_requests", "appointments", "clinical_notes", "note_requests"]


def clear_history(supabase, dry_run):
    """Delete everything notes have created, on top of clear_board."""
    clear_board(supabase, dry_run)
    for table in HISTORY_TABLES:
        rows = supabase.table(table).select("id").execute().data
        print(f"{'Would delete' if dry_run else 'Deleted'} {len(rows)} row(s) from {table}.")
        if rows and not dry_run:
            supabase.table(table).delete().not_.is_("id", "null").execute()


def reset_all(supabase, dry_run=False):
    """Back to the state db/seed.sql creates."""
    clear_history(supabase, dry_run)
    reset_beds(supabase, dry_run)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    # Every table has row-level security, so only the server-side secret key can reset them
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key or key.startswith("sb_publishable_"):
        print("SUPABASE_URL and SUPABASE_SECRET_KEY (the sb_secret_ key) must be set in .env")
        return 1

    supabase = create_client(url, key)
    if "--all" in sys.argv:
        reset_all(supabase, dry_run)
        return 0
    reset_beds(supabase, dry_run)
    if "--clear-board" in sys.argv:
        clear_board(supabase, dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
