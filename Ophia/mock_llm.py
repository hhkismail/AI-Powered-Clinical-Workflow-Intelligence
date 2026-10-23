"""
Mock AI mode: a rule-based stand-in for the LLM, so the demo runs without a
Groq key (set MOCK_AI=1 in .env).

plan() reads the same prompt the LLM gets (build_llm_prompt in main.py) and
returns the same JSON shape, so everything after it (allergy rules, hospital
APIs, the ward board) runs for real. It only understands notes written like
the demo ones: known drug names, "admit to ... ward", "Stop X", "Repeat ...".
Anything it doesn't recognise is left out rather than guessed.
"""

import re

from allergy_rules import CLASSES, check_prescriptions

LABEL = "Mock AI mode (no LLM was called): rule-based plan from keywords in the note."

# Drugs it can prescribe: the allergy table's drugs plus common ones in the demo notes
DRUGS = sorted({d for info in CLASSES.values() for d in info["drugs"]} | {
    "metoprolol", "bisoprolol", "diltiazem", "amiodarone", "digoxin", "atorvastatin", "simvastatin",
    "metformin", "insulin", "cetirizine", "loratadine", "paracetamol", "morphine", "codeine", "tramadol",
    "doxycycline", "azithromycin", "clarithromycin", "vancomycin", "gentamicin", "metronidazole",
    "salbutamol", "prednisolone", "hydrocortisone", "furosemide", "heparin", "enoxaparin", "apixaban",
    "warfarin", "omeprazole", "ondansetron", "amlodipine", "lisinopril", "ramipril", "clopidogrel",
}, key=len, reverse=True)  # longest first, so "piperacillin-tazobactam" wins over "piperacillin"

DOSE = r"(\d+(?:\.\d+)?\s*(?:mg|mcg|micrograms?|g|grams?|units?|ml)\b)"
ROUTES = [(r"\b(orally|oral|po|by mouth)\b", "oral"), (r"\b(iv|intravenous(ly)?)\b", "IV"),
          (r"\b(im|intramuscular(ly)?)\b", "IM"), (r"\b(sc|subcut(aneous(ly)?)?)\b", "SC"),
          (r"\b(inhaled|nebulised|nebulized)\b", "inhaled")]
FREQUENCY = re.compile(r"\b(once daily|twice daily|(?:three|four|3|4) times (?:a|per) day|(?:three|four) times daily|"
                       r"every \d+\s*(?:h|hours?)(?: prn)?|daily|nightly|stat|prn)\b", re.IGNORECASE)

STOP_WORDS = re.compile(r"\b(stop|stopped|discontinue|discontinued|cease|hold|withhold|d/c)\b", re.IGNORECASE)
FAILING = re.compile(r"\b(despite|failed|failing|not responding|switch(?:ing)? from|instead of|replace|resistant)\b",
                     re.IGNORECASE)
LIFE_SUPPORT = re.compile(r"respiratory failure|intubat|mechanical ventilation|life support|vasopressor|"
                          r"cardiac arrest|(admit|transfer)\w* to (the )?icu", re.IGNORECASE)
IN_ICU = re.compile(r"\b(in|on) (the )?icu\b", re.IGNORECASE)
ADMIT = re.compile(r"\badmit(?! with)\b|\badmit to\b", re.IGNORECASE)
WORSE = re.compile(r"\b(unstable|deteriorat\w*|sepsis|septic)\b", re.IGNORECASE)
FOLLOW_UP = re.compile(r"\b(?:review|follow[- ]?up)\b.*?\bin (\d+) (day|week|month)s?\b(?:.*?\bin (\w+) clinic)?",
                       re.IGNORECASE)

# (pattern, category) for next steps; the first match wins
STEPS = [(r"\b(consult|refer|referral)\b", "consult"),
         (r"\b(prep|prepare|nbm|nil by mouth|consent|intubat\w*|ventilat\w*)\b", "prep"),
         (r"\b(x-?ray|ct|mri|ultrasound|echo(cardiogram)?|scan)\b", "imaging"),
         (r"\b(culture|abg|arterial blood gas|crp|fbc|troponin|glucose|bloods|labs|electrolytes|u&e)\b", "lab"),
         (r"\b(telemetry|monitor\w*|observations|obs)\b", "monitoring")]
PLAN_VERBS = re.compile(r"\b(repeat|check|initiate|monitor|consult|refer|prep|prepare|keep|arrange|order|obtain|"
                        r"request|requires?|needs?|continue telemetry)\b", re.IGNORECASE)

DIAGNOSES = [(r"atrial fibrillation|\baf\b", "Atrial fibrillation"), (r"unstable angina", "Unstable angina"),
             (r"respiratory failure", "Acute respiratory failure"), (r"pneumonia", "Pneumonia"),
             (r"allergic rhinitis", "Allergic rhinitis"), (r"tension headache", "Tension headache"),
             (r"(closed |open )?fracture [\w ]+", None), (r"type 2 diabetes", "Type 2 diabetes"),
             (r"sepsis", "Sepsis"), (r"heart failure", "Heart failure"), (r"\bcopd\b", "COPD"),
             (r"asthma", "Asthma"), (r"stroke", "Stroke"), (r"myocardial infarction|\bstemi\b", "Myocardial infarction")]


def _field(prompt, name):
    found = re.search(rf"^\s*-?\s*{name}:\s*(.*)$", prompt, re.IGNORECASE | re.MULTILINE)
    return found.group(1).strip() if found else ""


def _sentences(text):
    # A line starting in lower case continues the one before (handwriting and OCR wrap mid-sentence)
    text = re.sub(r"\n(?=[a-z])", " ", text)
    return [s.strip(" -") for s in re.split(r"[.;\n]+|\s-\s", text) if s.strip(" -")]


def _drug_in(sentence):
    for drug in DRUGS:
        if re.search(rf"(?<![a-z]){re.escape(drug)}(?![a-z])", sentence, re.IGNORECASE):
            return drug
    return None


def _prescription(sentence, drug):
    after = sentence[re.search(re.escape(drug), sentence, re.IGNORECASE).end():]
    dose = re.search(DOSE, after, re.IGNORECASE)
    route = next((name for pattern, name in ROUTES if re.search(pattern, after, re.IGNORECASE)), None)
    frequency = FREQUENCY.search(after)
    return {"drug": drug.capitalize(), "dosage": dose.group(1).replace(" ", "") if dose else None,
            "route": route, "frequency": frequency.group(1) if frequency else None}


def plan(prompt):
    """A plan in the LLM's output schema for the prompt from build_llm_prompt."""
    patient_id = _field(prompt, "PATIENT ID")
    department = _field(prompt, "DEPARTMENT") or "General"
    allergies = [a.strip() for a in _field(prompt, "Known Allergies").split(",")
                 if a.strip() and a.strip().lower() != "none documented"]
    ward_orders = [o for o in _field(prompt, "Current Ward Orders").split(";") if o.strip() and o.strip() != "None"]
    note = prompt.split("NEW DOCTOR'S NOTE:", 1)[-1]
    sentences = _sentences(note)

    prescriptions, next_steps = [], []
    for sentence in sentences:
        drug = _drug_in(sentence)
        if drug and not STOP_WORDS.search(sentence) and not FAILING.search(sentence):
            if not any(p["drug"].lower() == drug for p in prescriptions):
                prescriptions.append(_prescription(sentence, drug))
            continue
        if drug or FOLLOW_UP.search(sentence) or not PLAN_VERBS.search(sentence):
            continue
        category = next((c for pattern, c in STEPS if re.search(pattern, sentence, re.IGNORECASE)), "other")
        next_steps.append({"description": sentence[0].upper() + sentence[1:], "category": category})

    # Rule 1: a prescription the patient is allergic to halts the note
    blocks = [f for f in check_prescriptions(prescriptions, allergies) if f["severity"] == "block"]
    if blocks:
        return {"status": "halted_for_clarification", "reasoning": f"{LABEL} {blocks[0]['reason']}", "actions": [],
                "system_alerts": [{"type": "Clinical Safety Halt", "message": blocks[0]["reason"]}]}

    # Medications on the ward that the note stops (explicit) or implies are failing (inferred)
    discontinue = []
    for order in ward_orders:
        drug = _drug_in(order) or order.split()[0].lower()
        mentions = [s for s in sentences if re.search(rf"\b{re.escape(drug)}\b", s, re.IGNORECASE)]
        if any(STOP_WORDS.search(s) for s in mentions):
            discontinue.append({"drug": drug.capitalize(), "reason": "The note says to stop it.", "explicit": True})
        elif any(FAILING.search(s) for s in mentions):
            discontinue.append({"drug": drug.capitalize(), "explicit": False,
                                "reason": "The note suggests it isn't working; a clinician should confirm the stop."})

    if LIFE_SUPPORT.search(note):
        ward, acuity = "icu", "critical"
    elif ADMIT.search(note):
        ward = "observation" if re.search(r"observation", note, re.IGNORECASE) else "general"
        acuity = "serious"
    else:
        ward = None
        acuity = "critical" if IN_ICU.search(note) else "serious" if WORSE.search(note) else "stable"

    diagnoses = []
    for pattern, name in DIAGNOSES:
        found = re.search(pattern, note, re.IGNORECASE)
        if found:
            text = found.group(0).strip()
            diagnoses.append(name or text[0].upper() + text[1:])
    record = {"patient_id": patient_id, "diagnoses": diagnoses or ["See clinical note"],
              "prescriptions": prescriptions, "acuity": acuity, "next_steps": next_steps, "discontinue": discontinue}
    actions = [{"tool": "update_record", "params": record}]
    reasons = [f"acuity {acuity}"]

    if ward:
        actions.append({"tool": "reserve_bed", "params": {"patient_id": patient_id, "ward_type": ward,
                                                          "clinical_reason": ", ".join(diagnoses) or "Admission"}})
        reasons.append("ICU bed for life support" if ward == "icu" else f"{ward} bed because the note admits the patient")
    follow_up = FOLLOW_UP.search(note)
    if follow_up:
        count, unit, clinic = follow_up.groups()
        days = int(count) * {"day": 1, "week": 7, "month": 30}[unit.lower()]
        actions.append({"tool": "schedule_appointment", "params": {
            "patient_id": patient_id, "department": clinic.capitalize() if clinic else department,
            "timeframe_days": days, "reason": "Follow-up review requested in the note"}})
        reasons.append(f"follow-up in {days} days")

    return {"status": "success", "reasoning": f"{LABEL} Found {', '.join(reasons)}.",
            "actions": actions, "system_alerts": []}
