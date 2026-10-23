"""
Vercel entrypoint: the whole demo as one app on one origin.

    /                       the frontend (served from Vercel's CDN)
    /emr/...                the Mock EMR API (server.py)
    /ingest/...             the ingestion gateway (ingestion/ingestion.py)
    /api/health             health check
    /api/cron/reset-demo    the nightly reset (Vercel Cron, needs CRON_SECRET)

The orchestrator has no public route. Ingestion calls it in-process and it calls
the EMR API in-process, so a visitor can only reach what the browser uses. The
EMR routes only the orchestrator should call (record updates, bed reservations,
appointments) are blocked from outside, so every note goes through the allergy
checks and the AI budget.

Locally, tools/start.py still runs the four services separately; this file
isn't needed for that.
"""

import asyncio
from datetime import datetime, timezone
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
for folder in ("tools", "ingestion", "Ophia"):
    sys.path.insert(0, os.path.join(ROOT, folder))

from a2wsgi import WSGIMiddleware  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import ingestion  # noqa: E402
import main as orchestrator  # noqa: E402
import reset_demo  # noqa: E402
import server as emr  # noqa: E402

# Only the orchestrator writes notes' results; from outside these return 403
INTERNAL_ONLY = {"/api/update-record", "/api/reserve-bed", "/api/schedule-appointment"}

# Notes replayed after the nightly reset, so the board never opens empty.
# They're planned by the mock AI, so the reset costs no Groq quota.
DEMO_NOTES = [
    ("PT-30554", "Cardiology",
     "Sudden onset palpitations and shortness of breath for 2 hours. Heart rate 138 irregular, BP 145/90. ECG shows "
     "acute atrial fibrillation with rapid ventricular response. Plan: admit to the observation ward. Initiate "
     "continuous cardiac monitoring (telemetry). Prescribed Metoprolol 25mg orally twice daily."),
    ("PT-10934", "Critical Care",
     "Severe community acquired pneumonia with acute respiratory failure, SpO2 86% on high-flow oxygen, needs "
     "non-invasive ventilation. Transfer to ICU. Start Meropenem 1g IV every 8 hours. Repeat arterial blood gas in "
     "2 hours. Check blood glucose four times a day."),
    ("PT-40992", "Emergency",
     "Fall from ladder. Closed fracture R tibial shaft, neurovascularly intact. Plan: admit to general ward. "
     "Morphine 5mg IV every 4h PRN pain. Ortho consult. Prep for ORIF tomorrow. Keep NBM from midnight."),
    ("PT-55108", "Emergency",
     "Fall at home. Suspected fracture of the left neck of femur. Admit to general ward. Paracetamol 1g orally "
     "every 6 hours. Request hip x-ray. Orthogeriatric consult."),
    ("PT-20221", "Paediatrics",
     "Mild asthma exacerbation, settled in the emergency department. Prescribed Salbutamol 100 micrograms inhaled "
     "as needed. Review in 2 weeks in Paediatrics clinic. Discharge home."),
]


def orchestrate(payload):
    """Run a note through the orchestrator in this process: payload -> (JSON, status)."""
    try:
        request = orchestrator.ProcessNoteRequest(**payload)
    except ValidationError as e:
        return {"detail": e.errors(include_url=False)}, 422
    response = asyncio.run(orchestrator.process_note(request))
    return response.model_dump(mode="json"), 200


def public_emr(environ, start_response):
    if environ.get("PATH_INFO") in INTERNAL_ONLY:
        start_response("403 Forbidden", [("Content-Type", "application/json")])
        return [b'{"status": "error", "message": "Only the orchestrator can call this endpoint."}']
    return emr.app(environ, start_response)


orchestrator.EMR_APP = emr.app
ingestion.ORCHESTRATE = orchestrate

app = FastAPI(title="Ophia demo", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health():
    return {"status": "healthy", "ai": "mock" if orchestrator.mock_ai_enabled() else orchestrator.GROQ_CHAT_MODEL,
            "database": emr.supabase is not None}


@app.get("/api/cron/reset-demo")
def reset_demo_data(request: Request):
    """Back to the seed, then replay DEMO_NOTES. Vercel Cron sends 'Bearer <CRON_SECRET>'."""
    secret = os.getenv("CRON_SECRET")
    if not secret or request.headers.get("authorization") != f"Bearer {secret}":
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    if emr.supabase is None:
        return JSONResponse({"status": "error", "message": "The database isn't configured."}, status_code=500)

    reset_demo.reset_all(emr.supabase)
    replayed = []
    for patient_id, department, note in DEMO_NOTES:
        body, _ = orchestrate({
            "metadata": {"doctor_id": "DEMO-RESET", "patient_id": patient_id, "department": department,
                         "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "priority": "normal", "ai": "mock"},
            "payload": {"input_methods_used": ["text"], "raw_text": note}})
        replayed.append({"patient_id": patient_id, "status": body.get("status")})
    return {"status": "reset", "replayed": replayed}


app.mount("/emr", WSGIMiddleware(public_emr))
app.mount("/ingest", WSGIMiddleware(ingestion.app))
app.mount("/", StaticFiles(directory=os.path.join(ROOT, "frontend"), html=True), name="frontend")
