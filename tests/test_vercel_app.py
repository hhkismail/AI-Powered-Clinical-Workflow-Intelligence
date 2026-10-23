"""Tests for the Vercel deployment: app.py, the AI budget (ingestion/demo_budget.py) and the full reset."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app as vercel_app  # first: it puts tools/ on the path
import demo_budget
import ingestion
import main
import mock_llm
import server

# Importing app.py wires the services together in-process. The other test files
# test the HTTP paths, so switch that off; the fixture below turns it back on.
ingestion.ORCHESTRATE = None
main.EMR_APP = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = "PATIENT HISTORY (CRITICAL CONTEXT):\n- Known Allergies: {}\n- Current Ward Orders: None"


@pytest.fixture
def deployed(monkeypatch, fake_db):
    """The deployed app with the fake database, in-process wiring on and no Groq."""
    monkeypatch.setattr(server, "supabase", fake_db)
    monkeypatch.setattr(ingestion, "ORCHESTRATE", vercel_app.orchestrate)
    monkeypatch.setattr(main, "EMR_APP", server.app)
    monkeypatch.setenv("MOCK_AI", "1")

    async def history(patient_id):
        return HISTORY.format("Aspirin"), ["Aspirin"]
    monkeypatch.setattr(main, "fetch_patient_history", history)
    return TestClient(vercel_app.app)


def note(client, text, patient_id="PT-30554", **headers):
    return client.post("/ingest/api/process-note", headers=headers, data={
        "patient_id": patient_id, "doctor_id": "DR-1", "department": "Cardiology", "typed_text": text})


def test_frontend_and_apis_share_one_origin(deployed):
    assert "<title>" in deployed.get("/").text
    assert deployed.get("/board.html").status_code == 200
    assert deployed.get("/emr/api/ward-board").json()["summary"]["beds"]["available"] == 2
    assert deployed.get("/api/health").json() == {"status": "healthy", "ai": "mock", "database": True}


def test_a_note_runs_through_every_service_in_process(deployed, fake_db):
    resp = note(deployed, "Admit to the observation ward. Prescribed Metoprolol 25mg orally twice daily.")

    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "success" and body["ai"] == "mock"
    bed = next(b for b in fake_db.tables["hospital_resources"] if b["id"] == "RES-NEURO-01")
    assert (bed["status"], bed["assigned_to_patient"]) == ("occupied", "PT-30554")
    assert [o["drug"] for o in fake_db.tables["medication_orders"]] == ["Metoprolol"]


def test_allergy_conflicts_are_still_blocked_when_deployed(deployed, fake_db):
    body = note(deployed, "Unstable angina. Admit to the observation ward. Start Aspirin 300mg orally stat.").json()

    assert body["status"] == "halted_for_clarification"
    assert "clinical_notes" not in fake_db.tables


@pytest.mark.parametrize("path", sorted(vercel_app.INTERNAL_ONLY))
def test_orchestrator_only_routes_are_blocked_from_outside(deployed, fake_db, path):
    resp = deployed.post(f"/emr{path}", json={"patient_id": "PT-30554", "ward_type": "icu"})

    assert resp.status_code == 403
    assert all(b["assigned_to_patient"] is None for b in fake_db.tables["hospital_resources"])


def test_the_orchestrator_has_no_public_route(deployed):
    assert deployed.post("/api/process-note", json={}).status_code in (404, 405)


# ---------- AI budget ----------

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


def at(minutes_ago, now=NOW):
    return (now - timedelta(minutes=minutes_ago)).isoformat()


def log(fake_db, client, *minutes_ago, now=NOW):
    fake_db.tables.setdefault("note_requests", []).extend(
        {"client": client, "ai": "llm", "created_at": at(m, now)} for m in minutes_ago)


def test_budget_allows_the_llm_and_logs_the_note(fake_db):
    assert demo_budget.decide(fake_db, "a", NOW) == (demo_budget.LLM, None)
    assert fake_db.tables["note_requests"] == [{"client": "a", "ai": "llm", "created_at": NOW.isoformat()}]


def test_a_busy_visitor_gets_the_mock_ai(fake_db):
    log(fake_db, "a", 2, 3, 4, 5, 6)      # five LLM notes in the last 10 minutes
    log(fake_db, "b", 2)

    assert demo_budget.decide(fake_db, "a", NOW) == (demo_budget.MOCK, "visitor")
    assert demo_budget.decide(fake_db, "b", NOW) == (demo_budget.LLM, None)


def test_old_notes_dont_count(fake_db):
    log(fake_db, "a", 11, 12, 13, 14, 15)

    assert demo_budget.decide(fake_db, "a", NOW) == (demo_budget.LLM, None)


def test_a_busy_site_gives_everyone_the_mock_ai(fake_db):
    for client in "wxyz":
        log(fake_db, client, 0.5)

    assert demo_budget.decide(fake_db, "new", NOW) == (demo_budget.MOCK, "site")


def test_a_flood_from_one_visitor_is_refused_and_not_logged(fake_db):
    log(fake_db, "a", *range(15, 45))     # 30 in the last hour

    assert demo_budget.decide(fake_db, "a", NOW) == (demo_budget.REFUSE, None)
    assert len(fake_db.tables["note_requests"]) == 30


def test_client_key_hashes_the_address():
    key = demo_budget.client_key({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "10.0.0.1")

    assert key == demo_budget.client_key({"x-real-ip": "203.0.113.7"}, "10.0.0.2")
    assert "203.0.113.7" not in key and len(key) == 32


@pytest.fixture
def public_demo(deployed, monkeypatch, fake_db):
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.setenv("MOCK_AI", "")
    monkeypatch.setattr(ingestion, "budget_db", lambda: fake_db)
    sent = []
    real = vercel_app.orchestrate
    monkeypatch.setattr(ingestion, "ORCHESTRATE", lambda payload: sent.append(payload) or real(payload))
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **k: pytest.fail("the LLM was called"))
    return sent


def test_over_budget_notes_are_planned_by_the_mock_and_say_why(deployed, public_demo, fake_db):
    log(fake_db, demo_budget.client_key({"x-real-ip": "203.0.113.7"}, None), 1, 2, 3, 4, 5,
        now=datetime.now(timezone.utc))

    body = note(deployed, "Mild rhinitis. Prescribed Cetirizine 10mg orally once daily.", **{"x-real-ip": "203.0.113.7"}).json()

    assert public_demo[0]["metadata"]["ai"] == "mock"
    assert body["ai"] == "mock" and body["ai_note"] == demo_budget.REASONS["visitor"]


def test_refused_visitors_get_a_429(deployed, public_demo, fake_db):
    log(fake_db, demo_budget.client_key({"x-real-ip": "203.0.113.7"}, None), *range(1, 31),
        now=datetime.now(timezone.utc))

    resp = note(deployed, "Anything.", **{"x-real-ip": "203.0.113.7"})

    assert resp.status_code == 429 and public_demo == []


def test_budget_outage_falls_back_to_the_mock(deployed, public_demo, fake_db):
    fake_db.fail_tables.add("note_requests")

    body = note(deployed, "Mild rhinitis. Prescribed Cetirizine 10mg orally once daily.").json()

    assert body["ai"] == "mock" and body["ai_note"] == demo_budget.REASONS["site"]


# ---------- Nightly reset ----------

def test_reset_needs_the_cron_secret(deployed, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret-value-for-tests")

    assert deployed.get("/api/cron/reset-demo").status_code == 401
    assert deployed.get("/api/cron/reset-demo", headers={"authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.delenv("CRON_SECRET")
    assert deployed.get("/api/cron/reset-demo", headers={"authorization": "Bearer "}).status_code == 401


def test_reset_clears_everything_and_replays_the_demo_notes(deployed, monkeypatch, fake_db):
    monkeypatch.setenv("CRON_SECRET", "s3cret-value-for-tests")
    fake_db.tables["bed_requests"] = [{"id": "r1", "patient_id": "PT-30554", "status": "waiting"}]
    fake_db.tables["note_requests"] = [{"id": 1, "client": "a", "ai": "llm", "created_at": at(1)}]
    fake_db.tables["appointments"] = [{"id": "APT-1", "patient_id": "PT-30554"}]

    resp = deployed.get("/api/cron/reset-demo", headers={"authorization": "Bearer s3cret-value-for-tests"})

    assert resp.status_code == 200
    assert [r["patient_id"] for r in resp.json()["replayed"]] == [p for p, _, _ in vercel_app.DEMO_NOTES]
    assert all(r["id"] != "r1" for r in fake_db.tables["bed_requests"]) and fake_db.tables["note_requests"] == []
    assert all(a["id"] != "APT-1" for a in fake_db.tables["appointments"])
    # Rajesh's replayed note admitted him again (the only seeded patient in the fake)
    bed = next(b for b in fake_db.tables["hospital_resources"] if b["assigned_to_patient"] == "PT-30554")
    assert bed["id"] == "RES-NEURO-01"


@pytest.mark.parametrize("patient_id, allergies, ward, warns", [
    ("PT-30554", "Aspirin", "observation", False),
    ("PT-10934", "Penicillin, Sulfa Drugs", "icu", True),   # meropenem: the board shows an allergy warning
    ("PT-40992", "None documented", "general", False),
    ("PT-55108", "Ibuprofen", "general", False),
    ("PT-20221", "Latex, Peanuts", None, False),
])
def test_demo_notes_give_a_varied_board(patient_id, allergies, ward, warns):
    text = next(n for p, _, n in vercel_app.DEMO_NOTES if p == patient_id)
    plan = mock_llm.plan(main.build_llm_prompt(patient_id, "2026-10-23", "General", HISTORY.format(allergies), text))

    assert plan["status"] == "success"
    beds = [a["params"]["ward_type"] for a in plan["actions"] if a["tool"] == "reserve_bed"]
    assert beds == ([ward] if ward else [])
    record = plan["actions"][0]["params"]
    assert record["prescriptions"] and record["diagnoses"] != ["See clinical note"]
    findings = main.check_prescriptions(record["prescriptions"], [a.strip() for a in allergies.split(",")])
    assert [f["severity"] for f in findings] == (["warn"] if warns else [])


def test_vercel_config_runs_the_reset_daily():
    with open(os.path.join(ROOT, "vercel.json"), encoding="utf-8") as f:
        config = json.load(f)

    assert config["crons"] == [{"path": "/api/cron/reset-demo", "schedule": "0 19 * * *"}]
    assert "app.py" in config["functions"]


@pytest.mark.parametrize("page", ["/", "/board.html"])
def test_pages_have_link_previews(deployed, page):
    html = deployed.get(page).text

    assert '<meta property="og:image" content="https://ophia-ward.vercel.app/og-image.png">' in html
    assert '<meta property="og:title"' in html and '<meta property="og:description"' in html
    assert deployed.get("/og-image.png").headers["content-type"] == "image/png"
