"""Tests for the bed waiting list: queuing, assigning, removing, and how the board shows it."""

import pytest

import server


@pytest.fixture
def client(fake_db, monkeypatch):
    monkeypatch.setattr(server, "supabase", fake_db)
    fake_db.tables["patients"] += [
        {"patient_id": "PT-55108", "name": "Fatimah Zahra", "age": 71, "allergies": ["Ibuprofen"],
         "active_prescriptions": [], "medical_history": None, "acuity": "critical", "acuity_updated_at": None},
        {"patient_id": "PT-20221", "name": "Siti Aminah", "age": 8, "allergies": [],
         "active_prescriptions": [], "medical_history": None, "acuity": "stable", "acuity_updated_at": None},
    ]
    return server.app.test_client()


def bed(fake_db, bed_id):
    return next(b for b in fake_db.tables["hospital_resources"] if b["id"] == bed_id)


def fill(fake_db, *bed_ids):
    for bed_id in bed_ids:
        bed(fake_db, bed_id).update(status="maintenance")


def reserve(client, patient_id, ward_type, **extra):
    return client.post("/api/reserve-bed", json={"patient_id": patient_id, "ward_type": ward_type, **extra})


def requests_for(fake_db, patient_id):
    return [r for r in fake_db.tables.get("bed_requests", []) if r["patient_id"] == patient_id]


# ---------- Queuing ----------

def test_full_ward_queues_the_patient_instead_of_rejecting(client, fake_db):
    fill(fake_db, "RES-ICU-01")

    resp = reserve(client, "PT-55108", "icu", department="Critical Care", clinical_reason="Ventilated")

    assert resp.status_code == 202
    body = resp.get_json()
    assert (body["status"], body["waiting_for"], body["position"]) == ("queued", "icu", 1)
    assert "added to the waiting list" in body["message"]
    [req] = requests_for(fake_db, "PT-55108")
    assert (req["status"], req["resource_type"], req["clinical_reason"]) == ("waiting", "ICU_BED", "Ventilated")


def test_repeated_note_does_not_queue_twice(client, fake_db):
    fill(fake_db, "RES-ICU-01")

    first = reserve(client, "PT-55108", "icu").get_json()
    second = reserve(client, "PT-55108", "icu").get_json()

    assert first["request_id"] == second["request_id"]
    assert len(requests_for(fake_db, "PT-55108")) == 1


def test_queue_position_counts_earlier_requests(client, fake_db):
    fill(fake_db, "RES-ICU-01")

    reserve(client, "PT-55108", "icu")
    second = reserve(client, "PT-20221", "icu").get_json()

    assert second["position"] == 2


def test_patient_needing_a_transfer_keeps_their_bed_while_waiting(client, fake_db):
    reserve(client, "PT-30554", "observation")           # takes RES-NEURO-01
    fill(fake_db, "RES-ICU-01")

    body = reserve(client, "PT-30554", "icu").get_json()

    assert body["status"] == "queued" and body["current_bed"] == "RES-NEURO-01"
    assert bed(fake_db, "RES-NEURO-01")["assigned_to_patient"] == "PT-30554"


def test_new_note_that_finds_a_bed_closes_the_waiting_request(client, fake_db):
    fill(fake_db, "RES-ICU-01")
    reserve(client, "PT-55108", "icu")
    bed(fake_db, "RES-ICU-01").update(status="available")

    body = reserve(client, "PT-55108", "icu").get_json()

    assert body["reservation_id"] == "RES-ICU-01"
    [req] = requests_for(fake_db, "PT-55108")
    assert (req["status"], req["assigned_bed_id"], req["resolved_by"]) == ("assigned", "RES-ICU-01", "system")


# ---------- Assigning and removing ----------

def queued_request(client, fake_db, patient_id="PT-55108", ward_type="icu"):
    fill(fake_db, "RES-ICU-01")
    return reserve(client, patient_id, ward_type).get_json()["request_id"]


def test_assign_gives_the_best_free_bed_once_one_is_available(client, fake_db):
    request_id = queued_request(client, fake_db)
    bed(fake_db, "RES-ICU-01").update(status="available")

    resp = client.post(f"/api/bed-requests/{request_id}/assign", json={"clinician_id": "DR-7742"})

    assert resp.status_code == 200 and resp.get_json()["reservation_id"] == "RES-ICU-01"
    assert bed(fake_db, "RES-ICU-01")["assigned_to_patient"] == "PT-55108"
    [req] = requests_for(fake_db, "PT-55108")
    assert (req["status"], req["resolved_by"], req["assigned_bed_id"]) == ("assigned", "DR-7742", "RES-ICU-01")


def test_assign_with_no_free_bed_keeps_the_patient_waiting(client, fake_db):
    request_id = queued_request(client, fake_db)

    resp = client.post(f"/api/bed-requests/{request_id}/assign", json={"clinician_id": "DR-7742"})

    assert resp.status_code == 409 and resp.get_json()["error_code"] == "NO_BEDS_AVAILABLE"
    assert requests_for(fake_db, "PT-55108")[0]["status"] == "waiting"


def test_assign_a_specific_bed_must_be_free_and_the_right_type(client, fake_db):
    request_id = queued_request(client, fake_db)

    wrong_type = client.post(f"/api/bed-requests/{request_id}/assign",
                             json={"clinician_id": "DR-7742", "bed_id": "RES-NEURO-01"})

    assert wrong_type.status_code == 409 and wrong_type.get_json()["error_code"] == "BED_NOT_SUITABLE"


def test_assigning_a_transfer_releases_the_old_bed_for_cleaning(client, fake_db):
    reserve(client, "PT-30554", "observation")
    request_id = queued_request(client, fake_db, "PT-30554", "icu")
    bed(fake_db, "RES-ICU-01").update(status="available")

    body = client.post(f"/api/bed-requests/{request_id}/assign", json={"clinician_id": "DR-7742"}).get_json()

    assert body["transferred_from"] == ["RES-NEURO-01"]
    assert (bed(fake_db, "RES-NEURO-01")["status"], bed(fake_db, "RES-NEURO-01")["assigned_to_patient"]) == ("cleaning", None)


def test_remove_from_waiting_list(client, fake_db):
    request_id = queued_request(client, fake_db)

    resp = client.post(f"/api/bed-requests/{request_id}/cancel", json={"clinician_id": "DR-7742"})
    again = client.post(f"/api/bed-requests/{request_id}/cancel", json={"clinician_id": "DR-7742"})

    assert (resp.status_code, again.status_code) == (200, 409)
    assert requests_for(fake_db, "PT-55108")[0]["status"] == "cancelled"


@pytest.mark.parametrize("path", ["assign", "cancel"])
def test_waiting_list_actions_need_a_clinician_and_a_real_request(client, fake_db, path):
    request_id = queued_request(client, fake_db)

    assert client.post(f"/api/bed-requests/{request_id}/{path}", json={}).status_code == 400
    assert client.post(f"/api/bed-requests/nope/{path}", json={"clinician_id": "DR-1"}).status_code == 404


def test_discharge_cancels_a_pending_transfer_request(client, fake_db):
    reserve(client, "PT-30554", "observation")
    queued_request(client, fake_db, "PT-30554", "icu")

    client.post("/api/beds/RES-NEURO-01/discharge", json={"clinician_id": "DR-7742"})

    assert requests_for(fake_db, "PT-30554")[0]["status"] == "cancelled"


# ---------- How it shows up ----------

def test_board_lists_waiting_patients_sickest_first_with_their_details(client, fake_db):
    fill(fake_db, "RES-ICU-01")
    reserve(client, "PT-20221", "icu")      # stable, asked first
    reserve(client, "PT-55108", "icu")      # critical, asked second

    board = client.get("/api/ward-board").get_json()

    assert [w["patient"]["name"] for w in board["waiting"]] == ["Fatimah Zahra", "Siti Aminah"]
    assert board["summary"]["waiting"] == 2
    assert board["summary"]["critical_patients"] == 1     # a waiting patient still counts
    assert board["waiting"][0]["free_matching_beds"] == 0
    assert board["waiting"][0]["patient"]["allergies"] == ["Ibuprofen"]


def test_waiting_transfer_patient_is_counted_once(client, fake_db):
    reserve(client, "PT-55108", "general")      # Fatimah in a general bed...
    fill(fake_db, "RES-ICU-01")
    reserve(client, "PT-55108", "icu")           # ...and waiting for ICU

    board = client.get("/api/ward-board").get_json()

    assert board["summary"]["critical_patients"] == 1
    assert board["waiting"][0]["current_bed"]["id"] == "RES-NEURO-01"


def test_patient_record_says_when_they_are_waiting(client, fake_db):
    queued_request(client, fake_db)

    p = client.get("/api/patient/PT-55108").get_json()

    assert p["waiting_for_bed"]["ward_type"] == "icu"
