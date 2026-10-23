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
def server_supabase_key():
    """Server-side, so prefer the secret key: the ward board tables have row-level
    security that blocks the publishable key. Falls back for older .env files."""
    return os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_KEY")


supabase_key = server_supabase_key()
supabase = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None

# Free-text routes and categories from the LLM, mapped to the values the
# medication_orders / care_tasks check constraints allow
ROUTE_ALIASES = {
    'oral': 'oral', 'orally': 'oral', 'po': 'oral', 'by mouth': 'oral',
    'iv': 'iv', 'intravenous': 'iv', 'intravenously': 'iv', 'iv infusion': 'iv', 'iv drip': 'iv', 'iv push': 'iv',
    'im': 'im', 'intramuscular': 'im', 'intramuscularly': 'im',
    'sc': 'subcutaneous', 'sq': 'subcutaneous', 'subcut': 'subcutaneous', 'subcutaneous': 'subcutaneous',
    'inhaled': 'inhaled', 'inhalation': 'inhaled', 'nebulised': 'inhaled', 'nebulized': 'inhaled',
    'topical': 'topical', 'topically': 'topical'
}
TASK_CATEGORIES = {'prep', 'monitoring', 'lab', 'imaging', 'consult', 'medication', 'other'}
ACUITY_LEVELS = {'critical', 'serious', 'stable'}


def normalize_route(route):
    if not route:
        return None
    return ROUTE_ALIASES.get(str(route).strip().lower(), 'other')


def medication_key(order):
    """Identity of a medication order for de-duplication: drug, dose and route."""
    normalize = lambda v: ' '.join(str(v or '').lower().split())
    return normalize(order.get('drug')), normalize(order.get('dose')).replace(' ', ''), order.get('route')


def task_key(task):
    """Identity of a care task for de-duplication: its description, ignoring case and spacing."""
    return ' '.join(str(task.get('description') or '').lower().split()).rstrip('.')


def medication_order_rows(patient_id, prescriptions, note_id):
    rows = []
    for rx in prescriptions or []:
        rx = rx if isinstance(rx, dict) else {'drug': str(rx)}
        drug = rx.get('drug') or rx.get('medication') or rx.get('name')
        if not drug:
            continue
        rows.append({
            'patient_id': patient_id,
            'drug': str(drug),
            'dose': rx.get('dosage') or rx.get('dose'),
            'route': normalize_route(rx.get('route')),
            'frequency': rx.get('frequency'),
            'status': 'active',
            'source_note_id': note_id
        })
    return rows


def care_task_rows(patient_id, next_steps, note_id):
    rows = []
    for step in next_steps or []:
        step = step if isinstance(step, dict) else {'description': str(step)}
        if not step.get('description'):
            continue
        category = str(step.get('category') or 'other').strip().lower()
        rows.append({
            'patient_id': patient_id,
            'description': str(step['description']),
            'category': category if category in TASK_CATEGORIES else 'other',
            'status': 'suggested',      # a clinician has to accept it on the ward board
            'suggested_by': 'ai',
            'source_note_id': note_id
        })
    return rows


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
        # A patient holds one bed. Asking again for the same kind of bed (e.g. a
        # follow-up note) returns the current one; a different kind is a transfer.
        current_beds = (
            supabase.table('hospital_resources')
            .select('id, resource_name, wing, resource_type, status')
            .eq('assigned_to_patient', patient_id)
            .eq('status', 'occupied')
            .execute()
        ).data or []
        same_type = [b for b in current_beds if b['resource_type'] == mapped_resource_type]
        if same_type:
            bed = same_type[0]
            return jsonify({
                "status": "success",
                "reservation_id": bed['id'],
                "allocation": {"ward": bed.get('wing'), "bed": bed.get('resource_name'), "status": "occupied"},
                "already_assigned": True,
                "message": "The patient already has a bed of this type; no new bed was reserved."
            }), 200

        available_beds = (
            supabase.table('hospital_resources')
            .select('id, resource_name, wing, resource_type, status')
            .eq('resource_type', mapped_resource_type)
            .eq('status', 'available')
            .execute()
        ).data or []
        # Observation and general beds share GEN_WARD; when the note asks for
        # observation, prefer a bed in an observation area before any other
        if resource_type == 'observation':
            available_beds.sort(key=lambda b: 'observation' not in
                                f"{b.get('wing') or ''} {b.get('resource_name') or ''}".lower())

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

        # Transfer: free the patient's previous bed. It needs cleaning before reuse.
        for old_bed in current_beds:
            supabase.table('hospital_resources') \
                .update({'status': 'cleaning', 'assigned_to_patient': None}) \
                .eq('id', old_bed['id']).execute()

        return jsonify({
            "status": "success",
            "reservation_id": updated_bed['id'],
            "allocation": {
                "ward": updated_bed.get('wing'),
                "bed": updated_bed.get('resource_name'),
                "status": updated_bed.get('status', 'occupied')
            },
            "transferred_from": [b['id'] for b in current_beds] or None,
            "message": "Bed reserved successfully." + (" Previous bed released for cleaning." if current_beds else "")
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

    patient_id = data['patient_id']
    acuity = str(data.get('acuity') or '').strip().lower() or None
    if acuity is not None and acuity not in ACUITY_LEVELS:
        acuity = None

    structured_data = {
        'diagnoses': data.get('diagnoses', []),
        'prescriptions': data.get('prescriptions', []),
        'acuity': acuity,
        'next_steps': data.get('next_steps', []),
        # Kept for the audit trail: why the AI chose these actions
        'reasoning': data.get('reasoning')
    }
    record_id = str(uuid.uuid4())

    try:
        supabase.table('clinical_notes').insert({
            'id': record_id,
            'patient_id': patient_id,
            'raw_input': data.get('raw_input'),
            # Stored as a JSON object (jsonb), not a JSON-encoded string
            'structured_data': structured_data
        }).execute()
    except Exception as e:
        print(f"[update-record] Supabase error: {e}")
        return supabase_query_failed_response("Unable to save the clinical note to the database.")

    # Ward board data. The note is already saved, so a failure here is
    # reported as partial rather than silently dropped.
    medications = medication_order_rows(patient_id, data.get('prescriptions'), record_id)
    tasks = care_task_rows(patient_id, data.get('next_steps'), record_id)
    try:
        # A follow-up note often repeats current prescriptions and plans;
        # don't duplicate active orders or tasks that are still open
        active = supabase.table('medication_orders').select('drug, dose, route') \
            .eq('patient_id', patient_id).eq('status', 'active').execute().data or []
        active_keys = {medication_key(m) for m in active}
        medications = [m for m in medications if medication_key(m) not in active_keys]

        open_tasks = [t for status in ('suggested', 'accepted') for t in (
            supabase.table('care_tasks').select('description')
            .eq('patient_id', patient_id).eq('status', status).execute().data or [])]
        seen = {task_key(t) for t in open_tasks}
        unique_tasks = []
        for t in tasks:
            if task_key(t) not in seen:
                seen.add(task_key(t))     # also drops repeats within the same note
                unique_tasks.append(t)
        tasks = unique_tasks

        if medications:
            supabase.table('medication_orders').insert(medications).execute()
        if tasks:
            supabase.table('care_tasks').insert(tasks).execute()
        if acuity:
            supabase.table('patients').update({
                'acuity': acuity,
                'acuity_updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('patient_id', patient_id).execute()
    except Exception as e:
        print(f"[update-record] Supabase error writing ward board data: {e}")
        return supabase_query_failed_response(
            f"Clinical note {record_id} was saved, but its medications, tasks or acuity could not be.")

    # The frontend reads the extracted diagnoses/prescriptions back from 'params'
    return jsonify({
        "status": "success",
        "record_id": record_id,
        "message": "Patient EMR successfully updated.",
        "params": structured_data,
        "medication_orders_created": len(medications),
        "care_tasks_suggested": len(tasks)
    }), 200

# 4. Fetch Patient Profile (Read)
@app.route('/api/patient/<patient_id>', methods=['GET'])
def get_patient(patient_id):
    if supabase is None:
        return supabase_unavailable_response()

    try:
        result = (
            supabase.table('patients')
            .select('name, age, allergies, active_prescriptions, medical_history, acuity, acuity_updated_at')
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
        # Current ward state, so the notes page can show context before a note is written
        beds = supabase.table('hospital_resources').select('id, resource_name, wing') \
            .eq('assigned_to_patient', patient_id).eq('status', 'occupied').execute().data or []
        medications = supabase.table('medication_orders').select('drug, dose, route, frequency') \
            .eq('patient_id', patient_id).eq('status', 'active').execute().data or []

        return jsonify({
            "status": "success",
            "patient_id": patient_id,
            "name": patient.get('name'),
            "age": patient.get('age'),
            "allergies": patient.get('allergies'),
            "active_prescriptions": patient.get('active_prescriptions'),
            "medical_history": patient.get('medical_history'),
            "acuity": patient.get('acuity'),
            "acuity_updated_at": patient.get('acuity_updated_at'),
            "bed": beds[0] if beds else None,
            "medication_orders": medications
        }), 200
    except Exception as e:
        print(f"[patient] Supabase error: {e}")
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

# 6. Ward Board (Read): every bed with its patient, active medications and open tasks
@app.route('/api/ward-board', methods=['GET'])
def get_ward_board():
    if supabase is None:
        return supabase_unavailable_response()

    try:
        resources = supabase.table('hospital_resources') \
            .select('id, resource_name, resource_type, department, wing, status, assigned_to_patient') \
            .execute().data or []
        patient_ids = sorted({r['assigned_to_patient'] for r in resources if r.get('assigned_to_patient')})

        # One query per table for the whole board, not one per bed
        patients, medications, tasks = {}, {}, {}
        if patient_ids:
            for p in supabase.table('patients') \
                    .select('patient_id, name, age, allergies, medical_history, acuity, acuity_updated_at') \
                    .in_('patient_id', patient_ids).execute().data or []:
                patients[p['patient_id']] = p
            for m in supabase.table('medication_orders') \
                    .select('id, patient_id, drug, dose, route, frequency, started_at') \
                    .in_('patient_id', patient_ids).eq('status', 'active').execute().data or []:
                medications.setdefault(m['patient_id'], []).append(m)
            for t in supabase.table('care_tasks') \
                    .select('id, patient_id, description, category, status, suggested_by, created_at, decided_at, decided_by') \
                    .in_('patient_id', patient_ids).in_('status', ['suggested', 'accepted']).execute().data or []:
                tasks.setdefault(t['patient_id'], []).append(t)
    except Exception as e:
        print(f"[ward-board] Supabase error: {e}")
        return supabase_query_failed_response("Unable to load the ward board from the database.")

    wings = {}
    for r in sorted(resources, key=lambda r: r['id']):
        patient = None
        pid = r.get('assigned_to_patient')
        if pid and pid in patients:
            patient = dict(patients[pid])
            # IV lines first: they're what nurses check most often
            patient['medications'] = sorted(medications.get(pid, []),
                                            key=lambda m: (m.get('route') != 'iv', m.get('started_at') or ''))
            # Suggestions waiting for a decision first, then accepted work
            patient['tasks'] = sorted(tasks.get(pid, []),
                                      key=lambda t: (t['status'] != 'suggested', t.get('created_at') or ''))
        wings.setdefault(r.get('wing') or 'Unassigned', []).append({
            'id': r['id'],
            'name': r.get('resource_name'),
            'type': r.get('resource_type'),
            'department': r.get('department'),
            'status': r.get('status'),
            'patient': patient
        })

    beds = [b for wing in wings.values() for b in wing]
    occupants = [b['patient'] for b in beds if b['patient']]
    return jsonify({
        "status": "success",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "beds": {s: sum(b['status'] == s for b in beds) for s in ('available', 'occupied', 'cleaning', 'maintenance')},
            "critical_patients": sum(p.get('acuity') == 'critical' for p in occupants),
            "pending_suggestions": sum(t['status'] == 'suggested' for p in occupants for t in p['tasks'])
        },
        "wards": [{"wing": wing, "beds": wings[wing]} for wing in sorted(wings)]
    }), 200


# 7. Care Task Decision (Write): a clinician accepts/rejects an AI suggestion, or completes a task
TASK_TRANSITIONS = {
    # decision: (required current status, new status, timestamp column)
    'accept': ('suggested', 'accepted', 'decided_at'),
    'reject': ('suggested', 'rejected', 'decided_at'),
    'done':   ('accepted', 'done', 'completed_at')
}


@app.route('/api/tasks/<task_id>/decision', methods=['POST'])
def decide_task(task_id):
    data = request.get_json(silent=True) or {}
    decision = str(data.get('decision') or '').strip().lower()
    clinician_id = str(data.get('clinician_id') or '').strip()

    if decision not in TASK_TRANSITIONS:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_DECISION",
            "message": "'decision' must be one of: accept, reject, done."
        }), 400
    if not clinician_id:
        return missing_parameter_response("A task decision requires 'clinician_id', so it's clear who made it.")
    if supabase is None:
        return supabase_unavailable_response()

    current_status, new_status, timestamp_column = TASK_TRANSITIONS[decision]
    changes = {'status': new_status, timestamp_column: datetime.now(timezone.utc).isoformat()}
    if decision in ('accept', 'reject'):
        changes['decided_by'] = clinician_id

    try:
        # Only moves from the expected status, so two clinicians can't both decide the same task
        updated = supabase.table('care_tasks').update(changes) \
            .eq('id', task_id).eq('status', current_status).execute().data or []
        if updated:
            return jsonify({"status": "success", "task": updated[0]}), 200

        existing = supabase.table('care_tasks').select('id, status').eq('id', task_id).execute().data or []
    except Exception as e:
        print(f"[task-decision] Supabase error: {e}")
        return supabase_query_failed_response("Unable to update the care task.")

    if not existing:
        return jsonify({"status": "error", "error_code": "TASK_NOT_FOUND",
                        "message": f"No care task with id {task_id}."}), 404
    return jsonify({
        "status": "error",
        "error_code": "INVALID_TRANSITION",
        "message": f"Can't {decision} a task that is '{existing[0]['status']}' (it must be '{current_status}')."
    }), 409


# 8. Bed Cleaned (Write): a bed released by a transfer becomes available again
@app.route('/api/beds/<bed_id>/mark-clean', methods=['POST'])
def mark_bed_clean(bed_id):
    if supabase is None:
        return supabase_unavailable_response()
    try:
        updated = supabase.table('hospital_resources').update({'status': 'available'}) \
            .eq('id', bed_id).eq('status', 'cleaning').execute().data or []
        if updated:
            return jsonify({"status": "success", "bed": {"id": bed_id, "status": "available"}}), 200
        existing = supabase.table('hospital_resources').select('id, status').eq('id', bed_id).execute().data or []
    except Exception as e:
        print(f"[mark-clean] Supabase error: {e}")
        return supabase_query_failed_response("Unable to update the bed.")

    if not existing:
        return jsonify({"status": "error", "error_code": "BED_NOT_FOUND", "message": f"No bed with id {bed_id}."}), 404
    return jsonify({
        "status": "error",
        "error_code": "INVALID_TRANSITION",
        "message": f"Only beds being cleaned can be marked clean; {bed_id} is '{existing[0]['status']}'."
    }), 409


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