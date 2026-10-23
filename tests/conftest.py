"""
Shared test setup.

The services read credentials from .env at import time, so the environment is
blanked *before* they are imported. Tests never reach Supabase or Groq: the
database is replaced with FakeSupabase and outbound HTTP calls are patched.
"""

import os
import sys

import pytest

# load_dotenv() never overrides variables that are already set, even to "",
# so these win over a developer's real .env.
for var in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SECRET_KEY", "ISMA_DB_URL", "ISMA_ANON_KEY", "ZAI_API_KEY"):
    os.environ[var] = ""
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["MOCK_API_BASE_URL"] = "http://mock-emr.test"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "Ophia"), os.path.join(ROOT, "ingestion")):
    if path not in sys.path:
        sys.path.insert(0, path)


class FakeQuery:
    """Supports the subset of the supabase-py query builder the services use."""

    def __init__(self, db, table):
        self.db, self.table, self.op = db, table, "select"
        self.filters, self.values, self.row_limit, self.columns = [], None, None, None

    def select(self, columns="*"):
        # Like PostgREST, return only the requested columns, and fail on unknown
        # ones (that's how a query for a nonexistent column like bed_number errors)
        if columns.strip() != "*":
            self.columns = [c.strip() for c in columns.split(",")]
        return self

    def insert(self, row):
        self.op, self.values = "insert", row
        return self

    def update(self, values):
        self.op, self.values = "update", values
        return self

    def eq(self, column, value):
        self.filters.append((column, lambda v, value=value: v == value))
        return self

    def in_(self, column, values):
        self.filters.append((column, lambda v, values=list(values): v in values))
        return self

    def limit(self, n):
        self.row_limit = n
        return self

    def execute(self):
        if self.db.fail or self.table in self.db.fail_tables:
            raise RuntimeError("simulated database outage")
        rows = self.db.tables.setdefault(self.table, [])
        matches = [r for r in rows if all(test(r.get(c)) for c, test in self.filters)]

        class Result:
            pass

        result = Result()
        if self.op == "insert":
            # supabase-py accepts one row or a list of rows
            new_rows = [dict(r) for r in (self.values if isinstance(self.values, list) else [self.values])]
            rows.extend(new_rows)
            result.data = [dict(r) for r in new_rows]
        elif self.op == "update":
            for row in matches:
                row.update(self.values)
            result.data = [dict(r) for r in matches]
        else:
            rows_out = [dict(r) for r in matches][: self.row_limit]
            if self.columns:
                known = set().union(*(r.keys() for r in rows)) if rows else set(self.columns)
                missing = [c for c in self.columns if c not in known]
                if missing:
                    raise RuntimeError(f"column {self.table}.{missing[0]} does not exist")
                rows_out = [{c: r.get(c) for c in self.columns} for r in rows_out]
            result.data = rows_out
        return result


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = tables or {}
        self.fail = False           # every query fails
        self.fail_tables = set()    # only queries on these tables fail

    def table(self, name):
        return FakeQuery(self, name)


def demo_beds():
    return [
        {"id": "RES-ICU-01", "department": "Critical Care", "resource_name": "Ventilator Bed 01", "resource_type": "ICU_BED",
         "wing": "West Wing", "status": "available", "assigned_to_patient": None},
        {"id": "RES-NEURO-01", "department": "Neurology", "resource_name": "Observation Bed 01", "resource_type": "GEN_WARD",
         "wing": "Observation Wing B", "status": "available", "assigned_to_patient": None},
        {"id": "RES-CARD-01", "department": "Cardiology", "resource_name": "Cardiac Monitor Bay 04", "resource_type": "GEN_WARD",
         "wing": "Wing A", "status": "occupied", "assigned_to_patient": None},
        {"id": "RES-MRI-01", "department": "Radiology", "resource_name": "MRI Suite 1", "resource_type": "DIAGNOSTIC",
         "wing": "Diagnostic Block", "status": "available", "assigned_to_patient": None},
    ]


@pytest.fixture
def fake_db():
    return FakeSupabase({
        "hospital_resources": demo_beds(),
        "patients": [{"patient_id": "PT-30554", "name": "Rajesh Kumar", "age": 62, "allergies": ["Aspirin"],
                      "active_prescriptions": ["Atorvastatin"], "medical_history": "Post-MI",
                      "acuity": None, "acuity_updated_at": None}],
    })
