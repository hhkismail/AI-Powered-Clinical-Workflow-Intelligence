"""Keep db/schema.sql (fresh setups) in sync with db/migrations/ (existing databases)."""

import glob
import os
import re

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def read(path):
    with open(path, encoding="utf-8") as f:
        # Drop comments so a name mentioned in a comment doesn't count
        return re.sub(r"--[^\n]*", "", f.read()).lower()


def migrations():
    return [p for p in sorted(glob.glob(os.path.join(DB, "migrations", "*.sql"))) if not p.endswith(".down.sql")]


def test_every_migration_has_a_rollback():
    for up in migrations():
        assert os.path.exists(up[:-4] + ".down.sql"), f"{os.path.basename(up)} has no .down.sql"


def test_schema_includes_everything_migrations_add():
    schema = read(os.path.join(DB, "schema.sql"))
    for up in migrations():
        sql = read(up)
        for table in re.findall(r"create table if not exists public\.(\w+)", sql):
            assert f"create table if not exists public.{table}" in schema, f"schema.sql is missing table {table}"
        for column in re.findall(r"add column if not exists (\w+)", sql):
            assert re.search(rf"\n\s+{column}\s", schema), f"schema.sql is missing column {column}"
        for index in re.findall(r"create index if not exists (\w+)", sql):
            assert index in schema, f"schema.sql is missing index {index}"
        for table in re.findall(r"alter table public\.(\w+) enable row level security", sql):
            assert f"alter table public.{table} enable row level security" in schema, f"schema.sql doesn't enable RLS on {table}"
        for constraint in re.findall(r"add constraint (\w+)", sql):
            assert f"constraint {constraint}" in schema, f"schema.sql is missing constraint {constraint}"
        # A changed list of allowed values (e.g. a new status) must be reflected too
        for values in re.findall(r"check \(status in \(([^)]*)\)\)", sql):
            assert values in schema, f"schema.sql doesn't allow status values ({values})"


def test_reset_script_matches_seed_beds():
    """tools/reset_demo.py restores exactly the beds and states that db/seed.sql defines."""
    import importlib.util
    root = os.path.dirname(DB)
    spec = importlib.util.spec_from_file_location("reset_demo", os.path.join(root, "tools", "reset_demo.py"))
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)

    seed = read(os.path.join(DB, "seed.sql"))
    seed_beds = {bed_id.upper(): status for bed_id, status in
                 re.findall(r"\('(res-[a-z]+-\d+)',[^)]*'(available|occupied|cleaning|maintenance)',\s*null\)", seed)}
    assert seed_beds == {bed_id: status for bed_id, (status, _) in reset.DEMO_BEDS.items()}
    assert sum(1 for b in seed_beds if not b.startswith(("RES-MRI", "RES-CT"))) == 24
