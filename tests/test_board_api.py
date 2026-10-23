"""Tests for the ward board endpoints in server.py."""

import pytest

import server


@pytest.fixture
def board_db(fake_db):
    """Rajesh in an observation bed with medications and tasks; Siti in ICU; one bed being cleaned."""
    beds = {b["id"]: b for b in fake_db.tables["hospital_resources"]}
    beds["RES-NEURO-01"].update(status="occupied", assigned_to_patient="PT-30554")
    beds["RES-ICU-01"].update(status="occupied", assigned_to_patient="PT-20221")
    beds["RES-CARD-01"].update(status="cleaning", assigned_to_patient=None)
    fake_db.tables["patients"] = [
        {"patient_id": "PT-30554", "name": "Rajesh Kumar", "age": 62, "allergies": ["Aspirin"],
         "active_prescriptions": ["Atorvastatin"], "medical_history": "Post-MI", "acuity": "serious", "acuity_updated_at": "2026-10-23T08:00:00Z"},
        {"patient_id": "PT-20221", "name": "Siti Aminah", "age": 8, "allergies": ["Latex"],
         "active_prescriptions": [], "medical_history": "Asthma", "acuity": "critical", "acuity_updated_at": "2026-10-23T09:00:00Z"},
        {"patient_id": "PT-40992", "name": "Michael Wong", "age": 29, "allergies": [],
         "active_prescriptions": [], "medical_history": None, "acuity": "stable", "acuity_updated_at": None},
    ]
    fake_db.tables["medication_orders"] = [
        {"id": "m1", "patient_id": "PT-30554", "drug": "Metoprolol", "dose": "25mg", "route": "oral",
         "frequency": "BD", "status": "active", "started_at": "2026-10-23T08:00:00Z"},
        {"id": "m2", "patient_id": "PT-30554", "drug": "Heparin", "dose": "5000 units", "route": "iv",
         "frequency": "continuous", "status": "active", "started_at": "2026-10-23T08:05:00Z"},
        {"id": "m3", "patient_id": "PT-30554", "drug": "Amiodarone", "dose": "200mg", "route": "oral",
         "frequency": None, "status": "stopped", "started_at": "2026-10-22T08:00:00Z"},
    ]
    fake_db.tables["care_tasks"] = [
        {"id": "t1", "patient_id": "PT-30554", "description": "Telemetry", "category": "monitoring",
         "status": "accepted", "suggested_by": "ai", "created_at": "2026-10-23T08:00:00Z",
         "decided_at": "2026-10-23T08:10:00Z", "decided_by": "DR-7742"},
        {"id": "t2", "patient_id": "PT-30554", "description": "Prep for echo", "category": "prep",
         "status": "suggested", "suggested_by": "ai", "created_at": "2026-10-23T08:01:00Z",
         "decided_at": None, "decided_by": None},
        {"id": "t3", "patient_id": "PT-30554", "description": "Old task", "category": "other",
         "status": "done", "suggested_by": "ai", "created_at": "2026-10-22T08:00:00Z",
         "decided_at": None, "decided_by": None},
        {"id": "t4", "patient_id": "PT-20221", "description": "Repeat blood gas", "category": "lab",
         "status": "suggested", "suggested_by": "ai", "created_at": "2026-10-23T09:00:00Z",
         "decided_at": None, "decided_by": None},
    ]
    return fake_db


@pytest.fixture
def client(board_db, monkeypatch):
    monkeypatch.setattr(server, "supabase", board_db)
    return server.app.test_client()


def board_bed(board, bed_id):
    return next(b for w in board["wards"] for b in w["beds"] if b["id"] == bed_id)


# ---------- GET /api/ward-board ----------

def test_board_groups_beds_by_wing(client):
    board = client.get("/api/ward-board").get_json()

    assert [w["wing"] for w in board["wards"]] == ["Diagnostic Block", "Observation Wing B", "West Wing", "Wing A"]
    assert board_bed(board, "RES-NEURO-01")["name"] == "Observation Bed 01"


def test_board_shows_patient_with_active_medications_iv_first(client):
    patient = board_bed(client.get("/api/ward-board").get_json(), "RES-NEURO-01")["patient"]

    assert (patient["name"], patient["acuity"], patient["allergies"]) == ("Rajesh Kumar", "serious", ["Aspirin"])
    # Stopped orders are hidden; the IV line comes first
    assert [m["drug"] for m in patient["medications"]] == ["Heparin", "Metoprolol"]


def test_board_shows_open_tasks_with_suggestions_first(client):
    patient = board_bed(client.get("/api/ward-board").get_json(), "RES-NEURO-01")["patient"]

    assert [(t["description"], t["status"]) for t in patient["tasks"]] == [
        ("Prep for echo", "suggested"), ("Telemetry", "accepted")]   # done tasks are hidden


def test_board_empty_beds_have_no_patient(client):
    board = client.get("/api/ward-board").get_json()

    assert board_bed(board, "RES-CARD-01")["patient"] is None
    assert board_bed(board, "RES-CARD-01")["status"] == "cleaning"


def test_board_summary(client):
    summary = client.get("/api/ward-board").get_json()["summary"]

    assert summary["beds"] == {"available": 1, "occupied": 2, "cleaning": 1, "maintenance": 0}
    assert summary["critical_patients"] == 1
    assert summary["pending_suggestions"] == 2


def test_board_with_no_patients(client, board_db):
    for b in board_db.tables["hospital_resources"]:
        b.update(status="available", assigned_to_patient=None)

    board = client.get("/api/ward-board").get_json()

    assert board["summary"]["pending_suggestions"] == 0
    assert all(b["patient"] is None for w in board["wards"] for b in w["beds"])


def test_board_reports_database_failure(client, board_db):
    board_db.fail_tables.add("care_tasks")

    resp = client.get("/api/ward-board")

    assert resp.status_code == 500
    assert resp.get_json()["error_code"] == "SUPABASE_QUERY_FAILED"


# ---------- GET /api/patient/<id> (patient context on the notes page) ----------

def test_patient_includes_acuity_bed_and_active_medications(client):
    p = client.get("/api/patient/PT-30554").get_json()

    assert (p["name"], p["acuity"], p["allergies"]) == ("Rajesh Kumar", "serious", ["Aspirin"])
    assert p["bed"] == {"id": "RES-NEURO-01", "resource_name": "Observation Bed 01", "wing": "Observation Wing B"}
    assert [m["drug"] for m in p["medication_orders"]] == ["Metoprolol", "Heparin"]   # stopped orders excluded


def test_patient_without_bed_or_orders(client):
    p = client.get("/api/patient/PT-40992").get_json()

    assert p["bed"] is None and p["medication_orders"] == []


def test_unknown_patient_is_404(client):
    assert client.get("/api/patient/PT-NOPE").status_code == 404


# ---------- POST /api/tasks/<id>/decision ----------

def task(board_db, task_id):
    return next(t for t in board_db.tables["care_tasks"] if t["id"] == task_id)


@pytest.mark.parametrize("decision, new_status", [("accept", "accepted"), ("reject", "rejected")])
def test_clinician_decides_on_a_suggestion(client, board_db, decision, new_status):
    resp = client.post("/api/tasks/t2/decision", json={"decision": decision, "clinician_id": "DR-7742"})

    assert resp.status_code == 200
    t = task(board_db, "t2")
    assert (t["status"], t["decided_by"]) == (new_status, "DR-7742")
    assert t["decided_at"] is not None


def test_accepted_task_can_be_completed(client, board_db):
    resp = client.post("/api/tasks/t1/decision", json={"decision": "done", "clinician_id": "RN-0042"})

    assert resp.status_code == 200
    assert task(board_db, "t1")["status"] == "done"
    assert task(board_db, "t1")["completed_at"] is not None
    assert task(board_db, "t1")["decided_by"] == "DR-7742"   # completing doesn't overwrite who accepted it


@pytest.mark.parametrize("task_id, decision", [
    ("t2", "done"),     # can't complete a task nobody accepted
    ("t1", "accept"),   # already accepted
    ("t3", "reject"),   # already done
])
def test_invalid_transitions_are_refused(client, board_db, task_id, decision):
    before = task(board_db, task_id)["status"]

    resp = client.post(f"/api/tasks/{task_id}/decision", json={"decision": decision, "clinician_id": "DR-7742"})

    assert resp.status_code == 409
    assert resp.get_json()["error_code"] == "INVALID_TRANSITION"
    assert task(board_db, task_id)["status"] == before


def test_second_decision_on_the_same_suggestion_loses(client, board_db):
    first = client.post("/api/tasks/t2/decision", json={"decision": "accept", "clinician_id": "DR-1"})
    second = client.post("/api/tasks/t2/decision", json={"decision": "reject", "clinician_id": "DR-2"})

    assert (first.status_code, second.status_code) == (200, 409)
    assert (task(board_db, "t2")["status"], task(board_db, "t2")["decided_by"]) == ("accepted", "DR-1")


def test_decision_requires_clinician_and_valid_decision(client):
    assert client.post("/api/tasks/t2/decision", json={"decision": "accept"}).status_code == 400
    assert client.post("/api/tasks/t2/decision", json={"decision": "maybe", "clinician_id": "DR-1"}).status_code == 400


def test_unknown_task_is_404(client):
    resp = client.post("/api/tasks/nope/decision", json={"decision": "accept", "clinician_id": "DR-1"})

    assert resp.status_code == 404


# ---------- POST /api/beds/<id>/mark-clean ----------

def test_cleaned_bed_becomes_available(client, board_db):
    resp = client.post("/api/beds/RES-CARD-01/mark-clean")

    assert resp.status_code == 200
    assert next(b for b in board_db.tables["hospital_resources"] if b["id"] == "RES-CARD-01")["status"] == "available"


def test_only_beds_being_cleaned_can_be_marked_clean(client):
    resp = client.post("/api/beds/RES-NEURO-01/mark-clean")   # occupied

    assert resp.status_code == 409
    assert client.post("/api/beds/RES-NOPE/mark-clean").status_code == 404
