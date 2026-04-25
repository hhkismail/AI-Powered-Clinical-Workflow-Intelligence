"""
Clinical Notes Automation Workflow - AI Orchestrator Backend
FastAPI service that processes clinical notes and orchestrates hospital workflows
"""

import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import httpx
import requests

# Force-load from the current working directory
load_dotenv(os.path.join(os.getcwd(), '.env'))

app = FastAPI(
    title="Clinical Notes Automation",
    description="AI Orchestrator for healthcare workflow automation",
    version="1.0.0"
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


class MockAPIErrorResponse(BaseModel):
    """Error response from mock APIs"""
    status: str
    message: str


# ========================
# CONFIGURATION
# ========================

MOCK_API_BASE_URL = os.getenv("MOCK_API_BASE_URL", "https://destiny-dropkick-gout.ngrok-free.dev")
TIMEOUT_SECONDS = 60

# LLM System Prompt - exact as specified
SYSTEM_PROMPT = """You are an elite Chief Medical Officer AI and autonomous workflow orchestrator. 
Your objective is to ingest unstructured clinical notes and execute a hospital workflow by interacting with available tools.
You operate under a strict JSON-only output mandate. 
TOOLS: 'update_record', 'reserve_bed', 'schedule_appointment'.
RULES:
1. NO ASSUMPTIONS: Never guess a medication dosage.
2. EXCEPTION HANDLING: If you encounter missing critical data (e.g., missing dosage), output a "halted_for_clarification" JSON."""


# ========================
# LLM INTEGRATION
# ========================

import httpx
import json

async def call_zai_glm(text: str) -> dict:
    """Calls the Groq Llama-3 model for lightning-fast JSON extraction."""
    api_key = os.getenv("ZAI_API_KEY") 
    
    # 1. NEW URL FOR GROQ
    url = "https://api.groq.com/openai/v1/chat/completions"
    print(f"[DEBUG] API Key starts with: {str(api_key)[:5]}...")
    
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
3. DATA FORMAT: Prescriptions MUST be objects with 'drug', 'dosage', and 'route' keys.

# AVAILABLE TOOLS
- 'update_record': (patient_id, diagnoses, prescriptions)
- 'reserve_bed': (patient_id, ward_type, clinical_reason)
- 'schedule_appointment': (patient_id, department, appointment_date, reason)

# OUTPUT SCHEMA
Output ONLY valid JSON:
{
    "status": "success", 
    "reasoning": "Explain your decision.",
    "actions": [
        {"tool": "update_record", "params": {"patient_id": "...", "diagnoses": ["..."], "prescriptions": [{"drug": "...", "dosage": "...", "route": "..."}]}},
        {"tool": "reserve_bed", "params": {"patient_id": "...", "ward_type": "icu", "clinical_reason": "..."}}
    ],
    "system_alerts": []
}"""

    payload = {
        # 2. NEW MODEL FOR GROQ (Llama 3 70B is incredibly smart and fast)
        "model": "llama-3.3-70b-versatile",
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
            "system_alerts": [{"type": "Network Timeout", "message": f"Server is busy ({error_type}). Please try again."}]
        }


async def fetch_patient_history(patient_id: str) -> str:
    """Fetches patient allergies, prescriptions, and history from Isma's database."""
    db_url = os.getenv("ISMA_DB_URL")
    anon_key = os.getenv("ISMA_ANON_KEY")
    
    if not db_url or not anon_key:
        return "PATIENT HISTORY: No prior records found."

    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url = f"{db_url}/rest/v1/patients?patient_id=eq.{patient_id}"
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            if data and len(data) > 0:
                patient_record = data[0]
                
                # Extracting the exact columns from Isma's database
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
        print(f"[WARNING] Could not connect to Isma's database: {e}")
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
        HTTPError with formatted error response for 400 Bad Request
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
            raise HTTPError(error_message)
        
        response.raise_for_status()
        return response.json()
        
    except requests.exceptions.Timeout:
        raise Exception(f"Timeout calling {endpoint}")
    except requests.exceptions.ConnectionError:
        raise Exception(f"Connection error calling {endpoint}")


def reserve_bed(patient_id: str, ward_type: str, priority: str, clinical_reason: str) -> Dict[str, Any]:
    """
    Call mock API to reserve a hospital bed.
    
    Args:
        patient_id: Patient identifier
        ward_type: Type of ward (ICU, general, etc.)
        priority: Priority level
        clinical_reason: Reason for bed reservation
        
    Returns:
        API response
    """
    data = {
        "patient_id": patient_id,
        "ward_type": ward_type,
        "priority": priority,
        "clinical_reason": clinical_reason
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
    prescriptions: List[str]
) -> Dict[str, Any]:
    """
    Call mock API to update patient medical record.
    
    Args:
        patient_id: Patient identifier
        encounter_date: Date of encounter
        diagnoses: List of diagnoses
        prescriptions: List of prescriptions
        
    Returns:
        API response
    """
    data = {
        "patient_id": patient_id,
        "encounter_date": encounter_date,
        "diagnoses": diagnoses,
        "prescriptions": prescriptions
    }
    return call_mock_api("/api/update-record", data)


# ========================
# TOOL EXECUTION
# ========================

def execute_llm_actions(actions: List[Dict[str, Any]], patient_id: str) -> Dict[str, Any]:
    """
    Execute actions returned by the LLM.
    
    Dynamically calls the appropriate mock API based on the tool specified.
    
    Args:
        actions: List of actions from LLM
        patient_id: Patient ID for context
        
    Returns:
        Dictionary with execution results
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
                    clinical_reason=params.get("clinical_reason")
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
                    appointment_date=params.get("appointment_date", "2026-05-08"), # Fallback date just in case
                    reason=params.get("reason", "Orthopedics Follow-up")
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
                    prescriptions=params.get("prescriptions", [])
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
                
        except HTTPError as e:
            # Return halted_for_clarification on API rejection
            raise HTTPError(str(e))
        except Exception as e:
            results["alerts"].append({
                "type": "Execution Error",
                "message": f"Error executing {tool_name}: {str(e)}"
            })
    
    return results


# ========================
# CUSTOM EXCEPTIONS
# ========================

class HTTPError(Exception):
    """Custom exception for HTTP errors from mock APIs"""
    pass


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
        
        print(f"[ORCHESTRATOR] Fetching history for patient {patient_id} from Isma's DB...")
        
        # 1. Fetch the patient history from Isma's database
        patient_history = await fetch_patient_history(patient_id)
        
        # 2. Combine the history, metadata, and the new doctor's note
        # Extract the date from the timestamp for the encounter_date parameter
        encounter_date = request.metadata.timestamp[:10] 
        
        enriched_prompt = f"""
    PATIENT ID: {patient_id}
    ENCOUNTER DATE: {encounter_date}
    DEPARTMENT: {request.metadata.department}

    {patient_history}

    NEW DOCTOR'S NOTE:
    {raw_text}
    """
        
        # 3. Send the combined context to the AI Brain
        print(f"[ORCHESTRATOR] Calling LLM with enriched context...")
        llm_response = await call_zai_glm(enriched_prompt)
        
        # Step 2: Check if LLM returned halted_for_clarification
        if llm_response.get("status") == "halted_for_clarification":
            # Extract the actual clinical reason from the AI's response
            ai_alerts = llm_response.get("system_alerts", [])
            if ai_alerts and isinstance(ai_alerts, list) and len(ai_alerts) > 0:
                ai_message = ai_alerts[0].get("message", "Clinical data incomplete.")
            else:
                ai_message = llm_response.get("reasoning", "LLM requires clarification")
                
            return ProcessNoteResponse(
                status="halted_for_clarification",
                system_alerts=[
                    SystemAlert(
                        type="Clinical Safety Halt",
                        message=ai_message
                    )
                ]
            )
        
        # Step 3: Execute any actions from LLM
        actions = llm_response.get("actions", [])
        if actions:
            print(f"[ORCHESTRATOR] Executing {len(actions)} actions from LLM...")
            execution_results = execute_llm_actions(actions, patient_id)
            
            return ProcessNoteResponse(
                status="success",
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
    
    except HTTPError as e:
        # API rejection with specific error message
        print(f"[ERROR] API Rejection: {str(e)}")
        return ProcessNoteResponse(
            status="halted_for_clarification",
            system_alerts=[
                SystemAlert(
                    type="API Rejection",
                    message=str(e)
                )
            ]
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


# ========================
# STARTUP/SHUTDOWN
# ========================

@app.on_event("startup")
async def startup_event():
    """Log startup information"""
    print("\n" + "="*60)
    print("Clinical Notes Automation Backend Starting...")
    print("="*60)
    print(f"Mock API Base URL: {MOCK_API_BASE_URL}")
    print(f"Timeout: {TIMEOUT_SECONDS}s")
    api_key = os.getenv("ZAI_API_KEY")
    if api_key:
        print(f"✅ Z.AI API Key Loaded: {api_key[:5]}...{api_key[-4:]}") # Prints only first and last 4 chars
    else:
        print("❌ ERROR: Z.AI API Key NOT found in environment!")
    print("="*60 + "\n")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
