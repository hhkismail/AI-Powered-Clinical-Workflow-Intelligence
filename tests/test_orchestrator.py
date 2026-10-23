"""Tests for the AI orchestrator (Ophia/main.py). The LLM and hospital APIs are mocked."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main

NOTE_REQUEST = {
    "metadata": {"doctor_id": "DR-7742", "patient_id": "PT-30554", "department": "Cardiology",
                 "timestamp": "2026-10-23T08:00:00Z", "priority": "high"},
    "payload": {"input_methods_used": ["text"], "raw_text": "Admit to observation. Metoprolol 25mg PO."},
}

UPDATE = {"tool": "update_record", "params": {"diagnoses": ["AF"],
          "prescriptions": [{"drug": "Metoprolol", "dosage": "25mg", "route": "oral"}]}}
RESERVE = {"tool": "reserve_bed", "params": {"ward_type": "observation", "clinical_reason": "AF with RVR"}}


@pytest.fixture
def mock_apis(monkeypatch):
    """Patch the LLM, patient history and hospital APIs. Returns the calls made and the knobs to set."""
    state = {"llm": {"status": "success", "reasoning": "ok", "actions": []}, "rejected": set(),
             "broken": set(), "calls": [], "prompts": []}

    async def fake_llm(prompt):
        state["prompts"].append(prompt)
        return state["llm"]

    async def fake_history(patient_id):
        return "PATIENT HISTORY (CRITICAL CONTEXT):\n- Known Allergies: Aspirin"

    def fake_mock_api(endpoint, data):
        state["calls"].append(endpoint)
        if endpoint in state["rejected"]:
            raise main.APIRejection("No beds are available for the requested ward type.")
        if endpoint in state["broken"]:
            raise Exception("500 Server Error")
        return {"status": "success", "endpoint": endpoint}

    monkeypatch.setattr(main, "call_llm", fake_llm)
    monkeypatch.setattr(main, "fetch_patient_history", fake_history)
    monkeypatch.setattr(main, "call_mock_api", fake_mock_api)
    return state


@pytest.fixture
def client():
    return TestClient(main.app)


def test_all_actions_succeed(client, mock_apis):
    mock_apis["llm"]["actions"] = [UPDATE, RESERVE]

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert body["status"] == "success"
    assert body["system_alerts"] is None
    assert [a["tool"] for a in body["result"]["execution_results"]["executed_actions"]] == ["update_record", "reserve_bed"]


def test_rejected_action_keeps_earlier_results_and_reports_partial_success(client, mock_apis):
    mock_apis["llm"]["actions"] = [UPDATE, RESERVE]
    mock_apis["rejected"].add("/api/reserve-bed")

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert body["status"] == "partial_success"
    # The record update already happened, so it must still be reported
    assert [a["tool"] for a in body["result"]["execution_results"]["executed_actions"]] == ["update_record"]
    assert body["system_alerts"][0]["type"] == "API Rejection"
    assert "No beds" in body["system_alerts"][0]["message"]


def test_actions_after_a_failure_still_run(client, mock_apis):
    mock_apis["llm"]["actions"] = [RESERVE, UPDATE]
    mock_apis["broken"].add("/api/reserve-bed")

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert mock_apis["calls"] == ["/api/reserve-bed", "/api/update-record"]
    assert body["status"] == "partial_success"
    assert body["system_alerts"][0]["type"] == "Execution Error"


def test_every_action_failing_is_a_halt(client, mock_apis):
    mock_apis["llm"]["actions"] = [RESERVE]
    mock_apis["rejected"].add("/api/reserve-bed")

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert body["status"] == "halted_for_clarification"
    assert body["system_alerts"][0]["type"] == "API Rejection"


def test_unknown_tool_is_reported_not_executed(client, mock_apis):
    mock_apis["llm"]["actions"] = [{"tool": "discharge_patient", "params": {}}]

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert mock_apis["calls"] == []
    assert body["system_alerts"][0]["type"] == "Unknown Tool"


def test_llm_safety_halt_executes_nothing(client, mock_apis):
    mock_apis["llm"] = {"status": "halted_for_clarification",
                        "system_alerts": [{"type": "Allergy Conflict", "message": "Aspirin allergy"}],
                        "actions": [UPDATE]}

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert body["status"] == "halted_for_clarification"
    assert body["system_alerts"] == [{"type": "Allergy Conflict", "message": "Aspirin allergy"}]
    assert mock_apis["calls"] == []


def test_prompt_includes_history_and_note(client, mock_apis):
    client.post("/api/process-note", json=NOTE_REQUEST)

    prompt = mock_apis["prompts"][0]
    assert "PATIENT ID: PT-30554" in prompt
    assert "ENCOUNTER DATE: 2026-10-23" in prompt
    assert "Known Allergies: Aspirin" in prompt
    assert "Metoprolol 25mg PO" in prompt


def test_update_record_receives_ward_board_fields_and_audit_trail(client, monkeypatch, mock_apis):
    sent = {}
    monkeypatch.setattr(main, "call_mock_api", lambda endpoint, data: sent.update({endpoint: data}) or {"status": "success"})
    mock_apis["llm"] = {"status": "success", "reasoning": "AF needs monitored admission", "actions": [{
        "tool": "update_record", "params": {
            "diagnoses": ["AF"], "prescriptions": [], "acuity": "serious",
            "next_steps": [{"description": "Telemetry", "category": "monitoring"}],
            # The LLM can't overwrite the audit trail with its own params
            "raw_input": "forged", "reasoning": "forged"}}]}

    client.post("/api/process-note", json=NOTE_REQUEST)

    data = sent["/api/update-record"]
    assert data["acuity"] == "serious"
    assert data["next_steps"] == [{"description": "Telemetry", "category": "monitoring"}]
    assert data["raw_input"] == NOTE_REQUEST["payload"]["raw_text"]
    assert data["reasoning"] == "AF needs monitored admission"


def test_reserve_bed_receives_the_notes_department(client, monkeypatch, mock_apis):
    sent = {}
    monkeypatch.setattr(main, "call_mock_api", lambda endpoint, data: sent.update({endpoint: data}) or {"status": "success"})
    mock_apis["llm"]["actions"] = [RESERVE]

    client.post("/api/process-note", json=NOTE_REQUEST)

    assert sent["/api/reserve-bed"]["department"] == "Cardiology"


def test_missing_patient_id_is_rejected_by_validation(client, mock_apis):
    bad = {**NOTE_REQUEST, "metadata": {k: v for k, v in NOTE_REQUEST["metadata"].items() if k != "patient_id"}}

    assert client.post("/api/process-note", json=bad).status_code == 422
    assert mock_apis["prompts"] == []


def test_missing_api_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    result = asyncio.run(main.call_llm("note"))

    assert result["status"] == "halted_for_clarification"
    assert result["system_alerts"][0]["type"] == "Configuration Error"


def test_legacy_key_name_still_works(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("ZAI_API_KEY", "legacy-key")

    assert main.get_groq_api_key() == "legacy-key"
