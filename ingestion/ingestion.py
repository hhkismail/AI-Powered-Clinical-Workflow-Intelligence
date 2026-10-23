from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timezone
import requests as req
import base64, hashlib, os, sys, tempfile

load_dotenv()

# Write log lines straight away, even when output is redirected to a file
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)
CORS(app)  # allows your browser dashboard to call this

# GROQ_API_KEY, falling back to the legacy ZAI_API_KEY name
GROQ_API_KEY     = os.getenv("GROQ_API_KEY") or os.getenv("ZAI_API_KEY")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000/api/process-note")
TIMEOUT          = int(os.getenv("TIMEOUT_SECONDS", 30))
# Only image-capable model on Groq at the moment (preview, so it may be busy or retired)
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "samples")
MEDIA = (".jpg", ".jpeg", ".png", ".mp3", ".wav", ".m4a")


def mock_ai_enabled() -> bool:
    """MOCK_AI=1: no Groq calls (see Ophia/mock_llm.py)."""
    return os.getenv("MOCK_AI", "").strip().lower() in ("1", "true", "yes", "on")


def sample_transcript(path: str):
    """The stored transcript of a bundled sample (docs/samples/<name>.txt), matched
    by file content, or None. Mock AI mode has no OCR or speech model, so these
    are the only uploads it can read."""
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).digest()
    for name in sorted(os.listdir(SAMPLES_DIR)):
        base, ext = os.path.splitext(name)
        transcript = os.path.join(SAMPLES_DIR, base + ".txt")
        if ext.lower() in MEDIA and os.path.exists(transcript):
            with open(os.path.join(SAMPLES_DIR, name), "rb") as f:
                if hashlib.sha256(f.read()).digest() == digest:
                    with open(transcript, encoding="utf-8") as t:
                        return t.read()
    return None


# ─────────────────────────────────────────────
# Groq Vision & Audio Helpers
# ─────────────────────────────────────────────
def ocr_image(image_path: str) -> str:
    """Send an image to Groq Vision, return extracted text."""
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")
        
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    
    # Using Groq's Vision model to read the handwriting/text
    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all the text from this clinical note exactly as written. Do not add any conversational text, just return the medical note."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.0
    }
    
    resp = req.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


def transcribe_audio(audio_path: str) -> str:
    """Send an audio file to Groq Whisper, return transcript."""
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    
    # Using Groq's Whisper model for instant audio transcription
    with open(audio_path, "rb") as f:
        files = {
            "file": (os.path.basename(audio_path), f, "audio/mpeg")
        }
        data = {
            "model": "whisper-large-v3",
            "language": "en"
        }
        resp = req.post(url, headers=headers, files=files, data=data, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("text", "")


# ─────────────────────────────────────────────
#  Main endpoint — called by your dashboard
# ─────────────────────────────────────────────

@app.route("/api/process-note", methods=["POST"])
def process_note():

    # 1. Read fields sent by the dashboard form
    patient_id  = request.form.get("patient_id", "").strip()
    doctor_id   = request.form.get("doctor_id", "").strip()
    department  = request.form.get("department", "General")
    priority    = request.form.get("priority", "normal")
    typed_text  = request.form.get("typed_text", "").strip()

    if not patient_id or not doctor_id:
        return jsonify({"error": "patient_id and doctor_id are required"}), 400

    # 2. Extract raw text. Typed text and an uploaded file are combined, so
    # context typed alongside a photo or voice memo isn't lost.
    input_methods = ["text"] if typed_text else []
    extracted = ""

    if "file" in request.files :
        uploaded = request.files["file"]
        fname = uploaded.filename.lower()

        needs_groq = fname.endswith(MEDIA)
        if needs_groq and not GROQ_API_KEY and not mock_ai_enabled():
            return jsonify({"error": "GROQ_API_KEY is not set, so image/audio uploads can't be processed. Add your Groq key to .env."}), 500

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(fname)[1]) as tmp:
            uploaded.save(tmp.name)
            tmp_path = tmp.name

        try:
            if needs_groq and mock_ai_enabled():
                extracted = sample_transcript(tmp_path)
                if extracted is None:
                    return jsonify({"error": "Mock AI mode can only read the sample files in docs/samples, since there's "
                                             "no OCR or speech model without a Groq key. Type the note instead."}), 400
                input_methods.append("audio" if fname.endswith((".mp3", ".wav", ".m4a")) else "image")

            elif fname.endswith((".jpg", ".jpeg", ".png")):
                extracted = ocr_image(tmp_path)
                input_methods.append("image")

            elif fname.endswith((".mp3", ".wav", ".m4a")):
                extracted = transcribe_audio(tmp_path)
                input_methods.append("audio")
        except req.exceptions.RequestException as e:
            return jsonify({"error": f"Groq OCR/transcription request failed: {e}"}), 502
        finally:
            os.unlink(tmp_path)
    
    raw_text = "\n\n".join(part for part in (typed_text, (extracted or "").strip()) if part)
    if not raw_text:
        return jsonify({"error": "Please provide text or upload a valid file"}), 400

    # 3. Build the payload the orchestrator expects (ProcessNoteRequest in Ophia/main.py)
    payload = {
        "metadata": {
            "doctor_id":  doctor_id,
            "patient_id": patient_id,
            "department": department,
            "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "priority":   priority
        },
        "payload": {
            "input_methods_used": input_methods,
            "raw_text": raw_text
        }
    }

    # 4. Forward to the orchestrator
    try:
        resp = req.post(ORCHESTRATOR_URL, json=payload, timeout=TIMEOUT)
        return jsonify(resp.json()), resp.status_code
    except req.exceptions.Timeout:
        return jsonify({"error": "The orchestrator timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Ingestion server running on http://localhost:5000")
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)