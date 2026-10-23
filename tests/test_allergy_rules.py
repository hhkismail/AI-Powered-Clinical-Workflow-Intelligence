"""Tests for the deterministic allergy rules (Ophia/allergy_rules.py)."""

import pytest

import allergy_rules as rules


def severities(drug, allergies):
    return [f["severity"] for f in rules.check_prescription(drug, allergies)]


@pytest.mark.parametrize("drug, allergies", [
    ("Aspirin", ["Aspirin"]),                        # the allergen itself
    ("Aspirin 300mg", ["aspirin"]),                  # with a dose, any case
    ("Amoxicillin 1g", ["Penicillin"]),              # in the allergen's class
    ("Co-amoxiclav 625mg", ["Penicillins"]),
    ("Piperacillin-tazobactam 4.5g", ["Penicillin"]),
    ("Tazocin", ["Penicillin"]),                     # brand name
    ("Ibuprofen 400mg", ["NSAIDs"]),
    ("Aspirin", ["NSAIDs"]),                         # aspirin is an NSAID
    ("Co-trimoxazole 960mg", ["Sulfa Drugs"]),
    ("Ibuprofen", ["Ibuprofen"]),                    # a specific-drug allergy
])
def test_direct_conflicts_block(drug, allergies):
    assert severities(drug, allergies) == ["block"]


@pytest.mark.parametrize("drug, allergies", [
    ("Meropenem 1g", ["Penicillin"]),                # the case the LLM flip-flopped on
    ("Ceftriaxone 2g", ["Penicillin"]),
    ("Amoxicillin", ["Cephalosporins"]),
    ("Naproxen 500mg", ["Ibuprofen"]),               # same class as a specific-drug allergy
    ("Ibuprofen", ["Aspirin"]),                      # aspirin allergy and other NSAIDs
])
def test_cross_reactivity_warns(drug, allergies):
    assert severities(drug, allergies) == ["warn"]


@pytest.mark.parametrize("drug, allergies", [
    ("Metoprolol 25mg", ["Aspirin"]),
    ("Paracetamol 1g", ["NSAIDs", "Penicillin"]),    # paracetamol isn't an NSAID
    ("Azithromycin", ["Penicillin"]),                # a macrolide, no cross-reactivity
    ("Doxycycline", ["Penicillin", "Sulfa Drugs"]),
    ("Salbutamol", ["Latex", "Peanuts"]),            # non-drug allergies
    ("Amoxicillin", []),
    ("Penicillamine", ["Penicillin"]),               # different drug that only contains the word
])
def test_unrelated_drugs_are_clear(drug, allergies):
    assert severities(drug, allergies) == []


def test_several_allergies_give_one_finding_each():
    findings = rules.check_prescription("Aspirin", ["Aspirin", "NSAIDs", "Latex"])

    assert [(f["allergy"], f["severity"]) for f in findings] == [("Aspirin", "block"), ("NSAIDs", "block")]


def test_reasons_are_readable():
    [block] = rules.check_prescription("Amoxicillin 1g", ["Penicillin"])
    [warn] = rules.check_prescription("Meropenem 1g", ["Penicillin"])

    assert block["reason"] == "Amoxicillin 1g is a penicillin and the patient is allergic to Penicillin."
    assert warn["reason"].startswith("Meropenem 1g is a carbapenem; cross-reactivity with the documented Penicillin allergy")


def test_check_prescriptions_accepts_dicts_and_strings():
    findings = rules.check_prescriptions(
        [{"drug": "Aspirin", "dosage": "300mg"}, "Meropenem 1g", {"drug": "Paracetamol"}], ["Aspirin", "Penicillin"])

    assert [(f["drug"], f["severity"]) for f in findings] == [("Aspirin", "block"), ("Meropenem 1g", "warn")]
