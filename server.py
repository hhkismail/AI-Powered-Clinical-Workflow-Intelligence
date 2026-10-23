import os
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

app = Flask(__name__)
# Enable CORS globally so the browser dashboard isn't blocked
CORS(app)

load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None


def missing_parameter_response(message):
    return jsonify({
        "status": "error",
        "error_code": "MISSING_PARAMETER",
        "message": message
    }), 400


def supabase_unavailable_response():
    return jsonify({
        "status": "error",
        "error_code": "SUPABASE_NOT_CONFIGURED",
        "message": "Supabase credentials are missing from the environment."
    }), 500


def supabase_query_failed_response(message):
    return jsonify({
        "status": "error",
        "error_code": "SUPABASE_QUERY_FAILED",
        "message": message
    }), 500

# 1. Bed Reservation API
@app.route('/api/reserve-bed', methods=['POST'])
def reserve_bed():
    data = request.get_json()
    
    # Exception Handling: Catch missing parameters
    if not data or 'patient_id' not in data or 'ward_type' not in data:
        return missing_parameter_response("The reservation API requires 'patient_id' and 'ward_type'. You sent an incomplete payload.")

    if supabase is None:
        return supabase_unavailable_response()

    patient_id = data['patient_id']
    ward_type = data['ward_type']
    resource_type = str(ward_type).strip().lower()

    # The LLM sends ward types like 'icu' or 'observation'; hospital_resources
    # stores bed types as ICU_BED / GEN_WARD. Observation beds are general ward beds.
    ward_to_resource_map = {
        'icu': 'ICU_BED',
        'icu_bed': 'ICU_BED',
        'observation': 'GEN_WARD',
        'general': 'GEN_WARD',
        'gen_ward': 'GEN_WARD'
    }
    mapped_resource_type = ward_to_resource_map.get(resource_type)

    if mapped_resource_type is None:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_WARD_TYPE",
            "message": f"Unknown ward_type '{ward_type}'. Expected one of: icu, observation, general."
        }), 400

    try:
        bed_result = (
            supabase.table('hospital_resources')
            .select('id, resource_name, wing, resource_type, status')
            .eq('resource_type', mapped_resource_type)
            .eq('status', 'available')
            .limit(1)
            .execute()
        )
        available_beds = bed_result.data or []

        if not available_beds:
            return jsonify({
                "status": "error",
                "error_code": "NO_BEDS_AVAILABLE",
                "message": "No beds are available for the requested ward type."
            }), 400

        bed = available_beds[0]
        # Re-check status in the update so two requests can't take the same bed
        update_result = (
            supabase.table('hospital_resources')
            .update({'status': 'occupied', 'assigned_to_patient': patient_id})
            .eq('id', bed['id'])
            .eq('status', 'available')
            .execute()
        )
        updated_rows = update_result.data or []

        if not updated_rows:
            return jsonify({
                "status": "error",
                "error_code": "NO_BEDS_AVAILABLE",
                "message": "No beds are available for the requested ward type."
            }), 400

        updated_bed = updated_rows[0]

        return jsonify({
            "status": "success",
            "reservation_id": updated_bed['id'],
            "allocation": {
                "ward": updated_bed.get('wing'),
                "bed": updated_bed.get('resource_name'),
                "status": updated_bed.get('status', 'occupied')
            },
            "message": "Bed reserved successfully."
        }), 200
    except Exception as e:
        print(f"[reserve-bed] Supabase error: {e}")
        return supabase_query_failed_response("Unable to reserve a bed from the database.")


# 2. Scheduling API
@app.route('/api/schedule-appointment', methods=['POST'])
def schedule_appointment():
    data = request.get_json(silent=True) or {}

    if not data.get('patient_id'):
        return missing_parameter_response("The scheduling API requires 'patient_id'.")

    if supabase is None:
        return supabase_unavailable_response()

    patient_id = data['patient_id']
    dept = data.get('department') or 'General'
    appointment_id = str(uuid.uuid4())

    # appointment_date must be YYYY-MM-DD; without it, derive the date from timeframe_days
    timeframe_days = data.get('timeframe_days')
    try:
        timeframe_days = int(timeframe_days) if timeframe_days is not None else None
        appointment_date = date.fromisoformat(data['appointment_date']) if data.get('appointment_date') else None
    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "error_code": "INVALID_PARAMETER",
            "message": "'appointment_date' must be YYYY-MM-DD and 'timeframe_days' must be a whole number."
        }), 400

    if appointment_date is None and timeframe_days is not None:
        appointment_date = date.today() + timedelta(days=timeframe_days)

    try:
        supabase.table('appointments').insert({
            'id': appointment_id,
            'patient_id': patient_id,
            'department': dept,
            'appointment_date': appointment_date.isoformat() if appointment_date else None,
            'timeframe_days': timeframe_days,
            'reason': data.get('reason') or 'Routine Checkup'
        }).execute()
    except Exception as e:
        print(f"[schedule-appointment] Supabase error: {e}")
        return supabase_query_failed_response("Unable to save the appointment to the database.")

    return jsonify({
        "status": "success",
        "appointment_id": appointment_id,
        "scheduled_details": {
            "date": appointment_date.isoformat() if appointment_date else None,
            "location": f"{dept} Clinic"
        },
        "message": "Appointment scheduled successfully."
    }), 200


# 3. EMR Update
@app.route('/api/update-record', methods=['POST'])
def update_record():
    data = request.get_json(silent=True) or {}

    if not data.get('patient_id'):
        return missing_parameter_response("The EMR update API requires 'patient_id'.")

    if supabase is None:
        return supabase_unavailable_response()

    structured_data = {
        'diagnoses': data.get('diagnoses', []),
        'prescriptions': data.get('prescriptions', [])
    }
    record_id = str(uuid.uuid4())

    try:
        supabase.table('clinical_notes').insert({
            'id': record_id,
            'patient_id': data['patient_id'],
            # Stored as a JSON object (jsonb), not a JSON-encoded string
            'structured_data': structured_data
        }).execute()
    except Exception as e:
        print(f"[update-record] Supabase error: {e}")
        return supabase_query_failed_response("Unable to save the clinical note to the database.")

    # The frontend reads the extracted diagnoses/prescriptions back from 'params'
    return jsonify({
        "status": "success",
        "record_id": record_id,
        "message": "Patient EMR successfully updated.",
        "params": structured_data  
    }), 200

# 4. Fetch Patient Profile (Read)
@app.route('/api/patient/<patient_id>', methods=['GET'])
def get_patient(patient_id):
    if supabase is None:
        return supabase_unavailable_response()

    try:
        result = (
            supabase.table('patients')
            .select('name, age, allergies, active_prescriptions, medical_history')
            .eq('patient_id', patient_id)
            .execute()
        )
        patient_rows = result.data or []

        if not patient_rows:
            return jsonify({
                "status": "error",
                "error_code": "PATIENT_NOT_FOUND",
                "message": "No patient record was found for the requested patient_id."
            }), 404

        patient = patient_rows[0]

        return jsonify({
            "status": "success",
            "patient_id": patient_id,
            "name": patient.get('name'),
            "age": patient.get('age'),
            "allergies": patient.get('allergies'),
            "active_prescriptions": patient.get('active_prescriptions'),
            "medical_history": patient.get('medical_history')
        }), 200
    except Exception:
        return supabase_query_failed_response("Unable to fetch the patient record from the database.")

# 5. Check Ward Availability (Read)
@app.route('/api/ward-availability', methods=['GET'])
def get_ward_availability():
    if supabase is None:
        return supabase_unavailable_response()

    try:
        result = (
            supabase.table('hospital_resources')
            .select('wing, status')
            .execute()
        )
        rows = result.data or []

        grouped_wards = {}
        for row in rows:
            wing = row.get('wing')
            status = row.get('status')
            if wing is None:
                continue
            if wing not in grouped_wards:
                grouped_wards[wing] = 0
            if status == 'available':
                grouped_wards[wing] += 1

        wards = [
            {"wing": wing, "available_beds": grouped_wards[wing]}
            for wing in sorted(grouped_wards)
        ]

        return jsonify({
            "status": "success",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "wards": wards
        }), 200
    except Exception:
        return supabase_query_failed_response("Unable to fetch ward availability from the database.")

# The root route MUST be above the app.run block
@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "status": "success",
        "version": "1.0.0"
    }), 200

if __name__ == '__main__':
    # Runs the server on port 3001 to avoid conflicts. Set FLASK_DEBUG=1 to enable the debugger locally.
    app.run(port=3001, debug=os.getenv("FLASK_DEBUG") == "1")