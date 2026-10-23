"""
Deterministic allergy checks for prescriptions.

The LLM is asked to catch allergy conflicts too, but its judgement varies on
borderline cases. These rules make the outcome the same every time for the
drugs they know:

  block - the drug is the allergen, or in the allergen's drug class
          (aspirin allergy + aspirin, penicillin allergy + amoxicillin)
  warn  - cross-reactivity is possible between related classes or within a
          class (penicillin allergy + meropenem, ibuprofen allergy + naproxen)

Drugs the table doesn't know are left to the LLM. This is a demonstration rule
set, not a complete clinical knowledge base.
"""

import re

# Drug classes and the names (generic and common brand) that belong to them
CLASSES = {
    "penicillin": {"label": "penicillin", "drugs": [
        "penicillin", "benzylpenicillin", "phenoxymethylpenicillin", "amoxicillin", "amoxycillin", "ampicillin",
        "flucloxacillin", "cloxacillin", "dicloxacillin", "piperacillin", "piperacillin-tazobactam", "tazocin",
        "co-amoxiclav", "amoxicillin-clavulanate", "augmentin", "ticarcillin", "temocillin"]},
    "cephalosporin": {"label": "cephalosporin", "drugs": [
        "cefalexin", "cephalexin", "cefazolin", "cefuroxime", "cefaclor", "cefotaxime", "ceftriaxone",
        "ceftazidime", "cefepime", "cefixime", "cefpodoxime", "ceftaroline", "cefiderocol"]},
    "carbapenem": {"label": "carbapenem", "drugs": ["meropenem", "imipenem", "ertapenem", "doripenem"]},
    "nsaid": {"label": "NSAID", "drugs": [
        "aspirin", "acetylsalicylic acid", "ibuprofen", "naproxen", "diclofenac", "ketorolac", "indomethacin",
        "indometacin", "mefenamic acid", "celecoxib", "etoricoxib", "meloxicam", "piroxicam", "ketoprofen"]},
    "aspirin": {"label": "aspirin", "drugs": ["aspirin", "acetylsalicylic acid"]},
    "sulfonamide": {"label": "sulfonamide antibiotic", "drugs": [
        "sulfamethoxazole", "co-trimoxazole", "trimethoprim-sulfamethoxazole", "sulfadiazine", "sulfasalazine"]},
}

# How allergy entries are written in records, mapped to a class
ALLERGY_CLASSES = {
    "penicillin": "penicillin", "penicillins": "penicillin",
    "cephalosporin": "cephalosporin", "cephalosporins": "cephalosporin",
    "carbapenem": "carbapenem", "carbapenems": "carbapenem",
    "nsaid": "nsaid", "nsaids": "nsaid", "anti-inflammatories": "nsaid",
    "aspirin": "aspirin",
    "sulfa": "sulfonamide", "sulfa drugs": "sulfonamide", "sulpha": "sulfonamide", "sulfonamides": "sulfonamide",
}

# Allergy to one class -> possible cross-reactivity with another (a warning, not a block)
CROSS_REACTIVE = {
    "penicillin": ["cephalosporin", "carbapenem"],
    "cephalosporin": ["penicillin", "carbapenem"],
    "carbapenem": ["penicillin", "cephalosporin"],
    "aspirin": ["nsaid"],
}


def _norm(text):
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _names_in(drug_text, names):
    """Which of these drug names appear as whole words in the prescription text."""
    text = _norm(drug_text)
    return [n for n in names if re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text)]


def drug_classes(drug_text):
    """Classes a prescribed drug belongs to ('Co-amoxiclav 625mg' -> ['penicillin'])."""
    return [c for c, info in CLASSES.items() if _names_in(drug_text, info["drugs"])]


def check_prescription(drug_text, allergies):
    """Findings for one prescribed drug against the patient's allergies.
    Each finding: {"severity": "block" | "warn", "drug", "allergy", "reason"}."""
    findings = []
    drug = str(drug_text or "").strip()
    if not drug:
        return findings
    classes = drug_classes(drug)

    for allergy in allergies or []:
        allergy_name = str(allergy).strip()
        key = _norm(allergy_name)
        if not key:
            continue
        allergen_class = ALLERGY_CLASSES.get(key)

        if allergen_class:
            info = CLASSES[allergen_class]
            if allergen_class in classes:
                severity, reason = "block", (
                    f"{drug} conflicts with the documented {allergy_name} allergy."
                    if _names_in(drug, [key]) else
                    f"{drug} is a{'n' if info['label'][0] in 'aeiouAEIOU' else ''} {info['label']} and the patient is allergic to {allergy_name}.")
            else:
                related = [c for c in CROSS_REACTIVE.get(allergen_class, []) if c in classes]
                if not related:
                    continue
                label = CLASSES[related[0]]["label"]
                severity, reason = "warn", (
                    f"{drug} is a{'n' if label[0] in 'aeiouAEIOU' else ''} {label}; cross-reactivity with the documented "
                    f"{allergy_name} allergy is possible. Confirm it's safe before giving it.")
        else:
            # An allergy to a specific drug: the same drug blocks, others in its class warn
            if _names_in(drug, [key]):
                severity, reason = "block", f"{drug} conflicts with the documented {allergy_name} allergy."
            else:
                shared = [c for c in drug_classes(allergy_name) if c in classes and c != "aspirin"]
                if not shared:
                    continue
                label = CLASSES[shared[0]]["label"]
                severity, reason = "warn", (
                    f"{drug} is in the same class as {allergy_name} ({label}s); cross-reactivity is possible. "
                    f"Confirm it's safe before giving it.")

        findings.append({"severity": severity, "drug": drug, "allergy": allergy_name, "reason": reason})
    return findings


def check_prescriptions(prescriptions, allergies):
    """Findings for every prescription (dicts with 'drug', or plain strings)."""
    findings = []
    for rx in prescriptions or []:
        name = rx.get("drug") or rx.get("medication") or rx.get("name") if isinstance(rx, dict) else rx
        findings += check_prescription(name, allergies)
    return findings
