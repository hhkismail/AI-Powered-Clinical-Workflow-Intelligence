"""
The public demo's AI budget (PUBLIC_DEMO=1, set on Vercel).

Groq's free tier allows about five notes a minute for the whole key, so one
visitor submitting notes in a loop would break the demo for everyone. Each note
is logged in note_requests (with a hashed client address, never the address
itself) and:

  - over the per-visitor or site-wide LLM budget -> planned by the mock AI
    instead, and the page says why;
  - over the per-visitor hard limit -> refused, so the database can't be flooded.

The log lives in Supabase because Vercel runs several instances that share no
memory. The nightly reset clears it.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone

VISITOR_LLM_NOTES = 5        # per visitor per 10 minutes on the real LLM
SITE_LLM_NOTES_PER_MINUTE = 4  # across everyone, under Groq's free-tier limit
VISITOR_HARD_LIMIT = 30      # per visitor per hour, then refused

LLM, MOCK, REFUSE = "llm", "mock", "refuse"

REASONS = {
    "visitor": "You've used this demo's AI budget for the next few minutes, so this note was planned by the "
               "keyword rules instead.",
    "site": "The demo's shared AI budget is busy right now, so this note was planned by the keyword rules instead.",
}
UPLOAD_REASONS = {
    "visitor": "You've used this demo's AI budget for the next few minutes",
    "site": "The demo's shared AI budget is busy right now",
}


def enabled() -> bool:
    return os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def client_key(headers, remote_addr) -> str:
    """A hash of the visitor's address (Vercel puts the real one in x-real-ip / x-forwarded-for)."""
    address = headers.get("x-real-ip") or (headers.get("x-forwarded-for") or "").split(",")[0].strip() or remote_addr
    salt = os.getenv("CRON_SECRET", "")
    return hashlib.sha256(f"{salt}:{address}".encode()).hexdigest()[:32]


def _count_since(supabase, since, client=None):
    query = supabase.table("note_requests").select("created_at").gte("created_at", since.isoformat())
    if client:
        query = query.eq("client", client)
    return len(query.execute().data)


def decide(supabase, client, now=None):
    """(LLM | MOCK | REFUSE, reason key or None) for this visitor's next note, and log it."""
    now = now or datetime.now(timezone.utc)
    if _count_since(supabase, now - timedelta(hours=1), client) >= VISITOR_HARD_LIMIT:
        return REFUSE, None
    if _count_since(supabase, now - timedelta(minutes=10), client) >= VISITOR_LLM_NOTES:
        decision, reason = MOCK, "visitor"
    elif _count_since(supabase, now - timedelta(minutes=1)) >= SITE_LLM_NOTES_PER_MINUTE:
        decision, reason = MOCK, "site"
    else:
        decision, reason = LLM, None
    supabase.table("note_requests").insert({"client": client, "ai": decision, "created_at": now.isoformat()}).execute()
    return decision, reason
