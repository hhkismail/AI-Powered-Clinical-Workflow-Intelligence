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


# ---------- Patient history: the allergy check must never be skipped silently ----------

def test_note_is_halted_when_patient_history_cannot_be_checked(client, monkeypatch, mock_apis):
    async def unavailable(patient_id):
        raise main.PatientHistoryUnavailable("the patient database couldn't be reached (ConnectError)")
    monkeypatch.setattr(main, "fetch_patient_history", unavailable)
    mock_apis["llm"]["actions"] = [UPDATE]

    body = client.post("/api/process-note", json=NOTE_REQUEST).json()

    assert body["status"] == "halted_for_clarification"
    assert body["system_alerts"][0]["type"] == "Patient History Unavailable"
    assert "nothing was changed" in body["system_alerts"][0]["message"]
    assert mock_apis["prompts"] == [] and mock_apis["calls"] == []   # the LLM was never asked


@pytest.mark.parametrize("url, key", [("", "sb_secret_x"), ("https://x.supabase.co", ""),
                                      ("https://x.supabase.co", "sb_publishable_x")])
def test_history_refuses_missing_or_publishable_keys(monkeypatch, url, key):
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", key)

    with pytest.raises(main.PatientHistoryUnavailable):
        asyncio.run(main.fetch_patient_history("PT-30554"))


class FakeHttpResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def fake_supabase_http(monkeypatch, tables, fail=False):
    """Stand-in for httpx.AsyncClient that answers PostgREST reads from `tables`."""
    seen = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None):
            seen.append((url.rsplit("/", 1)[-1], headers.get("apikey")))
            if fail:
                raise main.httpx.ConnectError("connection refused")
            return FakeHttpResponse(tables.get(url.rsplit("/", 1)[-1], []))

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_x")
    return seen


def test_history_includes_allergies_regular_meds_and_ward_orders(monkeypatch):
    seen = fake_supabase_http(monkeypatch, {
        "patients": [{"allergies": ["Aspirin"], "active_prescriptions": ["Atorvastatin"], "medical_history": "Post-MI"}],
        "medication_orders": [{"drug": "Heparin", "dose": "5000 units", "route": "iv", "frequency": "continuous"}]})

    history = asyncio.run(main.fetch_patient_history("PT-30554"))

    assert "Known Allergies: Aspirin" in history
    assert "Regular Medications: Atorvastatin" in history
    assert "Current Ward Orders: Heparin 5000 units iv continuous" in history
    assert all(key == "sb_secret_x" for _, key in seen)   # the secret key, never the publishable one


def test_new_patient_without_a_record_is_not_an_error(monkeypatch):
    fake_supabase_http(monkeypatch, {"patients": []})

    assert asyncio.run(main.fetch_patient_history("PT-NEW")) == "PATIENT HISTORY: No prior records found."


def test_database_outage_makes_history_unavailable(monkeypatch):
    fake_supabase_http(monkeypatch, {}, fail=True)

    with pytest.raises(main.PatientHistoryUnavailable):
        asyncio.run(main.fetch_patient_history("PT-30554"))


# ---------- LLM call: retry malformed JSON, short error messages ----------

def fake_groq(monkeypatch, replies):
    """Stand-in for httpx.AsyncClient.post returning (status, body) replies in order."""
    calls = []

    class Reply:
        def __init__(self, status, body):
            self.status_code, self.body = status, body
            self.text = body if isinstance(body, str) else main.json.dumps(body)

        def json(self):
            return self.body if not isinstance(self.body, str) else main.json.loads(self.body)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise main.httpx.HTTPStatusError("error", request=None, response=self)

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append(json)
            return Reply(*replies[len(calls) - 1])

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    return calls


MALFORMED = (400, {"error": {"message": "Failed to generate JSON.", "code": "json_validate_failed",
                             "failed_generation": "{\"status\": \"success\", \"actions\": [{}}, }"}})
GOOD = (200, {"choices": [{"message": {"content": '{"status": "success", "reasoning": "ok", "actions": []}'}}]})


def test_malformed_json_is_retried_once(monkeypatch):
    calls = fake_groq(monkeypatch, [MALFORMED, GOOD])

    result = asyncio.run(main.call_llm("note"))

    assert result["status"] == "success" and len(calls) == 2


def test_malformed_json_twice_halts_with_a_short_message(monkeypatch):
    fake_groq(monkeypatch, [MALFORMED, MALFORMED])

    alert = asyncio.run(main.call_llm("note"))["system_alerts"][0]

    assert alert["type"] == "AI Format Error"
    assert "nothing was changed" in alert["message"] and "failed_generation" not in alert["message"]


def test_rate_limit_gets_a_readable_message(monkeypatch):
    fake_groq(monkeypatch, [(429, {"error": {"message": "Rate limit reached for model in organization org_123 ..."}})])

    alert = asyncio.run(main.call_llm("note"))["system_alerts"][0]

    assert alert["type"] == "AI Gateway Error"
    assert "rate limit" in alert["message"] and "org_123" not in alert["message"]
