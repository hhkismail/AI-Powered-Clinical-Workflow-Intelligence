"""Tests for the one-command launcher's checks (tools/start.py)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import start  # noqa: E402

READY = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "sb_secret_x", "GROQ_API_KEY": "gsk_x"}


def test_complete_config_has_no_problems():
    assert start.config_problems(READY, mock_ai=False) == []


def test_groq_key_is_only_needed_without_mock_ai():
    env = {**READY, "GROQ_API_KEY": ""}

    assert "GROQ_API_KEY is not set" in start.config_problems(env, mock_ai=False)[0]
    assert start.config_problems(env, mock_ai=True) == []


def test_supabase_is_always_needed():
    problems = start.config_problems({}, mock_ai=True)

    assert [p.split(" is")[0] for p in problems] == ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]


def test_every_service_has_its_own_port():
    ports = [port for *_, port in start.SERVICES]

    assert sorted(ports) == [3001, 5000, 5500, 8000]
