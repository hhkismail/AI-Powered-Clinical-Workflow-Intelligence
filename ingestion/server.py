from flask import Flask, request, jsonify
from flask_cors import CORS
import tempfile, os, requests as req
from datetime import datetime, timezone
from ocr_service import image_to_text
from audio_service import audio_to_text
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

ORCHESTRATOR_URL = os.getenv("MOCK_API_BASE_URL") + "/api/process-note"
TIMEOUT = int(os.getenv("TIMEOUT_SECONDS", 30))

@app.route("/api/process-note", methods=["POST"])
def process_note():
    # --- Step 1: Read form fields ---
    patient_id  = request.form.get("patient_id", "UNKNOWN")
    doctor_id   = request.form.get("doctor_id", "DR-000")
    department  = request.form.get("department", "General")
    priority    = request.form.get("priority", "normal")

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files["file"]
    filename = uploaded_file.filename.lower()

    with tempfile.NamedTemporaryFile(
        delete=False, suffix=os.path.splitext(filename)[1]
    ) as tmp:
        uploaded_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        # --- Step 2: Extract raw text ---
        if filename.endswith((".jpg", ".jpeg", ".png")):
            raw_text = image_to_text(tmp_path)
            input_method = "image"
        elif filename.endswith((".mp3", ".wav", ".m4a")):
            raw_text = audio_to_text(tmp_path)
            input_method = "audio"
        else:
            return jsonify({"error": "Unsupported file type"}), 400

    finally:
        os.unlink(tmp_path)

    # --- Step 3: Build payload ---
    orchestrator_payload = {
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

    # --- Step 4: Send to Razin's API ---
    try:
        resp = req.post(
            ORCHESTRATOR_URL,
            json=orchestrator_payload,
            timeout=TIMEOUT
        )
        return jsonify(resp.json()), resp.status_code

    except req.exceptions.Timeout:
        return jsonify({"error": "Orchestrator timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)