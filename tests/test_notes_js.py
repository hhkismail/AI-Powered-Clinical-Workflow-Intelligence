"""Tests for the clinical notes page's rendering (frontend/app.js), run in QuickJS."""

import json
import os

import pytest

quickjs = pytest.importorskip("quickjs")

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "app.js")

PATIENT = {
    "patient_id": "PT-30554", "name": "Rajesh Kumar", "age": 62, "allergies": ["Aspirin"],
    "active_prescriptions": ["Atorvastatin"], "medical_history": "Post-MI", "acuity": "serious",
    "bed": {"id": "RES-NEURO-01", "resource_name": "Observation Bed 01", "wing": "Observation Wing B"},
    "medication_orders": [{"drug": "Heparin", "dose": "5000 units", "route": "iv", "frequency": "continuous"}],
}

SUCCESS = {
    "status": "success", "system_alerts": None,
    "result": {
        "llm_reasoning": "AF with RVR needs a monitored bed; no conflict with the aspirin allergy.",
        "execution_results": {"alerts": [], "executed_actions": [
            {"tool": "update_record", "status": "success", "result": {
                "care_tasks_suggested": 2,
                "params": {"diagnoses": ["Atrial fibrillation"], "acuity": "serious",
                           "prescriptions": [{"drug": "Metoprolol", "dosage": "25mg", "route": "oral", "frequency": None}]}}},
            {"tool": "reserve_bed", "status": "success", "result": {
                "reservation_id": "RES-NEURO-01", "allocation": {"bed": "Observation Bed 01", "ward": "Observation Wing B"}}},
        ]},
    },
}


@pytest.fixture(scope="module")
def js():
    ctx = quickjs.Context()
    with open(APP_JS, encoding="utf-8") as f:
        ctx.eval(f.read())

    def call(fn, *args):
        return ctx.eval(f"({fn})(...{json.dumps(list(args))})")
    return call


def test_context_shows_allergy_bed_and_medications(js):
    html = js("renderContext", PATIENT)

    assert "Allergic to Aspirin" in html
    assert 'href="board.html#bed=RES-NEURO-01"' in html and "Observation Bed 01" in html
    assert "<b>IV</b> Heparin 5000 units" in html
    assert "Atorvastatin" in html and "acuity-serious" in html


def test_context_for_patient_without_record(js):
    html = js("renderContextMissing", "PT-NOPE")

    assert "No record for PT-NOPE" in html and "no history to check allergies against" in html


def test_successful_result_lists_what_was_done(js):
    html = js("renderResult", SUCCESS)

    assert "Note processed" in html
    assert "Record updated: 1 diagnosis, 1 prescription, acuity Serious" in html
    assert "2 next steps sent to the ward board for review" in html
    assert "Bed reserved: Observation Bed 01 (Observation Wing B)" in html
    assert "<td>Metoprolol</td><td>25mg</td><td>oral</td><td>–</td>" in html
    assert 'href="board.html#bed=RES-NEURO-01"' in html


def test_halted_result_says_nothing_changed(js):
    html = js("renderResult", {"status": "halted_for_clarification",
                               "system_alerts": [{"type": "Clinical Safety Halt", "message": "Aspirin allergy"}]})

    assert "Nothing was changed" in html and "Aspirin allergy" in html
    assert "What was done" not in html


def test_partial_result_shows_failures(js):
    partial = json.loads(json.dumps(SUCCESS))
    partial["status"] = "partial_success"
    partial["system_alerts"] = [{"type": "API Rejection", "message": "reserve_bed was rejected: No beds"}]
    partial["result"]["execution_results"]["executed_actions"].pop()

    html = js("renderResult", partial)

    assert "Some actions failed" in html
    assert '<span class="cross">✕</span><span>reserve_bed was rejected: No beds</span>' in html


def test_existing_bed_and_transfer_are_described(js):
    def bed_result(**extra):
        return {"tool": "reserve_bed", "result": {"reservation_id": "RES-ICU-01",
                                                  "allocation": {"bed": "Ventilator Bed 01", "ward": "West Wing"}, **extra}}

    assert "Already in Ventilator Bed 01" in js("describeAction", bed_result(already_assigned=True))
    assert "transferred from RES-NEURO-01" in js("describeAction", bed_result(transferred_from=["RES-NEURO-01"]))


def test_result_escapes_llm_text(js):
    evil = json.loads(json.dumps(SUCCESS))
    evil["result"]["llm_reasoning"] = "<script>x()</script>"
    evil["result"]["execution_results"]["executed_actions"][0]["result"]["params"]["diagnoses"] = ["<img src=x>"]

    html = js("renderResult", evil)

    assert "<script>" not in html and "<img" not in html


def test_queued_admission_is_pending_not_failed(js):
    queued = json.loads(json.dumps(SUCCESS))
    queued["result"]["execution_results"]["executed_actions"][1]["result"] = {
        "status": "queued", "request_id": "r1", "waiting_for": "icu", "position": 2}

    html = js("renderResult", queued)

    assert '<span class="pending">●</span><span>No ICU bed free: added to the waiting list (position 2)</span>' in html
    assert 'href="board.html#waiting=r1"' in html
    assert "Open on the ward board" not in html


def test_context_shows_waiting_for_a_bed(js):
    waiting = {**PATIENT, "bed": None, "waiting_for_bed": {"id": "r1", "ward_type": "icu"}}
    transfer = {**PATIENT, "waiting_for_bed": {"id": "r2", "ward_type": "icu"}}

    assert 'href="board.html#waiting=r1">Waiting for an ICU bed</a>' in js("renderContext", waiting)
    assert "Waiting for a transfer to an ICU bed" in js("renderContext", transfer)


def test_result_lists_stopped_and_proposed_medications(js):
    action = {"tool": "update_record", "result": {"params": {"diagnoses": [], "prescriptions": []},
              "medications_stopped": ["Metoprolol"], "stops_proposed": 1, "discontinue_not_found": ["Warfarin"]}}

    text = js("describeAction", action)

    assert "Stopped as the note says: Metoprolol" in text
    assert "1 medication stop proposed for a clinician to confirm" in text
    assert "Not on the ward orders, so not stopped: Warfarin" in text
