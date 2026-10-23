import os
import sys
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

# Write log lines straight away, even when output is redirected to a file
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

app = Flask(__name__)
# Enable CORS globally so the browser dashboard isn't blocked
CORS(app)

load_dotenv()
supabase_url = os.getenv("SUPABASE_URL")
def server_supabase_key():
    """The server-side secret key. Every table has row-level security, which makes
    the publishable key see empty tables rather than fail, so it's not accepted."""
    key = os.getenv("SUPABASE_SECRET_KEY")
    if key and key.startswith("sb_publishable_"):
        print("[startup] SUPABASE_SECRET_KEY is a publishable key; use the sb_secret_ key")
        return None
    return key


supabase_key = server_supabase_key()
supabase = create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
if supabase is None:
    print("[startup] Supabase is not configured: set SUPABASE_URL and SUPABASE_SECRET_KEY in .env")

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


# Words that make a stop explicit when they're in the same sentence as the drug
STOP_WORDS = re.compile(r"\b(stop|stopped|stopping|discontinue|discontinued|discontinuing|cease|ceased|"
                        r"hold|held|withhold|withheld|d/c)\b", re.IGNORECASE)


def note_explicitly_stops(note_text, drug):
    """True if a sentence of the note names the drug together with a stop word.
    The LLM labels stops as explicit or inferred; this checks the label against
    the doctor's own words, so an inferred stop is never applied as an order."""
    if not note_text or not drug:
        return False
    for sentence in re.split(r"[.;\n]+", note_text):
        if re.search(rf"\b{re.escape(drug)}\b", sentence, re.IGNORECASE) and STOP_WORDS.search(sentence):
            return True
    return False


def matching_orders(active_orders, drug, dose=None):
    """Active orders for this drug (ignoring case); the matching dose first if one is given."""
    name = ' '.join(str(drug or '').lower().split())
    found = [o for o in active_orders if ' '.join(str(o.get('drug') or '').lower().split()) == name]
    if dose:
        same_dose = [o for o in found if medication_key(o)[1] == medication_key({'dose': dose})[1]]
        return same_dose or found
    return found


def stop_order(order_id, stopped_by, reason):
    """Stop an active medication order. Returns the row, or None if it wasn't active."""
    rows = supabase.table('medication_orders').update({
        'status': 'stopped',
        'ended_at': datetime.now(timezone.utc).isoformat(),
        'stopped_by': stopped_by,
        'stop_reason': reason
    }).eq('id', order_id).eq('status', 'active').execute().data or []
    return rows[0] if rows else None


def cancel_stop_proposals(order_id, by):
    """Once a medication is stopped, open suggestions to stop it are moot."""
    for status in ('suggested', 'accepted'):
        supabase.table('care_tasks').update({
            'status': 'cancelled', 'decided_at': datetime.now(timezone.utc).isoformat(), 'decided_by': by
        }).eq('medication_order_id', order_id).eq('proposed_action', 'stop_medication').eq('status', status).execute()


def medication_order_rows(patient_id, prescriptions, note_id):
    rows = []
    for rx in prescriptions or []:
        rx = rx if isinstance(rx, dict) else {'drug': str(rx)}
        drug = rx.get('drug') or rx.get('medication') or rx.get('name')
        if not drug:
            continue
        drug = str(drug).strip()
        if drug.islower():          # "diltiazem" -> "Diltiazem", so the board reads consistently
            drug = drug[0].upper() + drug[1:]
        rows.append({
            'id': str(uuid.uuid4()),
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
            'proposed_action': None,
            'medication_order_id': None,
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
        "message": "Supabase isn't configured: set SUPABASE_URL and SUPABASE_SECRET_KEY in .env."
    }), 500


def supabase_query_failed_response(message):
    return jsonify({
        "status": "error",
        "error_code": "SUPABASE_QUERY_FAILED",
        "message": message
    }), 500

# 1. Bed Reservation API
# The LLM sends ward types like 'icu' or 'observation'; hospital_resources stores
# bed types as ICU_BED / GEN_WARD. Observation beds are general ward beds.
WARD_KINDS = {'icu': 'icu', 'icu_bed': 'icu', 'observation': 'observation',
              'general': 'general', 'gen_ward': 'general'}
BED_TYPES = {'icu': 'ICU_BED', 'observation': 'GEN_WARD', 'general': 'GEN_WARD'}
WARD_LABELS = {'icu': 'ICU', 'observation': 'observation', 'general': 'general ward'}
ACUITY_ORDER = {'critical': 0, 'serious': 1, 'stable': 2}


def held_beds(patient_id):
    """Beds the patient currently occupies."""
    return supabase.table('hospital_resources') \
        .select('id, resource_name, wing, resource_type, status') \
        .eq('assigned_to_patient', patient_id).eq('status', 'occupied').execute().data or []


def choose_bed(ward_kind, department=None):
    """The most suitable free bed: an observation area if observation was asked for,
    then the note's department, then the lowest ID. None if nothing is free."""
    beds = supabase.table('hospital_resources') \
        .select('id, resource_name, wing, department, resource_type, status') \
        .eq('resource_type', BED_TYPES[ward_kind]).eq('status', 'available') \
        .order('id').execute().data or []      # ordered, so the same request gets the same bed
    department = str(department or '').strip().lower()

    def preference(b):
        in_observation = 'observation' in f"{b.get('wing') or ''} {b.get('resource_name') or ''}".lower()
        same_department = bool(department) and str(b.get('department') or '').lower() == department
        return (ward_kind == 'observation' and not in_observation, not same_department)

    beds.sort(key=preference)
    return beds[0] if beds else None


def occupy_bed(bed_id, patient_id):
    """Take the bed if it's still free. Re-checking the status in the update means
    two requests can't both take it. Returns the updated row, or None."""
    rows = supabase.table('hospital_resources') \
        .update({'status': 'occupied', 'assigned_to_patient': patient_id}) \
        .eq('id', bed_id).eq('status', 'available').execute().data or []
    return rows[0] if rows else None


def release_for_cleaning(beds):
    """Transfer: the patient's previous beds need cleaning before reuse."""
    for bed in beds:
        supabase.table('hospital_resources').update({'status': 'cleaning', 'assigned_to_patient': None}) \
            .eq('id', bed['id']).execute()


def waiting_request(patient_id):
    """The patient's open bed request, if they're on the waiting list."""
    rows = supabase.table('bed_requests').select('id, ward_type, resource_type, requested_at') \
        .eq('patient_id', patient_id).eq('status', 'waiting').execute().data or []
    return rows[0] if rows else None


def queue_position(request_row):
    waiting = supabase.table('bed_requests').select('id, requested_at').eq('status', 'waiting').execute().data or []
    return sum(1 for r in waiting if (r.get('requested_at') or '') <= (request_row.get('requested_at') or ''))


def resolve_request(request_id, status, by, bed_id=None):
    """Close a waiting request (assigned or cancelled). Returns the row, or None if it wasn't waiting."""
    changes = {'status': status, 'resolved_at': datetime.now(timezone.utc).isoformat(), 'resolved_by': by}
    if bed_id:
        changes['assigned_bed_id'] = bed_id
    rows = supabase.table('bed_requests').update(changes) \
        .eq('id', request_id).eq('status', 'waiting').execute().data or []
    return rows[0] if rows else None


def allocation(bed):
    return {"ward": bed.get('wing'), "bed": bed.get('resource_name'), "status": "occupied"}


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
    ward_kind = WARD_KINDS.get(str(ward_type).strip().lower())
    if ward_kind is None:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_WARD_TYPE",
            "message": f"Unknown ward_type '{ward_type}'. Expected one of: icu, observation, general."
        }), 400
    bed_type = BED_TYPES[ward_kind]

    try:
        # A patient holds one bed. Asking again for the same kind of bed (e.g. a
        # follow-up note) returns the current one; a different kind is a transfer.
        current_beds = held_beds(patient_id)
        same_type = [b for b in current_beds if b['resource_type'] == bed_type]
        if same_type:
            return jsonify({
                "status": "success",
                "reservation_id": same_type[0]['id'],
                "allocation": allocation(same_type[0]),
                "already_assigned": True,
                "message": "The patient already has a bed of this type; no new bed was reserved."
            }), 200

        bed = choose_bed(ward_kind, data.get('department'))
        taken = occupy_bed(bed['id'], patient_id) if bed else None

        if taken:
            release_for_cleaning(current_beds)
            # A new note found a bed for a patient who was waiting: close their request
            pending = waiting_request(patient_id)
            if pending:
                resolve_request(pending['id'], 'assigned', 'system', taken['id'])
            return jsonify({
                "status": "success",
                "reservation_id": taken['id'],
                "allocation": allocation(taken),
                "transferred_from": [b['id'] for b in current_beds] or None,
                "message": "Bed reserved successfully." + (" Previous bed released for cleaning." if current_beds else "")
            }), 200

        # No suitable bed is free: put the patient on the waiting list rather than
        # rejecting the admission. One open request per patient (a unique index).
        pending = waiting_request(patient_id)
        if not pending:
            supabase.table('bed_requests').insert({
                'id': str(uuid.uuid4()),
                'status': 'waiting',
                'requested_at': datetime.now(timezone.utc).isoformat(),
                'patient_id': patient_id,
                'ward_type': ward_kind,
                'resource_type': bed_type,
                'department': data.get('department'),
                'clinical_reason': data.get('clinical_reason')
            }).execute()
            pending = waiting_request(patient_id)
        position = queue_position(pending)
        return jsonify({
            "status": "queued",
            "request_id": pending['id'],
            "waiting_for": pending['ward_type'],
            "position": position,
            "current_bed": current_beds[0]['id'] if current_beds else None,
            "message": f"No {WARD_LABELS[pending['ward_type']]} bed is free. "
                       f"The patient was added to the waiting list (position {position})."
        }), 202
    except Exception as e:
        print(f"[reserve-bed] Supabase error: {e}")
        # A dropped connection can lose the reply to a write that succeeded. A bed's
        # state can be checked, so look before reporting a failure that didn't happen.
        try:
            held = held_beds(patient_id)
        except Exception:
            held = []
        bed = next((b for b in held if b.get('resource_type') == bed_type), None)
        if bed:
            print(f"[reserve-bed] {patient_id} does hold {bed['id']}; reporting success")
            return jsonify({
                "status": "success",
                "reservation_id": bed['id'],
                "allocation": allocation(bed),
                "message": "Bed reserved (confirmed after a database connection error)."
            }), 200
        return supabase_query_failed_response("Unable to reserve a bed from the database.")


# 1a. Waiting list: assign a bed to a waiting patient, or remove them from the list
@app.route('/api/bed-requests/<request_id>/assign', methods=['POST'])
def assign_bed_request(request_id):
    data = request.get_json(silent=True) or {}
    clinician_id = str(data.get('clinician_id') or '').strip()
    if not clinician_id:
        return missing_parameter_response("Assigning a bed requires 'clinician_id'.")
    if supabase is None:
        return supabase_unavailable_response()

    try:
        rows = supabase.table('bed_requests').select('id, patient_id, ward_type, resource_type, department, status') \
            .eq('id', request_id).execute().data or []
        if not rows:
            return jsonify({"status": "error", "error_code": "REQUEST_NOT_FOUND",
                            "message": f"No bed request with id {request_id}."}), 404
        req = rows[0]
        if req['status'] != 'waiting':
            return jsonify({"status": "error", "error_code": "INVALID_TRANSITION",
                            "message": f"This request is already {req['status']}."}), 409

        if data.get('bed_id'):
            beds = supabase.table('hospital_resources').select('id, resource_name, wing, resource_type, status') \
                .eq('id', data['bed_id']).execute().data or []
            suitable = beds and beds[0]['status'] == 'available' and beds[0]['resource_type'] == req['resource_type']
            if not suitable:
                return jsonify({"status": "error", "error_code": "BED_NOT_SUITABLE",
                                "message": f"{data['bed_id']} isn't a free {WARD_LABELS[req['ward_type']]} bed."}), 409
            bed = beds[0]
        else:
            bed = choose_bed(req['ward_type'], req.get('department'))
            if bed is None:
                return jsonify({"status": "error", "error_code": "NO_BEDS_AVAILABLE",
                                "message": f"No {WARD_LABELS[req['ward_type']]} bed is free yet."}), 409

        previous = held_beds(req['patient_id'])
        taken = occupy_bed(bed['id'], req['patient_id'])
        if not taken:
            return jsonify({"status": "error", "error_code": "NO_BEDS_AVAILABLE",
                            "message": f"{bed['id']} was taken a moment ago; try again."}), 409
        release_for_cleaning(previous)
        resolve_request(request_id, 'assigned', clinician_id, taken['id'])
    except Exception as e:
        print(f"[assign-bed] Supabase error: {e}")
        return supabase_query_failed_response("Unable to assign the bed.")

    return jsonify({
        "status": "success",
        "patient_id": req['patient_id'],
        "reservation_id": taken['id'],
        "allocation": allocation(taken),
        "transferred_from": [b['id'] for b in previous] or None,
        "message": f"{req['patient_id']} assigned to {taken.get('resource_name') or taken['id']}."
    }), 200


@app.route('/api/bed-requests/<request_id>/cancel', methods=['POST'])
def cancel_bed_request(request_id):
    data = request.get_json(silent=True) or {}
    clinician_id = str(data.get('clinician_id') or '').strip()
    if not clinician_id:
        return missing_parameter_response("Removing a patient from the waiting list requires 'clinician_id'.")
    if supabase is None:
        return supabase_unavailable_response()
    try:
        if resolve_request(request_id, 'cancelled', clinician_id):
            return jsonify({"status": "success", "request": {"id": request_id, "status": "cancelled"}}), 200
        existing = supabase.table('bed_requests').select('id, status').eq('id', request_id).execute().data or []
    except Exception as e:
        print(f"[cancel-request] Supabase error: {e}")
        return supabase_query_failed_response("Unable to update the waiting list.")
    if not existing:
        return jsonify({"status": "error", "error_code": "REQUEST_NOT_FOUND",
                        "message": f"No bed request with id {request_id}."}), 404
    return jsonify({"status": "error", "error_code": "INVALID_TRANSITION",
                    "message": f"This request is already {existing[0]['status']}."}), 409


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
        active = supabase.table('medication_orders').select('id, drug, dose, route') \
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
        # Discontinuations, matched against orders that existed before this note.
        # Explicit stops in the note are the doctor's order; anything else is only a
        # suggestion that a clinician has to accept.
        stopped, stop_suggestions, unmatched = [], 0, []
        open_proposals = {t.get('medication_order_id') for t in supabase.table('care_tasks')
                          .select('medication_order_id, status').eq('patient_id', patient_id)
                          .eq('proposed_action', 'stop_medication').execute().data or []
                          if t.get('status') in ('suggested', 'accepted')}
        for item in data.get('discontinue') or []:
            item = item if isinstance(item, dict) else {'drug': str(item)}
            orders = matching_orders(active, item.get('drug'), item.get('dose'))
            if not orders:
                unmatched.append(str(item.get('drug')))
                continue
            reason = str(item.get('reason') or '').strip() or None
            for order in orders:
                if item.get('explicit') and note_explicitly_stops(data.get('raw_input'), order['drug']):
                    if stop_order(order['id'], data.get('recorded_by') or 'clinical note', reason):
                        stopped.append(order['drug'])
                        cancel_stop_proposals(order['id'], data.get('recorded_by') or 'clinical note')
                elif order['id'] not in open_proposals:
                    supabase.table('care_tasks').insert({
                        'id': str(uuid.uuid4()),
                        'patient_id': patient_id,
                        'description': f"Stop {order['drug']}?" + (f" {reason}" if reason else ""),
                        'category': 'medication',
                        'status': 'suggested',
                        'suggested_by': 'ai',
                        'proposed_action': 'stop_medication',
                        'medication_order_id': order['id'],
                        'source_note_id': record_id
                    }).execute()
                    open_proposals.add(order['id'])
                    stop_suggestions += 1

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
        "care_tasks_suggested": len(tasks),
        "medications_stopped": stopped,
        "stops_proposed": stop_suggestions,
        "discontinue_not_found": unmatched
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
        bed_request = waiting_request(patient_id)

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
            "medication_orders": medications,
            "waiting_for_bed": bed_request
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
        waiting = supabase.table('bed_requests') \
            .select('id, patient_id, ward_type, resource_type, department, clinical_reason, requested_at') \
            .eq('status', 'waiting').execute().data or []
        # Patients in a bed and patients waiting for one (a transfer can be both)
        patient_ids = sorted({r['assigned_to_patient'] for r in resources if r.get('assigned_to_patient')}
                             | {w['patient_id'] for w in waiting})

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
                    .select('id, patient_id, description, category, status, suggested_by, created_at, decided_at, decided_by, '
                            'proposed_action, medication_order_id') \
                    .in_('patient_id', patient_ids).in_('status', ['suggested', 'accepted']).execute().data or []:
                tasks.setdefault(t['patient_id'], []).append(t)
    except Exception as e:
        print(f"[ward-board] Supabase error: {e}")
        return supabase_query_failed_response("Unable to load the ward board from the database.")

    def patient_view(pid):
        if pid not in patients:
            return None
        patient = dict(patients[pid])
        # IV lines first: they're what nurses check most often
        patient['medications'] = sorted(medications.get(pid, []),
                                        key=lambda m: (m.get('route') != 'iv', m.get('started_at') or ''))
        # Suggestions waiting for a decision first, then accepted work
        patient['tasks'] = sorted(tasks.get(pid, []),
                                  key=lambda t: (t['status'] != 'suggested', t.get('created_at') or ''))
        return patient

    wings = {}
    # Within a wing, beds read in name order (Bay 01, Bay 02, ...), not ID order
    for r in sorted(resources, key=lambda r: (r.get('resource_name') or '', r['id'])):
        pid = r.get('assigned_to_patient')
        patient = patient_view(pid) if pid else None
        wings.setdefault(r.get('wing') or 'Unassigned', []).append({
            'id': r['id'],
            'name': r.get('resource_name'),
            'type': r.get('resource_type'),
            'department': r.get('department'),
            'status': r.get('status'),
            'patient': patient
        })

    # Scanners (DIAGNOSTIC) are shown on the board but aren't beds, so they're not counted
    beds = [b for wing in wings.values() for b in wing if b['type'] in ('ICU_BED', 'GEN_WARD')]

    # Waiting list: sickest first, then longest waiting
    current_bed = {r['assigned_to_patient']: r for r in resources if r.get('assigned_to_patient')}
    free_by_type = {t: sum(1 for r in resources if r['resource_type'] == t and r['status'] == 'available')
                    for t in ('ICU_BED', 'GEN_WARD')}
    waiting_list = []
    for w in waiting:
        patient = patient_view(w['patient_id'])
        bed = current_bed.get(w['patient_id'])
        waiting_list.append({
            'request_id': w['id'],
            'ward_type': w['ward_type'],
            'department': w.get('department'),
            'clinical_reason': w.get('clinical_reason'),
            'requested_at': w.get('requested_at'),
            'current_bed': {'id': bed['id'], 'name': bed.get('resource_name')} if bed else None,
            'free_matching_beds': free_by_type.get(w['resource_type'], 0),
            'patient': patient
        })
    waiting_list.sort(key=lambda w: (ACUITY_ORDER.get((w['patient'] or {}).get('acuity'), 3), w['requested_at'] or ''))

    # Everyone the board shows, counted once (a patient waiting for a transfer is also in a bed)
    shown = {p['patient_id']: p for p in [b['patient'] for b in beds if b['patient']] +
             [w['patient'] for w in waiting_list if w['patient']]}.values()
    return jsonify({
        "status": "success",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "beds": {s: sum(b['status'] == s for b in beds) for s in ('available', 'occupied', 'cleaning', 'maintenance')},
            "critical_patients": sum(p.get('acuity') == 'critical' for p in shown),
            "pending_suggestions": sum(t['status'] == 'suggested' for p in shown for t in p['tasks']),
            "waiting": len(waiting_list)
        },
        "waiting": waiting_list,
        # Wings with beds first, alphabetically; wings of only scanners (no beds) last
        "wards": [{"wing": wing, "beds": wings[wing]} for wing in sorted(
            wings, key=lambda w: (all(b['type'] == 'DIAGNOSTIC' for b in wings[w]), w))]
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
            task = updated[0]
            stopped = None
            # Accepting "Stop X?" stops X, and the task is then done
            if decision == 'accept' and task.get('proposed_action') == 'stop_medication' and task.get('medication_order_id'):
                stopped = stop_order(task['medication_order_id'], clinician_id, task.get('description'))
                task = (supabase.table('care_tasks').update({
                    'status': 'done', 'completed_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', task_id).execute().data or [task])[0]
            return jsonify({"status": "success", "task": task,
                            "medication_stopped": stopped['drug'] if stopped else None}), 200

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


# 10. Stop a medication (Write): a clinician stops an active order from the board
@app.route('/api/medications/<order_id>/stop', methods=['POST'])
def stop_medication(order_id):
    data = request.get_json(silent=True) or {}
    clinician_id = str(data.get('clinician_id') or '').strip()
    if not clinician_id:
        return missing_parameter_response("Stopping a medication requires 'clinician_id'.")
    if supabase is None:
        return supabase_unavailable_response()
    reason = str(data.get('reason') or '').strip() or 'Stopped from the ward board'
    try:
        stopped = stop_order(order_id, clinician_id, reason)
        if stopped:
            cancel_stop_proposals(order_id, clinician_id)
            return jsonify({"status": "success", "medication": {"id": order_id, "drug": stopped.get('drug'),
                                                                 "status": "stopped"}}), 200
        existing = supabase.table('medication_orders').select('id, status').eq('id', order_id).execute().data or []
    except Exception as e:
        print(f"[stop-medication] Supabase error: {e}")
        return supabase_query_failed_response("Unable to stop the medication.")
    if not existing:
        return jsonify({"status": "error", "error_code": "MEDICATION_NOT_FOUND",
                        "message": f"No medication order with id {order_id}."}), 404
    return jsonify({"status": "error", "error_code": "INVALID_TRANSITION",
                    "message": f"This medication is already {existing[0]['status']}."}), 409


# 9. Discharge (Write): the patient leaves; their bed needs cleaning before reuse
@app.route('/api/beds/<bed_id>/discharge', methods=['POST'])
def discharge_patient(bed_id):
    data = request.get_json(silent=True) or {}
    clinician_id = str(data.get('clinician_id') or '').strip()
    if not clinician_id:
        return missing_parameter_response("A discharge requires 'clinician_id', so it's clear who discharged the patient.")
    if supabase is None:
        return supabase_unavailable_response()

    now = datetime.now(timezone.utc).isoformat()
    try:
        bed = supabase.table('hospital_resources').select('id, status, assigned_to_patient') \
            .eq('id', bed_id).execute().data or []
        if not bed:
            return jsonify({"status": "error", "error_code": "BED_NOT_FOUND", "message": f"No bed with id {bed_id}."}), 404
        patient_id = bed[0].get('assigned_to_patient')
        if bed[0].get('status') != 'occupied' or not patient_id:
            return jsonify({"status": "error", "error_code": "INVALID_TRANSITION",
                            "message": f"{bed_id} has no patient to discharge."}), 409

        # Free the bed first, guarded on the patient still being in it, so two
        # discharges (or a discharge racing a transfer) can't both proceed
        freed = supabase.table('hospital_resources') \
            .update({'status': 'cleaning', 'assigned_to_patient': None}) \
            .eq('id', bed_id).eq('assigned_to_patient', patient_id).execute().data or []
        if not freed:
            return jsonify({"status": "error", "error_code": "INVALID_TRANSITION",
                            "message": f"{bed_id} changed while discharging; refresh and try again."}), 409
    except Exception as e:
        print(f"[discharge] Supabase error: {e}")
        return supabase_query_failed_response("Unable to discharge the patient.")

    # Close the ward episode. Nothing is deleted: orders and tasks keep their history.
    try:
        meds = supabase.table('medication_orders').update({'status': 'completed', 'ended_at': now}) \
            .eq('patient_id', patient_id).eq('status', 'active').execute().data or []
        cancelled = []
        for status in ('suggested', 'accepted'):
            cancelled += supabase.table('care_tasks') \
                .update({'status': 'cancelled', 'decided_at': now, 'decided_by': clinician_id}) \
                .eq('patient_id', patient_id).eq('status', status).execute().data or []
        supabase.table('patients').update({'acuity': None, 'acuity_updated_at': now}) \
            .eq('patient_id', patient_id).execute()
        # A patient waiting for a transfer no longer needs the bed
        pending = waiting_request(patient_id)
        if pending:
            resolve_request(pending['id'], 'cancelled', clinician_id)
    except Exception as e:
        print(f"[discharge] Supabase error closing the episode: {e}")
        return supabase_query_failed_response(
            f"{patient_id} left {bed_id}, but their medications or tasks could not all be closed.")

    return jsonify({
        "status": "success",
        "patient_id": patient_id,
        "bed": {"id": bed_id, "status": "cleaning"},
        "medication_orders_completed": len(meds),
        "care_tasks_cancelled": len(cancelled),
        "discharged_by": clinician_id,
        "message": f"{patient_id} discharged; {bed_id} is being cleaned."
    }), 200


# 8. Bed Cleaned (Write): a bed released by a transfer or discharge becomes available again
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