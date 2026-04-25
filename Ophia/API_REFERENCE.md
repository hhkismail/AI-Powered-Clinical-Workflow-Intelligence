# API Contract Reference

## Endpoint: POST /api/process-note

### Request Schema

```json
{
  "metadata": {
    "doctor_id": "string (required)",
    "patient_id": "string (required)",
    "department": "string (required)",
    "timestamp": "string (required, ISO 8601 format)",
    "priority": "string (required)"
  },
  "payload": {
    "input_methods_used": ["string (required, array of methods)"],
    "raw_text": "string (required, unstructured clinical notes)"
  }
}
```

### Response Schema - Success (200 OK)

```json
{
  "status": "success",
  "system_alerts": null,
  "result": {
    "llm_reasoning": "string (reasoning from LLM)",
    "execution_results": {
      "executed_actions": [
        {
          "tool": "reserve_bed | schedule_appointment | update_record",
          "status": "success",
          "result": "object (API response)"
        }
      ],
      "alerts": []
    }
  }
}
```

### Response Schema - Error / Halted (200 OK)

```json
{
  "status": "halted_for_clarification",
  "system_alerts": [
    {
      "type": "API Rejection | Processing Error | LLM Alert",
      "message": "string (specific error or clarification needed)"
    }
  ],
  "result": null
}
```

### Response Schema - Validation Error (422 Unprocessable Entity)

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "metadata", "patient_id"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

---

## Mock API Contracts

### 1. reserve_bed

**URL:** `POST /api/reserve-bed`

**Request:**
```json
{
  "patient_id": "string",
  "ward_type": "string (ICU, General, Surgical, etc.)",
  "priority": "string (high, medium, low)",
  "clinical_reason": "string"
}
```

**Success Response (200):**
```json
{
  "bed_id": "string",
  "ward_type": "string",
  "status": "reserved"
}
```

**Error Response (400):**
```json
{
  "status": "error",
  "message": "string (specific error)"
}
```

---

### 2. schedule_appointment

**URL:** `POST /api/schedule-appointment`

**Request:**
```json
{
  "patient_id": "string",
  "department": "string",
  "timeframe_days": "integer",
  "appointment_type": "string (consultation, follow-up, etc.)"
}
```

**Success Response (200):**
```json
{
  "appointment_id": "string",
  "scheduled_date": "string (ISO 8601)",
  "department": "string",
  "status": "scheduled"
}
```

**Error Response (400):**
```json
{
  "status": "error",
  "message": "string (specific error)"
}
```

---

### 3. update_record

**URL:** `POST /api/update-record`

**Request:**
```json
{
  "patient_id": "string",
  "encounter_date": "string (ISO 8601)",
  "diagnoses": ["string"],
  "prescriptions": ["string"]
}
```

**Success Response (200):**
```json
{
  "record_id": "string",
  "updated_at": "string (ISO 8601)",
  "status": "updated"
}
```

**Error Response (400):**
```json
{
  "status": "error",
  "message": "string (specific error)"
}
```

---

## System Prompt (CMO Role)

Used when calling LLM via `call_zai_glm()`:

```
You are an elite Chief Medical Officer AI and autonomous workflow orchestrator. 
Your objective is to ingest unstructured clinical notes and execute a hospital workflow by interacting with available tools.
You operate under a strict JSON-only output mandate. 
TOOLS: 'update_record', 'reserve_bed', 'schedule_appointment'.
RULES:
1. NO ASSUMPTIONS: Never guess a medication dosage.
2. EXCEPTION HANDLING: If you encounter missing critical data (e.g., missing dosage), output a "halted_for_clarification" JSON.
```

---

## Error Handling Rules

| Scenario | HTTP Status | Response Status | Notes |
|----------|-------------|-----------------|-------|
| Valid request, successful processing | 200 | `success` | No alerts |
| Invalid request payload | 422 | Validation error | Pydantic validation |
| Mock API returns 400 | 200 | `halted_for_clarification` | Error message in system_alerts |
| LLM missing critical data | 200 | `halted_for_clarification` | LLM returns this status |
| Timeout calling mock API | 200 | `halted_for_clarification` | Caught exception |
| Unexpected server error | 200 | `halted_for_clarification` | Generic error message |

**Key Rule:** The backend ALWAYS returns 200 OK for application logic errors and communicates via the `status` field and `system_alerts`.

---

## cURL Examples

### Basic Note Processing

```bash
curl -X POST http://localhost:8000/api/process-note \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "doctor_id": "DR001",
      "patient_id": "PAT123",
      "department": "Cardiology",
      "timestamp": "2024-01-15T10:30:00Z",
      "priority": "high"
    },
    "payload": {
      "input_methods_used": ["voice_to_text"],
      "raw_text": "Patient presents with acute chest pain"
    }
  }'
```

### Health Check

```bash
curl -X GET http://localhost:8000/health
```

### View API Documentation

```
http://localhost:8000/docs
```

---

## Python Example

```python
import requests

response = requests.post(
    "http://localhost:8000/api/process-note",
    json={
        "metadata": {
            "doctor_id": "DR001",
            "patient_id": "PAT123",
            "department": "Cardiology",
            "timestamp": "2024-01-15T10:30:00Z",
            "priority": "high"
        },
        "payload": {
            "input_methods_used": ["voice_to_text"],
            "raw_text": "Patient presents with chest pain..."
        }
    }
)

result = response.json()
if result["status"] == "success":
    print("Processing successful!")
    print(result["result"])
else:
    print("Processing halted")
    for alert in result["system_alerts"]:
        print(f"  - {alert['type']}: {alert['message']}")
```

---

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| MOCK_API_BASE_URL | http://localhost:8001 | No | Base URL for mock APIs |
| TIMEOUT_SECONDS | 10 | No | Request timeout in seconds |

---

## Status Codes

- **200 OK** - Request processed (check `status` field for result)
- **422 Unprocessable Entity** - Request validation failed (bad JSON structure)
- **500 Internal Server Error** - Unexpected server error (rare)

---

## Data Flow

```
Frontend
   ↓
POST /api/process-note (200)
   ↓
Pydantic Validation
   ├─ FAIL → 422 Validation Error
   └─ PASS ↓
LLM Processing
   ├─ Returns halted_for_clarification → 200 with halted status
   └─ Returns actions ↓
Mock API Calls
   ├─ Returns 400 → Caught, 200 with halted status
   └─ Returns 200 ↓
Aggregate Results
   ↓
Return 200 with success status
```

---

## Testing Tools

- **Swagger UI:** http://localhost:8000/docs
- **Test Script:** `python test_api.py` (after server is running)
- **cURL:** See examples above
- **Postman:** Import from Swagger UI
- **Python:** `requests` library (see example above)

---

Last Updated: 2024
