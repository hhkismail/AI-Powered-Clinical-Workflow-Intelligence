"""
Clinical Notes Automation Workflow - AI Orchestrator Backend
FastAPI service that processes clinical notes and orchestrates hospital workflows
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx
import requests

# Load the shared .env from the repo root, regardless of the working directory
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log startup information"""
    print("\n" + "="*60)
    print("Clinical Notes Automation Backend Starting...")
    print("="*60)
    print(f"Mock API Base URL: {MOCK_API_BASE_URL}")
    print(f"Timeout: {TIMEOUT_SECONDS}s")
    if get_groq_api_key():
        print(f"✅ Groq API key loaded (model: {GROQ_CHAT_MODEL})")
    else:
        print("❌ ERROR: GROQ_API_KEY not found in environment! Add your Groq key to .env")
    print("="*60 + "\n")
    yield


app = FastAPI(
    title="Clinical Notes Automation",
    description="AI Orchestrator for healthcare workflow automation",
    version="1.0.0",
    lifespan=lifespan
)

from fastapi.middleware.cors import CORSMiddleware

# This opens the gates for the frontend to talk to your API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Safe for hackathon local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================
# PYDANTIC MODELS
# ========================

class MetadataModel(BaseModel):
    """Request metadata with doctor, patient, and clinical context"""
    doctor_id: str = Field(..., description="ID of the doctor creating the note")
    patient_id: str = Field(..., description="ID of the patient")
    department: str = Field(..., description="Department or specialty")
    timestamp: str = Field(..., description="ISO format timestamp")
    priority: str = Field(..., description="Priority level")


class PayloadModel(BaseModel):
    """Payload containing the clinical input"""
    input_methods_used: List[str] = Field(..., description="Methods used to input data")
    raw_text: str = Field(..., description="Unstructured clinical notes text")


class ProcessNoteRequest(BaseModel):
    """Complete request model for process-note endpoint"""
    metadata: MetadataModel
    payload: PayloadModel


class SystemAlert(BaseModel):
    """Alert message from processing"""
    type: str = Field(..., description="Type of alert")
    message: str = Field(..., description="Alert message")


class ProcessNoteResponse(BaseModel):
    """Response model for process-note endpoint"""
    status: str = Field(..., description="Status of processing")
    system_alerts: Optional[List[SystemAlert]] = Field(
        default=None,
        description="List of system alerts if any"
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Processing result if successful"
    )


# ========================
# CONFIGURATION
# ========================

MOCK_API_BASE_URL = os.getenv("MOCK_API_BASE_URL", "http://127.0.0.1:3001")
TIMEOUT_SECONDS = 60
# Groq retires models regularly; override in .env without touching code
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")


def get_groq_api_key() -> Optional[str]:
    """GROQ_API_KEY, falling back to the legacy ZAI_API_KEY name."""
    return os.getenv("GROQ_API_KEY") or os.getenv("ZAI_API_KEY")


class APIRejection(Exception):
    """Raised when a hospital API rejects an action with 400 Bad Request."""
    pass


# ========================
# LLM INTEGRATION
# ========================

def build_llm_prompt(patient_id: str, encounter_date: str, department: str, patient_history: str, raw_text: str) -> str:
    """The user message sent to the LLM: note metadata, patient history, then the doctor's note."""
    return f"""
    PATIENT ID: {patient_id}
    ENCOUNTER DATE: {encounter_date}
    DEPARTMENT: {department}

    {patient_history}

    NEW DOCTOR'S NOTE:
    {raw_text}
    """


async def call_llm(text: str) -> dict:
    """Calls the Groq chat model (GROQ_CHAT_MODEL) for JSON extraction and action planning."""
    api_key = get_groq_api_key()
    
    # 1. NEW URL FOR GROQ
    url = "https://api.groq.com/openai/v1/chat/completions"

    if not api_key:
        return {
            "status": "halted_for_clarification",
            "system_alerts": [{"type": "Configuration Error", "message": "GROQ_API_KEY is not set. Add your Groq API key to .env and restart the orchestrator."}]
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    system_prompt = """You are an elite Chief Medical Officer AI. 
Your objective is to ingest clinical notes and execute hospital workflows via tools.
Output MUST be pure JSON.

# OPERATING RULES
1. DRUG SAFETY: If an allergy conflict (e.g., Aspirin/NSAID) is detected, you MUST return "status": "halted_for_clarification".
2. ADMISSION LOGIC: If a patient is in respiratory failure or needs life support, you MUST use the 'reserve_bed' tool with ward_type='icu'.
   If the note says to admit the patient to any other ward (e.g. observation or general), you MUST use 'reserve_bed' with ward_type='observation' or 'general'.
   Rule 1 always takes priority: if any prescription conflicts with a known allergy, halt instead of admitting.
3. DATA FORMAT: Prescriptions MUST be objects with 'drug', 'dosage', 'route' and 'frequency' keys (frequency may be null if the note doesn't say).
4. ACUITY: In 'update_record', set 'acuity' to exactly one of:
   'critical' - life-threatening or needs ICU / life support;
   'serious'  - needs admission or close monitoring;
   'stable'   - can be managed as an outpatient or routine follow-up.
5. NEXT STEPS: In 'update_record', list the concrete next steps the note calls for (e.g. telemetry monitoring, labs, imaging, procedure prep, consults) as 'next_steps', each with a 'description' and a 'category' of 'prep', 'monitoring', 'lab', 'imaging', 'consult', 'medication' or 'other'.
   Only include steps the note states or directly implies; never invent new treatments. These are suggestions a clinician must approve.

# AVAILABLE TOOLS
- 'update_record': (patient_id, diagnoses, prescriptions, acuity, next_steps)
- 'reserve_bed': (patient_id, ward_type, clinical_reason)
- 'schedule_appointment': (patient_id, department, appointment_date (YYYY-MM-DD) or timeframe_days, reason)

# OUTPUT SCHEMA
Output ONLY valid JSON:
{
    "status": "success",
    "reasoning": "Explain your decision.",
    "actions": [
        {"tool": "update_record", "params": {"patient_id": "...", "diagnoses": ["..."], "prescriptions": [{"drug": "...", "dosage": "...", "route": "...", "frequency": "..."}], "acuity": "serious", "next_steps": [{"description": "...", "category": "monitoring"}]}},
        {"tool": "reserve_bed", "params": {"patient_id": "...", "ward_type": "icu", "clinical_reason": "..."}}
    ],
    "system_alerts": []
}"""

    payload = {
        "model": GROQ_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.0, # Set to 0 for strict JSON adherence
        "response_format": { "type": "json_object" } # Forces Groq to output pure JSON
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            print("[DEBUG] Sending request to Groq API... waiting for response.")
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            response_data = response.json()
            glm_output_string = response_data['choices'][0]['message']['content']
            
            clean_json_string = glm_output_string.strip().replace("```json", "").replace("```", "").strip()
            
            try:
                parsed_result = json.loads(clean_json_string)
                if isinstance(parsed_result, dict):
                    return parsed_result
                else:
                    return {"status": "success", "reasoning": str(parsed_result), "actions": []}
            except json.JSONDecodeError:
                print(f"\n[WARNING] AI sent non-JSON text: {glm_output_string[:200]}...")
                return {
                    "status": "halted_for_clarification",
                    "system_alerts": [{"type": "AI Format Error", "message": "AI failed to return structured JSON."}]
                }
            
    except httpx.HTTPStatusError as e:
        print(f"[ERROR] API {e.response.status_code} Details: {e.response.text}")
        return {
            "status": "halted_for_clarification",
            "system_alerts": [{"type": "AI Gateway Error", "message": f"API Error: {e.response.text}"}]
        }
    except Exception as e:
        error_type = type(e).__name__
        print(f"[ERROR] Connection Failed: {error_type} - {str(e)}")
        
        return {
            "status": "halted_for_clarification",
            "system_alerts": [{"type": "LLM Request Failed", "message": f"Could not get a response from the Groq API ({error_type}: {e})."}]
        }


async def fetch_patient_history(patient_id: str) -> str:
    """Fetches patient allergies, prescriptions, and history from the Supabase patients table."""
    db_url = os.getenv("ISMA_DB_URL")
    anon_key = os.getenv("ISMA_ANON_KEY")

    if not db_url or not anon_key:
        return "PATIENT HISTORY: No prior records found."

    # Supabase publishable keys go in the apikey header only (they aren't JWTs)
    headers = {
        "apikey": anon_key,
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Pass the ID as a query param so it's URL-encoded, not spliced into the filter
            response = await client.get(
                f"{db_url}/rest/v1/patients",
                params={"patient_id": f"eq.{patient_id}"},
                headers=headers
            )
            response.raise_for_status()

            data = response.json()
            if data and len(data) > 0:
                patient_record = data[0]

                allergies = patient_record.get("allergies", [])
                prescriptions = patient_record.get("active_prescriptions", [])
                history = patient_record.get("medical_history", "None")
                
                # Formatting arrays into clean strings for the AI to read
                allergies_str = ", ".join(allergies) if allergies else "None documented"
                rx_str = ", ".join(prescriptions) if prescriptions else "None"
                
                return f"""PATIENT HISTORY (CRITICAL CONTEXT):
- Known Allergies: {allergies_str}
- Active Prescriptions: {rx_str}
- Medical History: {history}"""
            else:
                return "PATIENT HISTORY: No prior records found."
                
    except Exception as e:
        print(f"[WARNING] Could not fetch patient history from Supabase: {e}")
        return "PATIENT HISTORY: Unavailable at this time."


# ========================
# MOCK API CALLS
# ========================

def call_mock_api(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic function to call mock hospital APIs.
    
    Args:
        endpoint: API endpoint (e.g., '/api/reserve-bed')
        data: Request payload
        
    Returns:
        Response JSON from the API
        
    Raises:
        APIRejection with the API's message for 400 Bad Request
    """
    url = f"{MOCK_API_BASE_URL}{endpoint}"
    
    try:
        response = requests.post(
            url,
            json=data,
            timeout=TIMEOUT_SECONDS
        )
        
        if response.status_code == 400:
            # Extract error message from mock API
            try:
                error_data = response.json()
                error_message = error_data.get("message", "Unknown error")
            except json.JSONDecodeError:
                error_message = response.text or "Bad Request"
            
            # Return formatted error for orchestrator to handle
            raise APIRejection(error_message)
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.Timeout:
        raise Exception(f"Timeout calling {endpoint}")
    except requests.exceptions.ConnectionError:
        raise Exception(f"Connection error calling {endpoint}")


def reserve_bed(patient_id: str, ward_type: str, priority: str, clinical_reason: str,
                department: Optional[str] = None) -> Dict[str, Any]:
    """
    Call mock API to reserve a hospital bed.
    
    Args:
        patient_id: Patient identifier
        ward_type: Type of ward (ICU, general, etc.)
        priority: Priority level
        clinical_reason: Reason for bed reservation
        department: The note's department; the API prefers beds there
        
    Returns:
        API response
    """
    data = {
        "patient_id": patient_id,
        "ward_type": ward_type,
        "priority": priority,
        "clinical_reason": clinical_reason,
        "department": department
    }
    return call_mock_api("/api/reserve-bed", data)


def schedule_appointment(
    patient_id: str,
    department: str,
    timeframe_days: int,
    appointment_date: str,
    reason: str
) -> Dict[str, Any]:
    """Call mock API to schedule an appointment with strict keys."""
    data = {
        "patient_id": patient_id,
        "department": department,
        "timeframe_days": timeframe_days,
        "appointment_date": appointment_date,
        "reason": reason
    }
    return call_mock_api("/api/schedule-appointment", data)


def update_record(
    patient_id: str,
    encounter_date: str,
    diagnoses: List[str],
    prescriptions: List[Any],
    acuity: Optional[str] = None,
    next_steps: Optional[List[Any]] = None,
    raw_input: Optional[str] = None,
    reasoning: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call mock API to update patient medical record.

    Args:
        patient_id: Patient identifier
        encounter_date: Date of encounter
        diagnoses: List of diagnoses
        prescriptions: List of prescriptions (become medication orders)
        acuity: critical / serious / stable
        next_steps: Suggested care tasks for a clinician to approve
        raw_input: The original note text, kept for the audit trail
        reasoning: The LLM's explanation, kept for the audit trail

    Returns:
        API response
    """
    data = {
        "patient_id": patient_id,
        "encounter_date": encounter_date,
        "diagnoses": diagnoses,
        "prescriptions": prescriptions,
        "acuity": acuity,
        "next_steps": next_steps or [],
        "raw_input": raw_input,
        "reasoning": reasoning
    }
    return call_mock_api("/api/update-record", data)


# ========================
# TOOL EXECUTION
# ========================

def execute_llm_actions(
    actions: List[Dict[str, Any]],
    patient_id: str,
    raw_text: Optional[str] = None,
    reasoning: Optional[str] = None,
    department: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute actions returned by the LLM.

    Dynamically calls the appropriate mock API based on the tool specified.
    Every action is attempted; a rejected or failed action is recorded as an
    alert instead of discarding the actions that already succeeded.

    Args:
        actions: List of actions from LLM
        patient_id: Patient ID for context

    Returns:
        Dictionary with executed_actions and alerts
    """
    results = {
        "executed_actions": [],
        "alerts": []
    }
    
    for action in actions:
        tool_name = action.get("tool")
        params = action.get("params", {})
        
        try:
            if tool_name == "reserve_bed":
                result = reserve_bed(
                    patient_id=params.get("patient_id", patient_id),
                    ward_type=params.get("ward_type"),
                    priority=params.get("priority"),
                    clinical_reason=params.get("clinical_reason"),
                    department=department
                )
                results["executed_actions"].append({
                    "tool": tool_name,
                    "status": "success",
                    "result": result
                })
                
            elif tool_name == "schedule_appointment":
                result = schedule_appointment(
                    patient_id=params.get("patient_id", patient_id),
                    department=params.get("department"),
                    timeframe_days=params.get("timeframe_days"),
                    appointment_date=params.get("appointment_date"),
                    reason=params.get("reason")
                )
                results["executed_actions"].append({
                    "tool": tool_name,
                    "status": "success",
                    "result": result
                })
                
            elif tool_name == "update_record":
                result = update_record(
                    patient_id=params.get("patient_id", patient_id),
                    encounter_date=params.get("encounter_date"),
                    diagnoses=params.get("diagnoses", []),
                    prescriptions=params.get("prescriptions", []),
                    acuity=params.get("acuity"),
                    next_steps=params.get("next_steps", []),
                    # From the request and the LLM response, not the LLM's params
                    raw_input=raw_text,
                    reasoning=reasoning
                )
                results["executed_actions"].append({
                    "tool": tool_name,
                    "status": "success",
                    "result": result
                })
                
            else:
                results["alerts"].append({
                    "type": "Unknown Tool",
                    "message": f"Tool '{tool_name}' not recognized"
                })
                
        except APIRejection as e:
            results["alerts"].append({
                "type": "API Rejection",
                "message": f"{tool_name} was rejected: {e}"
            })
        except Exception as e:
            results["alerts"].append({
                "type": "Execution Error",
                "message": f"Error executing {tool_name}: {str(e)}"
            })
    
    return results


# ========================
# ENDPOINTS
# ========================

@app.post(
    "/api/process-note",
    response_model=ProcessNoteResponse,
    summary="Process Clinical Notes",
    description="Ingests unstructured clinical notes and orchestrates hospital workflow"
)
async def process_note(request: ProcessNoteRequest) -> ProcessNoteResponse:
    """
    Main orchestration endpoint for clinical notes processing.
    
    Workflow:
    1. Receive clinical notes with metadata
    2. Call LLM with system prompt to determine actions
    3. Execute any actions via mock hospital APIs
    4. Return results or gracefully handle errors
    
    Args:
        request: ProcessNoteRequest containing metadata and payload
        
    Returns:
        ProcessNoteResponse with status, alerts, and results
    """
    try:
        # Extract data from request
        raw_text = request.payload.raw_text
        patient_id = request.metadata.patient_id
        
        print(f"\n[ORCHESTRATOR] Processing note for patient {patient_id}")
        print(f"[ORCHESTRATOR] Doctor: {request.metadata.doctor_id}")
        print(f"[ORCHESTRATOR] Department: {request.metadata.department}")
        
        print(f"[ORCHESTRATOR] Fetching history for patient {patient_id} from Supabase...")

        # 1. Fetch the patient history from the patients table
        patient_history = await fetch_patient_history(patient_id)
        
        # 2. Combine the history, metadata, and the new doctor's note
        # Extract the date from the timestamp for the encounter_date parameter
        encounter_date = request.metadata.timestamp[:10] 
        
        enriched_prompt = build_llm_prompt(
            patient_id, encounter_date, request.metadata.department, patient_history, raw_text
        )

        # 3. Send the combined context to the AI Brain
        print(f"[ORCHESTRATOR] Calling LLM with enriched context...")
        llm_response = await call_llm(enriched_prompt)
        
        # Step 2: Check if LLM returned halted_for_clarification
        if llm_response.get("status") == "halted_for_clarification":
            # Extract the actual clinical reason from the AI's response
            ai_alerts = llm_response.get("system_alerts", [])
            alert_type = "Clinical Safety Halt"
            if ai_alerts and isinstance(ai_alerts, list) and len(ai_alerts) > 0:
                ai_message = ai_alerts[0].get("message", "Clinical data incomplete.")
                # Keep config/network error types so they aren't reported as clinical halts
                alert_type = ai_alerts[0].get("type", alert_type)
            else:
                ai_message = llm_response.get("reasoning", "LLM requires clarification")

            return ProcessNoteResponse(
                status="halted_for_clarification",
                system_alerts=[
                    SystemAlert(
                        type=alert_type,
                        message=ai_message
                    )
                ]
            )
        
        # Step 3: Execute any actions from LLM
        actions = llm_response.get("actions", [])
        if actions:
            print(f"[ORCHESTRATOR] Executing {len(actions)} actions from LLM...")
            # The hospital API calls are blocking; keep them off the event loop
            execution_results = await run_in_threadpool(
                execute_llm_actions, actions, patient_id, raw_text, llm_response.get("reasoning"),
                request.metadata.department
            )
            executed = execution_results["executed_actions"]
            alerts = execution_results["alerts"]

            # Surface action failures at the top level so the dashboard shows them
            if not alerts:
                status = "success"
            elif executed:
                status = "partial_success"
            else:
                status = "halted_for_clarification"

            return ProcessNoteResponse(
                status=status,
                system_alerts=[SystemAlert(**alert) for alert in alerts] or None,
                result={
                    "llm_reasoning": llm_response.get("reasoning"),
                    "execution_results": execution_results
                }
            )
        else:
            # No actions to execute
            print(f"[ORCHESTRATOR] No actions to execute")
            return ProcessNoteResponse(
                status="success",
                result={
                    "llm_reasoning": llm_response.get("reasoning"),
                    "execution_results": {
                        "executed_actions": [],
                        "alerts": []
                    }
                }
            )
    
    except Exception as e:
        # Unexpected errors
        print(f"[ERROR] Unexpected error: {str(e)}")
        return ProcessNoteResponse(
            status="halted_for_clarification",
            system_alerts=[
                SystemAlert(
                    type="Processing Error",
                    message=str(e)
                )
            ]
        )


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Clinical Notes Orchestrator",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn

    # reload needs an import string; bind to localhost since the API has no auth
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
