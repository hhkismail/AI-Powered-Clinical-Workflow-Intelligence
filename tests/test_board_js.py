"""
Tests for the ward board's rendering (frontend/board.js), run in QuickJS.

board.js keeps rendering in pure functions (data in, HTML out) and only starts
its browser controller when `document` exists, so it can be loaded here as-is.
"""

import json
import os

import pytest

quickjs = pytest.importorskip("quickjs")

BOARD_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "board.js")

RAJESH_BED = {
    "id": "RES-NEURO-01", "name": "Observation Bed 01", "type": "GEN_WARD",
    "department": "Neurology", "status": "occupied",
    "patient": {
        "patient_id": "PT-30554", "name": "Rajesh Kumar", "age": 62, "allergies": ["Aspirin"],
        "medical_history": "Post-MI", "acuity": "serious", "acuity_updated_at": "2026-10-23T08:00:00Z",
        "medications": [
            {"drug": "Heparin", "dose": "5000 units", "route": "iv", "frequency": "continuous"},
            {"drug": "Metoprolol", "dose": "25mg", "route": "oral", "frequency": None},
        ],
        "tasks": [
            {"id": "t2", "description": "Prep for echo", "category": "prep", "status": "suggested", "suggested_by": "ai"},
            {"id": "t1", "description": "Telemetry", "category": "monitoring", "status": "accepted",
             "suggested_by": "ai", "decided_by": "DR-7742"},
        ],
    },
}
CLEANING_BED = {"id": "RES-CARD-01", "name": "Bay 04", "type": "GEN_WARD", "department": "Cardiology",
                "status": "cleaning", "patient": None}


def board_with(*beds, summary=None):
    return {"summary": summary or {"beds": {"available": 0, "occupied": 1, "cleaning": 1, "maintenance": 0},
                                   "critical_patients": 0, "pending_suggestions": 1},
            "wards": [{"wing": "Observation Wing B", "beds": list(beds)}]}


@pytest.fixture(scope="module")
def js():
    ctx = quickjs.Context()
    with open(BOARD_JS, encoding="utf-8") as f:
        ctx.eval(f.read())

    def call(fn, *args):
        return ctx.eval(f"({fn})(...{json.dumps(list(args))})")
    return call


def test_occupied_card_shows_patient_acuity_allergies_and_iv_line(js):
    html = js("renderBedCard", RAJESH_BED)

    assert "Rajesh Kumar" in html and "acuity-serious" in html and ">Serious<" in html
    assert "Allergic to Aspirin" in html
    assert '<span class="med med-iv"><span class="route">IV</span><b>Heparin</b>5000 units</span>' in html
    assert "1 to review" in html
    assert "1 task in progress" in html


def test_card_without_acuity_says_not_assessed(js):
    bed = json.loads(json.dumps(RAJESH_BED))
    bed["patient"]["acuity"] = None

    assert "Not assessed" in js("renderBedCard", bed)


def test_open_card_is_highlighted(js):
    assert "is-open" in js("renderBedCard", RAJESH_BED, "RES-NEURO-01")
    assert "is-open" not in js("renderBedCard", RAJESH_BED, "RES-ICU-01")


def test_cleaning_bed_offers_mark_clean_and_no_patient(js):
    html = js("renderBedCard", CLEANING_BED)

    assert 'data-action="mark-clean" data-bed="RES-CARD-01"' in html
    assert "Being cleaned" in html
    assert 'data-action="open"' not in html


def test_panel_offers_accept_reject_for_suggestions_and_done_for_accepted(js):
    html = js("renderPanel", RAJESH_BED, 0)

    assert 'data-decision="accept" data-task="t2"' in html
    assert 'data-decision="reject" data-task="t2"' in html
    assert 'data-decision="done" data-task="t1"' in html
    assert 'data-decision="accept" data-task="t1"' not in html
    assert "Accepted by DR-7742" in html
    assert "continuous" in html   # frequency is shown in the drawer


def test_llm_and_database_text_is_escaped(js):
    bed = json.loads(json.dumps(RAJESH_BED))
    bed["patient"]["name"] = "<img src=x onerror=alert(1)>"
    bed["patient"]["acuity"] = "critical"
    bed["patient"]["tasks"][0]["description"] = "<script>steal()</script>"
    bed["patient"]["medications"][0]["drug"] = '"><b>bold</b>'

    for html in (js("renderBedCard", bed), js("renderPanel", bed, 0), js("renderSummary", board_with(bed))):
        assert "<img" not in html and "<script>" not in html and "<b>bold" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_summary_names_critical_patients(js):
    bed = json.loads(json.dumps(RAJESH_BED))
    bed["patient"]["acuity"] = "critical"
    board = board_with(bed, CLEANING_BED, summary={"beds": {"available": 2, "occupied": 3, "cleaning": 1, "maintenance": 0},
                                                   "critical_patients": 1, "pending_suggestions": 4})

    html = js("renderSummary", board)

    assert "2<span> / 6</span>" in html
    assert "1 bed being cleaned" in html
    assert "kpi-critical" in html and "Rajesh Kumar" in html
    assert "Waiting on a clinician" in html


def test_summary_when_nothing_is_pending(js):
    html = js("renderSummary", board_with(CLEANING_BED, summary={"beds": {"available": 1}, "critical_patients": 0,
                                                                 "pending_suggestions": 0}))

    assert "No critical patients" in html and "All reviewed" in html


def test_board_groups_cards_by_wing(js):
    html = js("renderBoard", board_with(RAJESH_BED, CLEANING_BED))

    assert "<h2>Observation Wing B <span>0 of 2 free</span></h2>" in html and "Rajesh Kumar" in html


@pytest.mark.parametrize("seconds, expected", [(5, "5s ago"), (180, "3 min ago"), (7200, "2 h ago"), (172800, "2 d ago")])
def test_relative_time(js, seconds, expected):
    now = 1_800_000_000_000
    iso = js("(ms) => new Date(ms).toISOString()", now - seconds * 1000)
    assert js("relativeTime", iso, now) == expected
