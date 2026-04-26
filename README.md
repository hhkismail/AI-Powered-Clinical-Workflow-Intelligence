# 🩺 Project OPHIA: AI-Powered Clinical Workflow Intelligence
**UM Hackathon 2026 — Domain 1: AI Systems & Agentic Workflow Automation**

OPHIA is a stateful, multi-agent clinical orchestration engine designed to eliminate the administrative lag in critical care. By utilizing a "Read-Reason-Act" loop, OPHIA transforms unstructured clinical notes into autonomous hospital actions, including real-time bed reservations and medication safety audits.

---

## 🎥 Project Demo & Presentation
> **[WATCH THE SUBMISSION VIDEO HERE](https://drive.google.com/drive/folders/1QwInfCI_nnIr09jofypu5DqwKQUyDCa6?usp=sharing)**
> 
> *This folder contains our formal pitching presentation and the high-fidelity demonstration of the OPHIA orchestrator in action.*

---

## 🏗️ The 4-Tier Microservice Mesh
To ensure clinical-grade reliability, OPHIA operates as a distributed system:

1.  **Ingestion Engine (Port 5000):** Flask-based gateway for multimodal data (OCR/Audio ingestion).
2.  **The Orchestrator (Port 8000):** FastAPI "Brain" powered by **Groq (Llama-3.3-70b)** for clinical reasoning.
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

## 🧪 The "Rajesh Kumar" Demo Scenario
To verify the stateful agentic workflow, input the following into the dashboard:

"Patient Rajesh Kumar (ID: PT-30554) presents to the emergency department complaining of sudden onset palpitations, shortness of breath, and mild chest tightness that began 2 hours ago. Vitals show an irregular heart rate of 138 bpm and blood pressure of 145/90. Preliminary ECG indicates acute Atrial Fibrillation with rapid ventricular response. Plan: Admit to the observation ward. Initiate continuous cardiac monitoring (telemetry) immediately. Prescribed Metoprolol 25mg orally to control heart rate. Monitor for drug interactions."

The **OPHIA** Execution Loop:

**READ**: The Ingestion engine structures the raw text into clinical entities.

**REASON**: The AI identifies the life-threatening status and determines that an ICU bed is mandatory.

**ACT**: The system triggers update_record for the prescription and reserve_bed for the ICU.

**PERSIST**: Check your Supabase Dashboard — Bed RES-ICU-01 will have automatically flipped to occupied.

---

## 🚀 Quick Start Guide

### 1. Environment Setup
Create a `.env` file in the root directory. Because our system uses multiple integrated backends, ensure you provide values for **all** variables below:

```env
# AI & Orchestration
ZAI_API_KEY=your_groq_key_here
MOCK_API_BASE_URL=[http://127.0.0.1:3001](http://127.0.0.1:3001)

# Database (Compatibility for all Microservices)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
ISMA_DB_URL=your_supabase_url
ISMA_ANON_KEY=your_supabase_anon_key

# Launch Sequence
Terminal,Service,Command
Terminal 1   Ingestion      cd ingestion && python ingestion.py
Terminal 2   Orchestrator   cd Ophia && uvicorn main:app --reload --port 8000
Terminal 3   Hospital API   python server.py
Terminal 4   Dashboard      Open frontend/index.html via Live Server

```

---

## 🧪 The "Rajesh Kumar" Demo Scenario
To verify the stateful agentic workflow, input the following into the dashboard:

"Patient Rajesh Kumar (ID: PT-30554) presents to the emergency department complaining of sudden onset palpitations, shortness of breath, and mild chest tightness that began 2 hours ago. Vitals show an irregular heart rate of 138 bpm and blood pressure of 145/90. Preliminary ECG indicates acute Atrial Fibrillation with rapid ventricular response. Plan: Admit to the observation ward. Initiate continuous cardiac monitoring (telemetry) immediately. Prescribed Metoprolol 25mg orally to control heart rate. Monitor for drug interactions."

The **OPHIA** Execution Loop:

**READ**: The Ingestion engine structures the raw text into clinical entities.

**REASON**: The AI identifies the life-threatening status and determines that an ICU bed is mandatory.

**ACT**: The system triggers update_record for the prescription and reserve_bed for the ICU.

**PERSIST**: Check your Supabase Dashboard — Bed RES-CARD-01 will have automatically flipped to occupied.

---

## 🛡️ Medical Safety & Compliance
Drug Allergy Interception: Automatically blocks prescriptions contraindicated by patient history.

Audit Trail: Every AI decision is logged to Supabase with a reasoning summary for MOH compliance.

Human-in-the-loop: Requires manual verification for high-risk surgical scheduling.

---

Developed for the UM Hackathon 2026. "AI-First, Patient-Always."
