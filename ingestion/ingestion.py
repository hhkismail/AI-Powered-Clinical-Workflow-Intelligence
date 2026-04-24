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
RAZIN_URL     = os.getenv("MOCK_API_BASE_URL") + "/api/process-note"
TIMEOUT       = int(os.getenv("TIMEOUT_SECONDS", 30))

# ── Set True while api.ilmu.ai is down, False once it's back ──
ZAI_DOWN = True


# ─────────────────────────────────────────────
#  Z.AI helpers
# ─────────────────────────────────────────────

def ocr_image(image_path: str) -> str:
    """Send an image to Z.AI OCR, return extracted text."""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    resp = req.post(
        "https://ocr.z.ai/v1/recognize",
        headers={"Authorization": f"Bearer {ZAI_API_KEY}",
                 "Content-Type": "application/json"},
        json={"image": f"data:{mime};base64,{data}",
              "language": "en", "mode": "medical"},
        timeout=TIMEOUT
    )
    resp.raise_for_status()
    return resp.json().get("text", "")


def transcribe_audio(audio_path: str) -> str:
    """Send an audio file to Z.AI Audio, return transcript."""
    with open(audio_path, "rb") as f:
        resp = req.post(
            "https://audio.z.ai/v1/transcribe",
            headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
            files={"file": (os.path.basename(audio_path), f, "audio/mpeg")},
            data={"language": "en", "domain": "medical"},
            timeout=TIMEOUT
        )
    resp.raise_for_status()
    return resp.json().get("transcript", "")


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

    if "file" in request.files and not ZAI_DOWN:
        uploaded = request.files["file"]
        fname = uploaded.filename.lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(fname)[1]) as tmp:
            uploaded.save(tmp.name)
            tmp_path = tmp.name

        try:
            if fname.endswith((".jpg", ".jpeg", ".png")):
                raw_text = ocr_image(tmp_path)
                input_method = "image"
            elif fname.endswith((".mp3", ".wav", ".m4a")):
                raw_text = transcribe_audio(tmp_path)
                input_method = "audio"
        finally:
            os.unlink(tmp_path)
    
    if not raw_text:
        return jsonify({"error": "No usable text extracted"}), 400  

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