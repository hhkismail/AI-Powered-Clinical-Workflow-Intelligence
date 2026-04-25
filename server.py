import os
import json
import uuid
import random

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

app = Flask(__name__)
# Enable CORS globally so Fitri and Anna's frontend doesn't get blocked
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

    ward_to_resource_map = {
        'observation': 'observation',
        'general': 'general',
        'icu': 'icu'
    }
    mapped_resource_type = ward_to_resource_map.get(resource_type, resource_type)

    try:
        bed_result = (
            supabase.table('hospital_resources')
            .select('id, wing, bed_number, resource_type, status')
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
        update_query = (
            supabase.table('hospital_resources')
            .update({'status': 'occupied', 'assigned_to_patient': patient_id})
            .eq('status', 'available')
        )

        if bed.get('id') is not None:
            update_query = update_query.eq('id', bed['id'])
        elif bed.get('bed_number') is not None:
            update_query = update_query.eq('bed_number', bed['bed_number'])
        else:
            return jsonify({
                "status": "error",
                "error_code": "BED_IDENTIFIER_MISSING",
                "message": "The available bed record is missing an identifier."
            }), 500

        update_result = update_query.execute()
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
            "reservation_id": f"RES-{updated_bed.get('id', updated_bed.get('bed_number', 'UNKNOWN'))}",
            "allocation": {
                "ward": updated_bed.get('wing', bed.get('wing')),
                "bed_number": updated_bed.get('bed_number', bed.get('bed_number')),
                "status": updated_bed.get('status', 'occupied')
            },
            "message": "Bed reserved successfully."
        }), 200
    except Exception:
        return supabase_query_failed_response("Unable to reserve a bed from the database.")


# 2. Scheduling API
@app.route('/api/schedule-appointment', methods=['POST'])
def schedule_appointment():
    data = request.get_json()
    print(f"DEBUG PAYLOAD: {data}")

    missing_fields = []
    if not data:
        missing_fields = ['patient_id', 'department', 'appointment_date', 'timeframe_days', 'reason']
    else:
        for field in ['patient_id', 'department', 'appointment_date', 'timeframe_days', 'reason']:
            if field not in data:
                missing_fields.append(field)

    if missing_fields:
        print(f"DEBUG VALIDATION FAILED: missing_fields={missing_fields}")
        return missing_parameter_response("The scheduling API requires 'patient_id', 'department', 'appointment_date', 'timeframe_days', and 'reason'. You sent an incomplete payload.")

    if supabase is None:
        return supabase_unavailable_response()

    patient_id = data['patient_id']
    department = data['department']
    appointment_date = data['appointment_date']
    timeframe_days = data['timeframe_days']
    reason = data['reason']
    appointment_uuid = str(uuid.uuid4())

    try:
        supabase.table('patients').upsert({
            'patient_id': patient_id,
            'name': 'New Patient'
        }).execute()
        
        supabase.table('appointments').insert({
            'id': appointment_uuid,
            'patient_id': patient_id,
            'department': department,
            'appointment_date': appointment_date,
            'timeframe_days': timeframe_days,
            'reason': reason
        }).execute()
    except Exception:
        return supabase_query_failed_response("Unable to schedule the appointment in the database.")

    room_number = random.randint(1, 10)

    return jsonify({
        "status": "success",
        "appointment_id": appointment_uuid,
        "scheduled_details": {
            "date": "2026-05-05",
            "time": "10:30 AM",
            "location": f"{department} Clinic, Room {room_number}"
        },
        "message": "Appointment scheduled and SMS confirmation queued."
    }), 200


# 3. Clinical Structuring API (EMR Update)
@app.route('/api/update-record', methods=['POST'])
def update_record():
    data = request.get_json()

    if not data or 'patient_id' not in data or 'diagnoses' not in data or 'prescriptions' not in data:
        return missing_parameter_response("The EMR update API requires 'patient_id', 'diagnoses', and 'prescriptions'. You sent an incomplete payload.")

    if supabase is None:
        return supabase_unavailable_response()

    patient_id = data['patient_id']
    record_uuid = str(uuid.uuid4())
    diagnoses = data['diagnoses']
    prescriptions = data['prescriptions']
    structured_data = {
        'diagnoses': diagnoses,
        'prescriptions': prescriptions
    }

    try:
        supabase.table('patients').upsert({
            'patient_id': patient_id,
            'name': 'New Patient'
        }).execute()
        
        supabase.table('clinical_notes').insert({
            'id': record_uuid,
            'patient_id': patient_id,
            'raw_input': json.dumps(data),
            'structured_data': json.dumps(structured_data)
        }).execute()
    except Exception:
        return supabase_query_failed_response("Unable to update the patient record in the database.")

    return jsonify({
        "status": "success",
        "record_id": record_uuid,
        "drug_interaction_warning": False,
        "message": "Patient EMR successfully updated."
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
            "timestamp": "2026-04-23T08:00:00Z",
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
    # Runs the server on port 3000
    app.run(port=3000, debug=True)