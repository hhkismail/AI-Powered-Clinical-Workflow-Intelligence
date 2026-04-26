# Clinical Notes Automation System - Mock Hospital Backend

This repository contains the Flask + Supabase backend used by the UI and orchestration teams.

## Handover Steps

1. Pull the repository.
2. Create your own `.env` file in the project root.
3. Ask Rizwi for the Supabase keys and add them to `.env`:
   - `SUPABASE_URL=...`
   - `SUPABASE_KEY=...`
4. Install dependencies from `requirements.txt`:
   ```powershell
   pip install -r requirements.txt
   ```
5. Start the backend server:# OPHIA: AI-Powered Clinical Workflow Intelligence
*UM Hackathon 2026 — Domain 1: AI Systems & Agentic Workflow Automation*

---

## 🎥 10-Minute Pitch & Product Demonstration
> **[WATCH THE FULL SUBMISSION VIDEO HERE](https://drive.google.com/drive/folders/1QwInfCI_nnIr09jofypu5DqwKQUyDCa6?usp=sharing)**
> 
>This folder contains our formal pitching presentation and a high-fidelity demonstration of the OPHIA agentic workflow.

---

## 📄 Official Deliverables (PDF)
Per the hackathon requirements, the following documentation has been uploaded to this repository in PDF format:

* *[Product Requirement Document (PRD)](./PRD_OPHIA.pdf)*: Comprehensive problem analysis, target audience, and core feature specifications.
* *[System Architecture Document (SAD)](./SAD_OPHIA.pdf)*: Detailed technical stack, system flow diagrams, and Groq-based orchestration logic.
* *[Quality Assurance & Testing Document (QATD)](./QATD_OPHIA.pdf)*: Validation of medical safety protocols, edge case handling, and audit trail integrity.
* *[Pitching Deck](./Pitch_Deck_OPHIA.pdf)*: Our complete 10-slide strategy covering the problem, solution, and roadmap.

---

## 🏥 About OPHIA
OPHIA is a stateful, multi-agent clinical workflow engine designed to transform fragmented hospital data into intelligent care systems. [cite_start]It is built to eliminate dangerous communication breakdowns in Malaysian public hospitals[cite: 5, 29, 37].

### The Read-Reason-Act Workflow
[cite_start]OPHIA utilizes a proprietary loop powered by *GROQ*[cite: 64, 108]:
* [cite_start]*READ*: Extracts structured data from messy handwritten notes and voice memos via GLM-OCR[cite: 40].
* [cite_start]*REASON*: Analyzes patient state, cross-checks drug allergies, and structures data in SOAP/ICD-10 formats[cite: 41, 48, 80].
* [cite_start]*ACT*: Autonomously triggers hospital workflows including bed reservations, appointments, and discharge summaries[cite: 42, 43].

---

## 🛠 Technical Setup & Handover

This repository contains the Flask + Supabase backend used for clinical data management and API orchestration.

### Installation
1.  *Clone the Repository:*
    bash
    git clone [https://github.com/fthanifa/umhackathon2026-clinical.git](https://github.com/fthanifa/umhackathon2026-clinical.git)
    cd umhackathon2026-clinical
    

2.  *Environment Configuration:*
    Create a .env file in the project root and add your Supabase credentials:
    env
    SUPABASE_URL=your_supabase_url
    SUPABASE_KEY=your_supabase_key
    GROQ_API_KEY=your_groq_api_key
    

3.  *Install Dependencies:*
    bash
    pip install -r requirements.txt
    

4.  *Run the Server:*
    bash
    python server.py
    

5.  *Expose Locally (Optional):*
    bash
    ngrok http 3000
    

---

## 🛡️ Medical-Grade Safety
OPHIA includes hard-coded safety constraints managed by the AI engine:
* [cite_start]*Drug Allergy Block*: Automatically intercepts prescriptions contraindicated by patient history[cite: 80, 81].
* [cite_start]*Ambiguity Flags*: Requires senior physician review if diagnosis confidence is below threshold[cite: 84].
* [cite_start]*MOH Audit Trail*: Logs every AI decision with timestamps and reasoning summaries to Supabase for regulatory compliance[cite: 86, 87].
   ```powershell
   python server.py
   ```
6. Start the ngrok tunnel (choose one based on your shell):
   ```powershell
   ngrok http 3000
   ```
   or in PowerShell with local binary:
   ```powershell
   .\\ngrok http 3000
   ```
7. Send your new ngrok URL to the UI team.

## Notes

- Do not commit `.env` to GitHub.
- If dependencies change, regenerate `requirements.txt` and commit it.
# umhackathon2026-clinical
