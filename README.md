# 🩺 Project OPHIA: AI-Powered Clinical Workflow Intelligence
**UM Hackathon 2026 — Domain 1: AI Systems & Agentic Workflow Automation**

OPHIA is a hackathon prototype of an AI clinical workflow orchestrator. It takes an unstructured clinical note (typed, photographed or dictated), uses an LLM to extract diagnoses and prescriptions, and turns them into hospital actions such as updating the patient record, reserving a bed or scheduling a follow-up. It's a demo and is not meant for clinical use.

---

## 🎥 Project Demo & Presentation
> **[WATCH THE SUBMISSION VIDEO HERE](https://drive.google.com/drive/folders/1QwInfCI_nnIr09jofypu5DqwKQUyDCa6?usp=sharing)**
> 
> *This folder contains our formal pitching presentation and the high-fidelity demonstration of the OPHIA orchestrator in action.*

---

## 🏗️ Architecture
OPHIA runs as four small services:

1.  **Ingestion Engine (Port 5000):** Flask-based gateway for multimodal data (OCR/Audio ingestion).
2.  **The Orchestrator (Port 8000):** FastAPI "Brain" powered by **Groq (`openai/gpt-oss-120b`)** for clinical reasoning. Image notes are read with `qwen/qwen3.8-27b` and audio with `whisper-large-v3`.
3.  **Mock EMR API (Port 3001):** The execution layer that routes AI commands to **Supabase** persistence.
4.  **Clinical Dashboard (Port 5500):** A real-time visualization layer built with Vanilla JS for zero-dependency execution.

---

## 📄 Official Deliverables (PDF)
The following documents are located in the root directory for review:
* **[System Architecture Document (SAD)](./SAD_Ophia.pdf)** — Technical diagrams and mesh logic.
* **[Product Requirement Document (PRD)](./PRD_Ophia.pdf)** — Problem analysis and feature roadmap.
* **[Quality Assurance Document (QATD)](./QATD_Ophia.pdf)** — Safety protocols and audit trail integrity.
* **[Pitching Deck](./Ophia.pdf)** — Our strategy and market vision.

---

## 🚀 Quick Start Guide

### Prerequisites
* Python 3.12
* A [Groq API key](https://console.groq.com/keys)
* A Supabase project (the free tier is fine)

### 1. Set up the database
In your Supabase project's SQL editor, run [`db/schema.sql`](./db/schema.sql) to create the tables, then [`db/seed.sql`](./db/seed.sql) for the demo patients and beds (all fictional).

If your database was created from an older version of `schema.sql`, apply the files in [`db/migrations/`](./db/migrations/) in order instead. Each one has a matching `.down.sql` rollback.

### 2. Install dependencies
All three services share one `requirements.txt`:

```bash
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment setup
Create a `.env` file in the repo root. Every service reads this same file:

```env
# Groq API key (ZAI_API_KEY is still accepted as the old name)
GROQ_API_KEY=your_groq_key_here

# Where the orchestrator sends hospital actions (the Mock EMR API)
MOCK_API_BASE_URL=http://127.0.0.1:3001

# Supabase project URL and publishable key (Project Settings -> API Keys), used by server.py
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_publishable_key
# Secret key (sb_secret_...), server-side only. Required for the ward board tables,
# which have row-level security that blocks the publishable key
SUPABASE_SECRET_KEY=your_supabase_secret_key

# Same Supabase project, used by the orchestrator for patient-history lookups
ISMA_DB_URL=your_supabase_url
ISMA_ANON_KEY=your_supabase_publishable_key

# Optional: override the Groq models if Groq retires one (see https://console.groq.com/docs/deprecations)
# GROQ_CHAT_MODEL=openai/gpt-oss-120b
# GROQ_VISION_MODEL=qwen/qwen3.8-27b

# Optional: set to 1 to enable the Flask debugger locally (never on a public URL)
# FLASK_DEBUG=1
```

### 4. Launch
Run each service from the repo root in its own terminal:

| Terminal | Service | Command |
|---|---|---|
| 1 | Mock EMR API (3001) | `python server.py` |
| 2 | Orchestrator (8000) | `uvicorn main:app --app-dir Ophia --reload --port 8000` |
| 3 | Ingestion (5000) | `python ingestion/ingestion.py` |
| 4 | Dashboard (5500) | `python -m http.server 5500 --directory frontend`, then open http://localhost:5500 |

Interactive API docs for the orchestrator are at http://localhost:8000/docs.

---

## 🧪 The "Rajesh Kumar" Demo Scenario
Enter patient ID `PT-30554` and the following note into the dashboard:

"Patient Rajesh Kumar (ID: PT-30554) presents to the emergency department complaining of sudden onset palpitations, shortness of breath, and mild chest tightness that began 2 hours ago. Vitals show an irregular heart rate of 138 bpm and blood pressure of 145/90. Preliminary ECG indicates acute Atrial Fibrillation with rapid ventricular response. Plan: Admit to the observation ward. Initiate continuous cardiac monitoring (telemetry) immediately. Prescribed Metoprolol 25mg orally to control heart rate. Monitor for drug interactions."

The **OPHIA** Execution Loop:

**READ**: The ingestion service passes the note (or the text extracted from an image or audio file) to the orchestrator.

**REASON**: The orchestrator loads the patient's allergies and active prescriptions from Supabase and asks the LLM to decide which actions the note calls for.

**ACT**: The LLM's chosen actions are executed against the Mock EMR API. For this note, expect `update_record` for the Metoprolol prescription and `reserve_bed` for the requested ward.

**PERSIST**: In Supabase, a new row appears in `clinical_notes` and the reserved bed in `hospital_resources` flips to `occupied`.

Every run reserves a bed, so free them again between demos:

```bash
python tools/reset_demo.py                 # free the beds (add --dry-run to preview)
python tools/reset_demo.py --clear-board   # also clear medications, tasks and acuity
```

---

## ✅ Testing
```bash
pip install -r requirements-dev.txt
pytest
```
The tests cover all three services with Supabase, Groq and the other services mocked, so they need no API keys. They run on every push and pull request via GitHub Actions.

The LLM itself is checked separately by a **clinical safety eval**. It runs fixed notes through the real prompt and model and checks the decisions: halt on allergy conflicts, ICU vs observation beds, no bed for outpatients. It calls Groq, so run it by hand after changing the prompt or model:

```bash
python evals/run_safety_eval.py --runs 3
```

---

## 🛡️ Safety Behaviour (and Current Limits)
* **Allergy checks:** The patient's known allergies and active prescriptions are included in the LLM prompt, and the model is instructed to halt on a conflict. This check is done by the LLM, not by a deterministic rule.
* **Halting:** If the LLM halts, the request returns `halted_for_clarification` and nothing is executed. If some actions succeed and others are rejected or fail (e.g. the record is saved but no bed is free), the request returns `partial_success`. The dashboard then lists exactly which actions failed; earlier actions aren't rolled back.
* **Audit trail:** Each processed note is saved to `clinical_notes` with the original text, the extracted diagnoses and prescriptions, and the LLM's reasoning for its actions.
* **Ward board data:** Prescriptions become `medication_orders` (routes normalised, e.g. "orally" → `oral`, "IV drip" → `iv`), the patient's acuity is updated, and next steps become `care_tasks` with status `suggested`. AI suggestions aren't real tasks until a clinician accepts them. Repeated notes don't duplicate active medications, open tasks or beds. Asking for a different kind of bed is a transfer, and the old bed is released for cleaning.
* **Rate limits:** On Groq's free tier (8,000 tokens per minute) the orchestrator handles about five notes a minute. Beyond that, requests halt with an `AI Gateway Error` and can simply be retried.
* **No authentication:** The APIs have no auth and accept requests from any origin. Run them locally only.

---

Developed for the UM Hackathon 2026. "AI-First, Patient-Always."
