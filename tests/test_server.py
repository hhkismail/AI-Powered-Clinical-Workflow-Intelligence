"""Tests for the mock EMR API (server.py)."""

from datetime import date, timedelta

import pytest

import server


@pytest.fixture
def client(fake_db, monkeypatch):
    monkeypatch.setattr(server, "supabase", fake_db)
    return server.app.test_client()


def bed(fake_db, bed_id):
    return next(b for b in fake_db.tables["hospital_resources"] if b["id"] == bed_id)


# ---------- reserve-bed ----------

@pytest.mark.parametrize("ward_type, expected_bed", [
    ("icu", "RES-ICU-01"),
    ("ICU", "RES-ICU-01"),
    ("ICU_BED", "RES-ICU-01"),
    (" observation ", "RES-NEURO-01"),
    ("general", "RES-NEURO-01"),
])
def test_reserve_bed_maps_ward_type_to_stored_bed_type(client, fake_db, ward_type, expected_bed):
    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": ward_type})

    assert resp.status_code == 200
    assert resp.get_json()["reservation_id"] == expected_bed
    assert bed(fake_db, expected_bed)["status"] == "occupied"
    assert bed(fake_db, expected_bed)["assigned_to_patient"] == "PT-30554"


@pytest.mark.parametrize("ward_type", ["cardiology", "diagnostic", ""])
def test_reserve_bed_rejects_unknown_ward_type(client, ward_type):
    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": ward_type})

    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "INVALID_WARD_TYPE"


def test_reserve_bed_reports_no_beds_when_ward_is_full(client, fake_db):
    bed(fake_db, "RES-ICU-01")["status"] = "occupied"

    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "icu"})

    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "NO_BEDS_AVAILABLE"


def test_reserve_bed_requires_patient_and_ward(client):
    resp = client.post("/api/reserve-bed", json={"ward_type": "icu"})

    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "MISSING_PARAMETER"


def test_reserve_bed_returns_500_when_database_fails(client, fake_db):
    fake_db.fail = True

    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "icu"})

    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "SUPABASE_QUERY_FAILED"


# ---------- update-record ----------

def test_update_record_stores_structured_data_as_json_object(client, fake_db):
    payload = {"patient_id": "PT-30554", "diagnoses": ["Atrial fibrillation"],
               "prescriptions": [{"drug": "Metoprolol", "dosage": "25mg", "route": "oral"}]}

    resp = client.post("/api/update-record", json=payload)

    assert resp.status_code == 200
    stored = fake_db.tables["clinical_notes"][0]
    assert stored["id"] == resp.get_json()["record_id"]
    # A dict, not a JSON-encoded string, so jsonb stores an object
    assert stored["structured_data"] == {"diagnoses": payload["diagnoses"], "prescriptions": payload["prescriptions"]}


def test_update_record_requires_patient_id(client, fake_db):
    resp = client.post("/api/update-record", json={"diagnoses": ["x"]})

    assert resp.status_code == 400
    assert "clinical_notes" not in fake_db.tables


def test_update_record_fails_loudly_without_database(monkeypatch):
    monkeypatch.setattr(server, "supabase", None)

    resp = server.app.test_client().post("/api/update-record", json={"patient_id": "PT-30554"})

    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


# ---------- schedule-appointment ----------

def test_schedule_appointment_stores_date_and_timeframe(client, fake_db):
    resp = client.post("/api/schedule-appointment", json={
        "patient_id": "PT-30554", "department": "Cardiology",
        "appointment_date": "2026-11-20", "timeframe_days": 28, "reason": "AF review"})

    assert resp.status_code == 200
    stored = fake_db.tables["appointments"][0]
    assert stored["appointment_date"] == "2026-11-20"
    assert stored["timeframe_days"] == 28
    assert stored["reason"] == "AF review"
    assert resp.get_json()["scheduled_details"]["date"] == "2026-11-20"


def test_schedule_appointment_derives_date_from_timeframe(client, fake_db):
    resp = client.post("/api/schedule-appointment", json={"patient_id": "PT-30554", "timeframe_days": 7})

    assert resp.status_code == 200
    assert fake_db.tables["appointments"][0]["appointment_date"] == (date.today() + timedelta(days=7)).isoformat()


def test_schedule_appointment_defaults_reason_when_missing_or_null(client, fake_db):
    client.post("/api/schedule-appointment", json={"patient_id": "PT-30554", "reason": None})

    assert fake_db.tables["appointments"][0]["reason"] == "Routine Checkup"


@pytest.mark.parametrize("bad", [{"appointment_date": "next week"}, {"timeframe_days": "soon"}])
def test_schedule_appointment_rejects_invalid_dates(client, fake_db, bad):
    resp = client.post("/api/schedule-appointment", json={"patient_id": "PT-30554", **bad})

    assert resp.status_code == 400
    assert "appointments" not in fake_db.tables


# ---------- ward-availability ----------

def test_ward_availability_counts_free_beds_per_wing(client):
    resp = client.get("/api/ward-availability")

    data = resp.get_json()
    assert resp.status_code == 200
    assert {w["wing"]: w["available_beds"] for w in data["wards"]} == {
        "West Wing": 1, "Observation Wing B": 1, "Wing A": 0, "Diagnostic Block": 1}
    # Previously hardcoded to "2026-04-23T08:00:00Z"
    assert data["timestamp"][:10] in {date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat(),
                                      (date.today() + timedelta(days=1)).isoformat()}
