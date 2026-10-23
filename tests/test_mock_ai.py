"""Tests for mock AI mode (Ophia/mock_llm.py and MOCK_AI in both services)."""

import asyncio
import io
import os
import sys

import httpx
import pytest

import ingestion
import main
import mock_llm

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals"))
import run_safety_eval as safety_eval  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "samples")


def plan_for(note, allergies="None documented", ward_orders="None"):
    history = (f"PATIENT HISTORY (CRITICAL CONTEXT):\n- Known Allergies: {allergies}\n- Regular Medications: None\n"
               f"- Current Ward Orders: {ward_orders}\n- Medical History: None")
    return mock_llm.plan(main.build_llm_prompt("PT-30554", "2026-10-23", "General", history, note))


def sample(name):
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def mock_ai(monkeypatch):
    monkeypatch.setenv("MOCK_AI", "1")


@pytest.mark.parametrize("case", safety_eval.CASES, ids=lambda c: c["name"])
def test_mock_passes_the_safety_eval_cases(case):
    """The same checks the live LLM is held to (evals/run_safety_eval.py)."""
    response = plan_for(case["note"], case["allergies"], case.get("ward_orders", "None"))

    assert safety_eval.check(case, response) == []


def test_handwritten_sample_plans_a_general_bed_with_its_steps():
    response = plan_for(sample("handwritten_note.txt"))
    record = response["actions"][0]["params"]

    assert response["actions"][1] == {"tool": "reserve_bed", "params": {
        "patient_id": "PT-30554", "ward_type": "general", "clinical_reason": "Closed fracture R tibial shaft"}}
    assert record["prescriptions"] == [{"drug": "Morphine", "dosage": "5mg", "route": "IV", "frequency": "every 4h PRN"}]
    assert record["acuity"] == "serious"
    assert [(s["description"], s["category"]) for s in record["next_steps"]] == [
        ("Ortho consult", "consult"), ("Prep for ORIF tomorrow", "prep"), ("Keep NBM from midnight", "prep")]


def test_voice_sample_halts_for_a_penicillin_allergy():
    response = plan_for(sample("voice_memo.txt"), "Penicillin, Sulfa Drugs")

    assert response["status"] == "halted_for_clarification"
    assert response["system_alerts"][0]["message"] == "Amoxicillin is a penicillin and the patient is allergic to Penicillin."


def test_follow_up_is_booked_in_the_named_clinic():
    response = plan_for("Mild seasonal allergic rhinitis. Prescribed Cetirizine 10mg orally once daily. "
                        "Review in 4 weeks in General clinic. Discharge home.")

    assert response["actions"][1] == {"tool": "schedule_appointment", "params": {
        "patient_id": "PT-30554", "department": "General", "timeframe_days": 28,
        "reason": "Follow-up review requested in the note"}}
    assert response["actions"][0]["params"]["next_steps"] == []


def test_unknown_drugs_and_diagnoses_are_left_out_not_guessed():
    record = plan_for("Feeling unwell. Start Zyntrafex 20mg daily.")["actions"][0]["params"]

    assert record["prescriptions"] == []
    assert record["diagnoses"] == ["See clinical note"]


def test_call_llm_uses_the_rules_and_never_the_network(mock_ai, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: pytest.fail("mock mode called the network"))

    response = asyncio.run(main.call_llm(main.build_llm_prompt(
        "PT-1", "2026-10-23", "General", "- Known Allergies: None documented", "Admit to observation ward.")))

    assert response["reasoning"].startswith("Mock AI mode (no LLM was called)")
    assert response["actions"][1]["params"]["ward_type"] == "observation"


def test_responses_say_which_ai_planned_them(monkeypatch):
    assert main.ProcessNoteResponse(status="success").ai == "llm"
    monkeypatch.setenv("MOCK_AI", "1")
    assert main.ProcessNoteResponse(status="success").ai == "mock"


@pytest.fixture
def forwarded(monkeypatch):
    sent = []

    class Reply:
        status_code = 200

        def json(self):
            return {"status": "success"}

    monkeypatch.setattr(ingestion.req, "post", lambda url, json, timeout: sent.append(json) or Reply())
    monkeypatch.setattr(ingestion, "GROQ_API_KEY", None)
    return sent


@pytest.mark.parametrize("name, method", [("handwritten_note.jpg", "image"), ("voice_memo.wav", "audio")])
def test_bundled_samples_are_read_from_their_transcripts(mock_ai, forwarded, name, method):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        content = f.read()

    resp = ingestion.app.test_client().post("/api/process-note", data={
        "patient_id": "PT-10934", "doctor_id": "D", "file": (io.BytesIO(content), "upload" + os.path.splitext(name)[1])})

    assert resp.status_code == 200
    assert forwarded[0]["payload"] == {"input_methods_used": [method],
                                       "raw_text": sample(os.path.splitext(name)[0] + ".txt").strip()}


def test_other_uploads_are_refused_in_mock_mode(mock_ai, forwarded):
    resp = ingestion.app.test_client().post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "file": (io.BytesIO(b"\x89PNG other"), "note.png")})

    assert resp.status_code == 400
    assert "only the sample files in docs/samples can be read" in resp.get_json()["error"]
    assert forwarded == []
