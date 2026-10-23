"""
Reset the demo beds in Supabase to their starting state (same as db/seed.sql).

Each demo run reserves a bed, so after a few runs every bed is occupied and the
demo fails with NO_BEDS_AVAILABLE. Clinical notes and appointments are kept.

Usage (from the repo root):
    python tools/reset_demo.py            # reset the beds
    python tools/reset_demo.py --dry-run  # only show what would change
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


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        return 1

    supabase = create_client(url, key)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
