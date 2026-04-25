# Clinical Notes Automation Backend - Quick Start Guide

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   - Copy `.env.example` to `.env`
   - Update `MOCK_API_BASE_URL` to point to your mock API server

3. **Run the server:**
   ```bash
   python main.py
   ```
   Server will start on `http://localhost:8000`

## API Endpoints

### Health Check
```
GET /health
```
Returns service status and timestamp.

### Process Clinical Notes
```
POST /api/process-note
Content-Type: application/json

{
  "metadata": {
    "doctor_id": "DR001",
    "patient_id": "PAT123",
    "department": "Cardiology",
    "timestamp": "2024-01-15T10:30:00Z",
    "priority": "high"
  },
  "payload": {
    "input_methods_used": ["voice_to_text", "manual_entry"],
    "raw_text": "Patient presents with acute chest pain, elevated troponin levels..."
  }
}
```

**Success Response (200):**
```json
{
  "status": "success",
  "system_alerts": null,
  "result": {
    "llm_reasoning": "...",
    "execution_results": {
      "executed_actions": [...],
      "alerts": []
    }
  }
}
```

**Error Response (400 - API Rejection):**
```json
{
  "status": "halted_for_clarification",
  "system_alerts": [
    {
      "type": "API Rejection",
      "message": "Invalid ward type specified"
    }
  ]
}
```

## Architecture

### Request Flow
1. Frontend sends clinical notes to `/api/process-note`
2. Backend extracts `raw_text` from payload
3. LLM analyzes notes with system prompt (CMO role, strict rules)
4. If LLM returns actions, execute them via mock APIs
5. Handle errors gracefully and return status to frontend

### Mock API Integration
The system calls three mock endpoints:
- `POST /api/reserve-bed` - Reserve hospital bed
- `POST /api/schedule-appointment` - Schedule patient appointment
- `POST /api/update-record` - Update medical records

All errors from mock APIs (HTTP 400) are caught and reformatted into the `halted_for_clarification` response.

### LLM Integration
The `call_zai_glm()` function is a placeholder for your Zai GLM SDK integration.

**Current behavior:** Returns mock response
**Your task:** Replace with official SDK when available

Example integration point:
```python
def call_zai_glm(text: str, system_prompt: str) -> Dict[str, Any]:
    # TODO: Implement with Zai GLM SDK
    response = zai_glm.invoke({
        "system": system_prompt,
        "user": text
    })
    return parse_llm_response(response)
```

## Key Features

✅ Pydantic models for strict input validation
✅ Exact system prompt implementation (CMO + rules)
✅ Graceful HTTP error handling (400 → halted_for_clarification)
✅ Three mock API tool bindings (reserve_bed, schedule_appointment, update_record)
✅ Detailed logging for debugging
✅ Type hints throughout
✅ Clean separation of concerns

## Testing

Use curl to test:
```bash
curl -X POST http://localhost:8000/api/process-note \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {"doctor_id":"DR001","patient_id":"PAT123","department":"Cardiology","timestamp":"2024-01-15T10:30:00Z","priority":"high"},
    "payload": {"input_methods_used":["voice_to_text"],"raw_text":"Patient presents with chest pain"}
  }'
```

Or use Swagger UI: `http://localhost:8000/docs`

## Environment Variables

```
MOCK_API_BASE_URL     - Base URL for mock hospital API (default: http://localhost:8001)
TIMEOUT_SECONDS       - Request timeout (default: 10)
```
