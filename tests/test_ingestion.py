"""Tests for the ingestion gateway (ingestion/ingestion.py). Groq and the orchestrator are mocked."""

import io

import pytest
import requests

import ingestion


class FakeResponse:
    status_code = 200

    def json(self):
        return {"status": "success"}


@pytest.fixture
def forwarded(monkeypatch):
    """Capture what ingestion forwards to the orchestrator."""
    sent = []
    monkeypatch.setattr(ingestion.req, "post", lambda url, json, timeout: sent.append((url, json)) or FakeResponse())
    return sent


@pytest.fixture
def client():
    return ingestion.app.test_client()


def test_typed_note_is_forwarded_in_orchestrator_format(client, forwarded):
    resp = client.post("/api/process-note", data={
        "patient_id": "PT-30554", "doctor_id": "DR-7742", "department": "Cardiology",
        "priority": "high", "typed_text": "Metoprolol 25mg PO"})

    assert resp.status_code == 200
    url, payload = forwarded[0]
    assert url == ingestion.ORCHESTRATOR_URL
    assert payload["metadata"]["patient_id"] == "PT-30554"
    assert payload["payload"] == {"input_methods_used": ["text"], "raw_text": "Metoprolol 25mg PO"}


def test_patient_and_doctor_are_required(client, forwarded):
    resp = client.post("/api/process-note", data={"typed_text": "note"})

    assert resp.status_code == 400
    assert forwarded == []


def test_unsupported_file_without_text_is_rejected(client, forwarded):
    resp = client.post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "file": (io.BytesIO(b"%PDF"), "note.pdf")})

    assert resp.status_code == 400
    assert forwarded == []


def test_image_is_ocrd_and_forwarded(client, forwarded, monkeypatch):
    monkeypatch.setattr(ingestion, "ocr_image", lambda path: "Rx: Metoprolol 25mg PO")

    resp = client.post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "file": (io.BytesIO(b"\x89PNG"), "note.png")})

    assert resp.status_code == 200
    assert forwarded[0][1]["payload"] == {"input_methods_used": ["image"], "raw_text": "Rx: Metoprolol 25mg PO"}


def test_typed_text_and_uploaded_file_are_combined(client, forwarded, monkeypatch):
    monkeypatch.setattr(ingestion, "transcribe_audio", lambda path: "Start amoxicillin 1 gram orally three times a day.")

    resp = client.post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "typed_text": "Follow-up to this morning's ward round.",
        "file": (io.BytesIO(b"RIFF"), "memo.wav")})

    assert resp.status_code == 200
    assert forwarded[0][1]["payload"] == {
        "input_methods_used": ["text", "audio"],
        "raw_text": "Follow-up to this morning's ward round.\n\nStart amoxicillin 1 gram orally three times a day."}


def test_image_upload_without_api_key_returns_clear_json_error(client, forwarded, monkeypatch):
    monkeypatch.setattr(ingestion, "GROQ_API_KEY", None)

    resp = client.post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "file": (io.BytesIO(b"\x89PNG"), "note.png")})

    assert resp.status_code == 500
    assert "GROQ_API_KEY" in resp.get_json()["error"]
    assert forwarded == []


def test_ocr_failure_returns_502_json_not_a_traceback(client, forwarded, monkeypatch):
    def failing_ocr(path):
        raise requests.exceptions.HTTPError("503 Server Error: over capacity")
    monkeypatch.setattr(ingestion, "ocr_image", failing_ocr)

    resp = client.post("/api/process-note", data={
        "patient_id": "P", "doctor_id": "D", "file": (io.BytesIO(b"\x89PNG"), "note.png")})

    assert resp.status_code == 502
    assert "over capacity" in resp.get_json()["error"]
    assert forwarded == []
