from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime, timezone
import requests as req
import base64, os, tempfile

load_dotenv()

app = Flask(__name__)
CORS(app)  # allows your browser dashboard to call this

ZAI_API_KEY   = os.getenv("ZAI_API_KEY")
RAZIN_URL = "http://127.0.0.1:8000/api/process-note"
TIMEOUT       = int(os.getenv("TIMEOUT_SECONDS", 30))

# ── Set True while api.ilmu.ai is down, False once it's back ──
ZAI_DOWN = False


# ─────────────────────────────────────────────
# Groq Vision & Audio Helpers
# ─────────────────────────────────────────────
def ocr_image(image_path: str) -> str:
    """Send an image to Groq Vision, return extracted text."""
    # We use the same Groq key you already put in the .env
    api_key = os.getenv("ZAI_API_KEY") 
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    with open(image_path, "rb") as f:
        base64_image = base64.b64encode(f.read()).decode("utf-8")
        
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    
    # Using Groq's Vision model to read the handwriting/text
    payload = {
        "model": "llama-3.2-11b-vision-preview",
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
    api_key = os.getenv("ZAI_API_KEY")
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    
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

    # 2. Extract raw text
    input_method = "text"
    raw_text = typed_text

    if "file" in request.files :
        uploaded = request.files["file"]
        fname = uploaded.filename.lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(fname)[1]) as tmp:
            uploaded.save(tmp.name)
            tmp_path = tmp.name

        try:
            if fname.endswith((".jpg", ".jpeg", ".png")):
                if ZAI_DOWN:
                    raw_text = "Image uploaded (OCR unavailable)"
                else:
                    raw_text = ocr_image(tmp_path)
                input_method = "image"

            elif fname.endswith((".mp3", ".wav", ".m4a")):
                if ZAI_DOWN:
                    raw_text = "Audio uploaded (transcription unavailable)"
                else:
                    raw_text = transcribe_audio(tmp_path)
                input_method = "audio"
        finally:
            os.unlink(tmp_path)
    
    if not raw_text:
        return jsonify({"error": "Please provide text or upload a valid file"}), 400  

    # 3. Build the exact payload Razin's backend expects
    payload = {
        "metadata": {
            "doctor_id":  doctor_id,
            "patient_id": patient_id,
            "department": department,
            "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "priority":   priority
        },
        "payload": {
            "input_methods_used": [input_method],
            "raw_text": raw_text
        }
    }

    # 4. Forward to Razin's orchestrator
    try:
        resp = req.post(RAZIN_URL, json=payload, timeout=TIMEOUT)
        return jsonify(resp.json()), resp.status_code
    except req.exceptions.Timeout:
        return jsonify({"error": "Razin's server timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Ingestion server running on http://localhost:5000")
    print(f"ZAI_DOWN = {ZAI_DOWN}  (flip to False once api.ilmu.ai recovers)")
    app.run(debug=True, port=5000)