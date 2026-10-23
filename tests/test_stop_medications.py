"""Tests for stopping medications: explicit stops, AI-inferred proposals, and manual stops."""

import pytest

import server


@pytest.fixture
def client(fake_db, monkeypatch):
    monkeypatch.setattr(server, "supabase", fake_db)
    fake_db.tables["medication_orders"] = [
        {"id": "m-doxy", "patient_id": "PT-30554", "drug": "Doxycycline", "dose": "100mg", "route": "oral",
         "frequency": "daily", "status": "active", "source_note_id": None, "started_at": "2026-10-22T08:00:00Z",
         "ended_at": None, "stopped_by": None, "stop_reason": None, "allergy_warning": None},
        {"id": "m-meto", "patient_id": "PT-30554", "drug": "Metoprolol", "dose": "25mg", "route": "oral",
         "frequency": "twice daily", "status": "active", "source_note_id": None, "started_at": "2026-10-22T08:00:00Z",
         "ended_at": None, "stopped_by": None, "stop_reason": None, "allergy_warning": None},
    ]
    fake_db.tables["care_tasks"] = []
    return server.app.test_client()


def note(client, raw_input, discontinue, prescriptions=None):
    return client.post("/api/update-record", json={
        "patient_id": "PT-30554", "diagnoses": [], "prescriptions": prescriptions or [], "next_steps": [],
        "raw_input": raw_input, "discontinue": discontinue, "recorded_by": "DR-7742"}).get_json()


def order(fake_db, order_id):
    return next(o for o in fake_db.tables["medication_orders"] if o["id"] == order_id)


def stop_proposals(fake_db):
    return [t for t in fake_db.tables["care_tasks"] if t.get("proposed_action") == "stop_medication"]


# ---------- From a clinical note ----------

def test_explicit_stop_in_the_note_is_applied(client, fake_db):
    body = note(client, "Rate not controlled. Stop metoprolol. Start diltiazem 60mg orally three times a day.",
                [{"drug": "Metoprolol", "reason": "Rate not controlled", "explicit": True}])

    assert body["medications_stopped"] == ["Metoprolol"]
    m = order(fake_db, "m-meto")
    assert (m["status"], m["stopped_by"], m["stop_reason"]) == ("stopped", "DR-7742", "Rate not controlled")
    assert m["ended_at"] is not None
    assert stop_proposals(fake_db) == []


def test_inferred_stop_is_only_proposed(client, fake_db):
    body = note(client, "Deteriorating despite doxycycline. Start meropenem 1g IV every 8 hours.",
                [{"drug": "Doxycycline", "reason": "Treatment failure; replaced by meropenem", "explicit": False}])

    assert body["medications_stopped"] == [] and body["stops_proposed"] == 1
    assert order(fake_db, "m-doxy")["status"] == "active"
    [task] = stop_proposals(fake_db)
    assert task["status"] == "suggested" and task["medication_order_id"] == "m-doxy"
    assert task["description"] == "Stop Doxycycline? Treatment failure; replaced by meropenem"


def test_llm_claiming_explicit_without_the_words_in_the_note_is_downgraded(client, fake_db):
    # The safety check: the note never says to stop doxycycline, so it can't be stopped as an order
    body = note(client, "Deteriorating despite doxycycline. Start meropenem 1g IV every 8 hours.",
                [{"drug": "Doxycycline", "reason": "Replaced", "explicit": True}])

    assert body["medications_stopped"] == [] and body["stops_proposed"] == 1
    assert order(fake_db, "m-doxy")["status"] == "active"


def test_stop_word_must_be_in_the_same_sentence_as_the_drug(client, fake_db):
    body = note(client, "Continue doxycycline. Stop the IV fluids.",
                [{"drug": "Doxycycline", "reason": "?", "explicit": True}])

    assert body["medications_stopped"] == []
    assert order(fake_db, "m-doxy")["status"] == "active"


def test_unknown_drug_is_reported_not_invented(client, fake_db):
    body = note(client, "Stop warfarin.", [{"drug": "Warfarin", "reason": "Bleeding", "explicit": True}])

    assert body["discontinue_not_found"] == ["Warfarin"]
    assert stop_proposals(fake_db) == []


def test_repeated_note_does_not_propose_the_same_stop_twice(client, fake_db):
    item = [{"drug": "Doxycycline", "reason": "Replaced", "explicit": False}]
    note(client, "Despite doxycycline, start meropenem.", item)
    body = note(client, "Despite doxycycline, start meropenem.", item)

    assert body["stops_proposed"] == 0 and len(stop_proposals(fake_db)) == 1


def test_dose_change_stops_the_old_order_and_keeps_the_new_one(client, fake_db):
    body = note(client, "Stop metoprolol 25mg; start metoprolol 50mg twice daily.",
                [{"drug": "Metoprolol", "dose": "25mg", "reason": "Dose increase", "explicit": True}],
                prescriptions=[{"drug": "Metoprolol", "dosage": "50mg", "route": "oral", "frequency": "twice daily"}])

    assert body["medications_stopped"] == ["Metoprolol"]
    metoprolol = [(o["dose"], o["status"]) for o in fake_db.tables["medication_orders"] if o["drug"] == "Metoprolol"]
    assert sorted(metoprolol) == [("25mg", "stopped"), ("50mg", "active")]


@pytest.mark.parametrize("sentence, expected", [
    ("Stop metoprolol.", True),
    ("Metoprolol discontinued due to bradycardia", True),
    ("Hold metoprolol tonight", True),
    ("Continue metoprolol", False),
    ("Metoprolol 25mg. Stop the fluids", False),
    ("Stop metoprololX", False),
])
def test_note_explicitly_stops(sentence, expected):
    assert server.note_explicitly_stops(sentence, "Metoprolol") is expected


# ---------- Clinician decisions ----------

def propose_doxy_stop(client, fake_db):
    note(client, "Despite doxycycline, start meropenem.", [{"drug": "Doxycycline", "reason": "Replaced", "explicit": False}])
    return stop_proposals(fake_db)[0]["id"]


def test_accepting_a_stop_proposal_stops_the_medication(client, fake_db):
    task_id = propose_doxy_stop(client, fake_db)

    body = client.post(f"/api/tasks/{task_id}/decision", json={"decision": "accept", "clinician_id": "DR-9"}).get_json()

    assert body["medication_stopped"] == "Doxycycline"
    assert (order(fake_db, "m-doxy")["status"], order(fake_db, "m-doxy")["stopped_by"]) == ("stopped", "DR-9")
    assert body["task"]["status"] == "done"


def test_rejecting_a_stop_proposal_keeps_the_medication(client, fake_db):
    task_id = propose_doxy_stop(client, fake_db)

    client.post(f"/api/tasks/{task_id}/decision", json={"decision": "reject", "clinician_id": "DR-9"})

    assert order(fake_db, "m-doxy")["status"] == "active"


def test_manual_stop_from_the_board(client, fake_db):
    task_id = propose_doxy_stop(client, fake_db)

    first = client.post("/api/medications/m-doxy/stop", json={"clinician_id": "DR-9", "reason": "Course complete"})
    second = client.post("/api/medications/m-doxy/stop", json={"clinician_id": "DR-9"})

    assert (first.status_code, second.status_code) == (200, 409)
    m = order(fake_db, "m-doxy")
    assert (m["status"], m["stopped_by"], m["stop_reason"]) == ("stopped", "DR-9", "Course complete")
    # The open "Stop doxycycline?" proposal is now moot
    assert next(t for t in fake_db.tables["care_tasks"] if t["id"] == task_id)["status"] == "cancelled"


def test_manual_stop_needs_a_clinician_and_a_real_order(client):
    assert client.post("/api/medications/m-doxy/stop", json={}).status_code == 400
    assert client.post("/api/medications/m-nope/stop", json={"clinician_id": "DR-9"}).status_code == 404
