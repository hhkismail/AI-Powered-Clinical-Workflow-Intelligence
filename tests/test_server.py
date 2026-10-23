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


def test_reserve_bed_returns_existing_bed_instead_of_a_second_one(client, fake_db):
    first = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "observation"}).get_json()

    again = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "general"}).get_json()

    assert again["reservation_id"] == first["reservation_id"]
    assert again["already_assigned"] is True
    beds_held = [b["id"] for b in fake_db.tables["hospital_resources"] if b["assigned_to_patient"] == "PT-30554"]
    assert beds_held == [first["reservation_id"]]


def test_reserve_bed_of_a_different_type_is_a_transfer(client, fake_db):
    client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "observation"})

    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "icu"}).get_json()

    assert resp["reservation_id"] == "RES-ICU-01"
    assert resp["transferred_from"] == ["RES-NEURO-01"]
    old_bed = bed(fake_db, "RES-NEURO-01")
    assert (old_bed["status"], old_bed["assigned_to_patient"]) == ("cleaning", None)


def test_observation_request_prefers_an_observation_bed(client, fake_db):
    # A general bed listed first must not win over the observation bed
    fake_db.tables["hospital_resources"].insert(0, {
        "id": "RES-EMG-01", "department": "Emergency", "resource_name": "Triage Bay 02", "resource_type": "GEN_WARD",
        "wing": "Triage Wing", "status": "available", "assigned_to_patient": None})

    observation = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "observation"}).get_json()
    general = client.post("/api/reserve-bed", json={"patient_id": "PT-40992", "ward_type": "general"}).get_json()

    assert observation["reservation_id"] == "RES-NEURO-01"
    assert general["reservation_id"] == "RES-EMG-01"


def test_observation_request_falls_back_to_any_general_bed(client, fake_db):
    bed(fake_db, "RES-NEURO-01")["status"] = "maintenance"
    fake_db.tables["hospital_resources"].append({
        "id": "RES-EMG-01", "department": "Emergency", "resource_name": "Triage Bay 02", "resource_type": "GEN_WARD",
        "wing": "Triage Wing", "status": "available", "assigned_to_patient": None})

    resp = client.post("/api/reserve-bed", json={"patient_id": "PT-30554", "ward_type": "observation"}).get_json()

    assert resp["reservation_id"] == "RES-EMG-01"


def test_general_request_prefers_a_bed_in_the_notes_department(client, fake_db):
    # RES-CARD-02 sorts first by ID, but an Emergency note should go to triage
    fake_db.tables["hospital_resources"] += [
        {"id": "RES-CARD-02", "department": "Cardiology", "resource_name": "Cardiac Monitor Bay 02", "resource_type": "GEN_WARD",
         "wing": "Wing A", "status": "available", "assigned_to_patient": None},
        {"id": "RES-EMG-02", "department": "Emergency", "resource_name": "Triage Bay 01", "resource_type": "GEN_WARD",
         "wing": "Triage Wing", "status": "available", "assigned_to_patient": None}]
    bed(fake_db, "RES-NEURO-01")["status"] = "maintenance"

    emergency = client.post("/api/reserve-bed", json={"patient_id": "PT-20221", "ward_type": "general", "department": "Emergency"})
    no_department = client.post("/api/reserve-bed", json={"patient_id": "PT-40992", "ward_type": "general"})

    assert emergency.get_json()["reservation_id"] == "RES-EMG-02"
    assert no_department.get_json()["reservation_id"] == "RES-CARD-02"   # falls back to ID order


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
    assert isinstance(stored["structured_data"], dict)
    assert stored["structured_data"]["diagnoses"] == payload["diagnoses"]
    assert stored["structured_data"]["prescriptions"] == payload["prescriptions"]


# ---------- update-record: ward board data ----------

FULL_NOTE = {
    "patient_id": "PT-30554",
    "diagnoses": ["Atrial fibrillation with RVR"],
    "prescriptions": [
        {"drug": "Metoprolol", "dosage": "25mg", "route": "orally", "frequency": "twice daily"},
        {"drug": "Heparin", "dosage": "5000 units", "route": "IV drip", "frequency": "continuous"},
        "Paracetamol 1g",
    ],
    "acuity": "Serious",
    "next_steps": [
        {"description": "Continuous telemetry monitoring", "category": "monitoring"},
        {"description": "Prep for transthoracic echocardiogram", "category": "PREP"},
        {"description": "Ask a friend", "category": "vibes"},
    ],
    "raw_input": "Admit to observation. Metoprolol 25mg PO BD...",
    "reasoning": "AF with RVR needs monitored admission; no allergy conflict with metoprolol.",
}


def test_update_record_creates_medication_orders_with_normalized_routes(client, fake_db):
    resp = client.post("/api/update-record", json=FULL_NOTE)

    note_id = resp.get_json()["record_id"]
    meds = fake_db.tables["medication_orders"]
    assert resp.get_json()["medication_orders_created"] == 3
    assert [(m["drug"], m["dose"], m["route"], m["frequency"]) for m in meds] == [
        ("Metoprolol", "25mg", "oral", "twice daily"),
        ("Heparin", "5000 units", "iv", "continuous"),
        ("Paracetamol 1g", None, None, None),   # a bare string still becomes an order
    ]
    assert all(m["source_note_id"] == note_id and m["patient_id"] == "PT-30554" for m in meds)


def test_update_record_does_not_duplicate_active_medication_orders(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)
    follow_up = {**FULL_NOTE, "prescriptions": [
        {"drug": "metoprolol", "dosage": "25 mg", "route": "PO"},     # same order, different wording
        {"drug": "Metoprolol", "dosage": "50mg", "route": "oral"},    # dose change is a new order
    ]}

    resp = client.post("/api/update-record", json=follow_up)

    assert resp.get_json()["medication_orders_created"] == 1
    assert [m["dose"] for m in fake_db.tables["medication_orders"] if m["drug"].lower() == "metoprolol"] == ["25mg", "50mg"]


def test_update_record_does_not_duplicate_open_care_tasks(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)
    follow_up = {**FULL_NOTE, "next_steps": [
        {"description": "continuous telemetry monitoring.", "category": "monitoring"},   # already open
        {"description": "Repeat ECG in 6 hours", "category": "monitoring"},
        {"description": "Repeat ECG in 6 hours", "category": "monitoring"},              # repeated within the note
    ]}

    resp = client.post("/api/update-record", json=follow_up)

    assert resp.get_json()["care_tasks_suggested"] == 1
    descriptions = [t["description"] for t in fake_db.tables["care_tasks"]]
    assert descriptions.count("Repeat ECG in 6 hours") == 1
    assert len(descriptions) == 4


def test_rejected_task_can_be_suggested_again(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)
    for t in fake_db.tables["care_tasks"]:
        t["status"] = "rejected"

    resp = client.post("/api/update-record", json=FULL_NOTE)

    # Only suggested/accepted tasks block a repeat; a later note may re-raise a rejected one
    assert resp.get_json()["care_tasks_suggested"] == 3


def test_update_record_suggests_care_tasks_for_clinician_approval(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)

    tasks = fake_db.tables["care_tasks"]
    assert [(t["description"], t["category"]) for t in tasks] == [
        ("Continuous telemetry monitoring", "monitoring"),
        ("Prep for transthoracic echocardiogram", "prep"),
        ("Ask a friend", "other"),   # unknown categories fall back instead of failing the insert
    ]
    # Nothing the AI suggests is a real task until a clinician accepts it
    assert all(t["status"] == "suggested" and t["suggested_by"] == "ai" for t in tasks)


def test_update_record_updates_patient_acuity(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)

    patient = fake_db.tables["patients"][0]
    assert patient["acuity"] == "serious"
    assert patient["acuity_updated_at"] is not None


def test_update_record_ignores_invalid_acuity(client, fake_db):
    client.post("/api/update-record", json={**FULL_NOTE, "acuity": "pretty bad"})

    assert fake_db.tables["patients"][0]["acuity"] is None
    assert fake_db.tables["clinical_notes"][0]["structured_data"]["acuity"] is None


def test_update_record_keeps_note_and_reasoning_for_the_audit_trail(client, fake_db):
    client.post("/api/update-record", json=FULL_NOTE)

    note = fake_db.tables["clinical_notes"][0]
    assert note["raw_input"] == FULL_NOTE["raw_input"]
    assert note["structured_data"]["reasoning"] == FULL_NOTE["reasoning"]


def test_update_record_reports_when_ward_board_data_fails_after_note_is_saved(client, fake_db):
    fake_db.fail_tables.add("medication_orders")

    resp = client.post("/api/update-record", json=FULL_NOTE)

    assert resp.status_code == 500
    note_id = fake_db.tables["clinical_notes"][0]["id"]
    assert note_id in resp.get_json()["message"]


def test_server_prefers_the_secret_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_x")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_x")
    assert server.server_supabase_key() == "sb_secret_x"

    monkeypatch.delenv("SUPABASE_SECRET_KEY")
    assert server.server_supabase_key() == "sb_publishable_x"


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
