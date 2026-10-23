"""
Start the whole demo with one command: the Mock EMR API, the orchestrator,
the ingestion gateway and the frontend, with their logs in one terminal.

    python tools/start.py              # uses GROQ_API_KEY from .env
    python tools/start.py --mock-ai    # no Groq key needed (see Ophia/mock_llm.py)
    python tools/start.py --open       # also open the clinical notes page

Ctrl+C stops everything. Run it with the Python that has requirements.txt
installed (your .venv).
"""

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from dotenv import dotenv_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "127.0.0.1"

# name, command, working directory, port
SERVICES = [
    ("emr-api", [sys.executable, "server.py"], ROOT, 3001),
    ("orchestrator", [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST, "--port", "8000"],
     os.path.join(ROOT, "Ophia"), 8000),
    ("ingestion", [sys.executable, "ingestion.py"], os.path.join(ROOT, "ingestion"), 5000),
    ("frontend", [sys.executable, "-m", "http.server", "5500", "--bind", HOST, "--directory", "frontend"], ROOT, 5500),
]


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def config_problems(env, mock_ai):
    """What's missing from .env (and the environment) for the demo to work."""
    problems = []
    if not env.get("SUPABASE_URL"):
        problems.append("SUPABASE_URL is not set")
    if not env.get("SUPABASE_SECRET_KEY"):
        problems.append("SUPABASE_SECRET_KEY is not set (the publishable key won't work: every table has RLS)")
    if not mock_ai and not (env.get("GROQ_API_KEY") or env.get("ZAI_API_KEY")):
        problems.append("GROQ_API_KEY is not set (or run with --mock-ai to use the rule-based planner)")
    return problems


def stream(name, process):
    for line in process.stdout:
        print(f"[{name:<12}] {line.rstrip()}", flush=True)


def main():
    # The services log emoji; a console that can't show them gets "?" instead of a crash
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    mock_ai = "--mock-ai" in sys.argv
    env = {**dotenv_values(os.path.join(ROOT, ".env")), **os.environ}
    mock_ai = mock_ai or str(env.get("MOCK_AI", "")).strip().lower() in ("1", "true", "yes", "on")

    problems = config_problems(env, mock_ai)
    busy = [f"port {port} ({name}) is already in use" for name, _, _, port in SERVICES if port_in_use(port)]
    if problems or busy:
        print("Can't start the demo:\n" + "\n".join(f"  - {p}" for p in problems + busy))
        if problems:
            print("See the Environment setup section of README.md.")
        return 1

    child_env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if mock_ai:
        child_env["MOCK_AI"] = "1"

    processes = []
    try:
        for name, command, cwd, _ in SERVICES:
            process = subprocess.Popen(command, cwd=cwd, env=child_env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            processes.append((name, process))
            threading.Thread(target=stream, args=(name, process), daemon=True).start()

        deadline = time.time() + 30
        waiting = {port for *_, port in SERVICES}
        while waiting and time.time() < deadline:
            for name, process in processes:
                if process.poll() is not None:
                    print(f"\n{name} exited (code {process.returncode}); stopping the demo. Its log is above.")
                    return 1
            waiting = {port for port in waiting if not port_in_use(port)}
            time.sleep(0.3)
        if waiting:
            print(f"\nTimed out waiting for port(s) {', '.join(map(str, sorted(waiting)))}; stopping the demo.")
            return 1

        print("\n" + "=" * 60)
        print(f"Ophia is running{' in MOCK AI mode (no Groq calls)' if mock_ai else ''}:")
        print(f"  Clinical notes  http://localhost:5500/index.html")
        print(f"  Ward board      http://localhost:5500/board.html")
        print("Press Ctrl+C to stop all four services.")
        print("=" * 60 + "\n", flush=True)
        if "--open" in sys.argv:
            webbrowser.open("http://localhost:5500/index.html")

        while all(process.poll() is None for _, process in processes):
            time.sleep(0.5)
        name = next(name for name, process in processes if process.poll() is not None)
        print(f"\n{name} stopped unexpectedly; stopping the rest.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping...")
        return 0
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
