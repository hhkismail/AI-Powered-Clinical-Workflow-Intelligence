"""
Reset the demo data in Supabase to its starting state (same as db/seed.sql).

Each demo run reserves a bed, so after a few runs every bed is occupied and the
demo fails with NO_BEDS_AVAILABLE. By default only the beds are reset; clinical
notes and appointments are kept.

With --clear-board, the ward board is cleared too: all medication orders and
care tasks are deleted and patient acuity is unset. Use it to start a demo
from an empty board.

Usage (from the repo root):
    python tools/reset_demo.py                 # reset the beds
    python tools/reset_demo.py --clear-board   # also clear medications, tasks and acuity
    python tools/reset_demo.py --dry-run       # only show what would change (combines with --clear-board)
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

# Demo bed state: id -> (status, assigned_to_patient). Keep in sync with db/seed.sql.
DEMO_BEDS = {
    "RES-ICU-01": ("available", None),
    "RES-NEURO-01": ("available", None),
    "RES-EMG-01": ("available", None),
    "RES-CARD-01": ("occupied", None),
    "RES-MRI-01": ("available", None),
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


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    # The ward board tables have row-level security, so clearing them needs the secret key
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_KEY) must be set in .env")
        return 1

    supabase = create_client(url, key)
    reset_beds(supabase, dry_run)
    if "--clear-board" in sys.argv:
        if not os.getenv("SUPABASE_SECRET_KEY"):
            print("--clear-board needs SUPABASE_SECRET_KEY in .env (row-level security blocks the publishable key)")
            return 1
        clear_board(supabase, dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
