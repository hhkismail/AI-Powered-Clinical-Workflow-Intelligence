// Point to the Flask ingestion server, NOT FastAPI
const INGESTION_URL = "http://127.0.0.1:5000/api/process-note"; 

document.getElementById("file-input").addEventListener("change", function () {
  document.getElementById("file-name").textContent =
    this.files[0]?.name || "No file selected";
});

async function submitNote() {
  const patientId  = document.getElementById("patient-id").value.trim();
  const doctorId   = document.getElementById("doctor-id").value.trim();
  const department = document.getElementById("department").value;
  const priority   = document.getElementById("priority").value;
  const typedText  = document.getElementById("typed-text").value.trim();
  const fileInput  = document.getElementById("file-input");

  if (!patientId || !doctorId) {
    showStatus("error", "Please enter both Patient ID and Doctor ID.");
    return;
  }
  
  if (!typedText && fileInput.files.length === 0) {
    showStatus("error", "Please type a note or upload a file.");
    return;
  }

  showStatus("loading", "Processing note… please wait.");
  document.getElementById("submit-btn").disabled = true;

  try {
    // 1. Send data as FormData so ingestion.py can read the file
    const form = new FormData();
    form.append("patient_id", patientId);
    form.append("doctor_id", doctorId);
    form.append("department", department);
    form.append("priority", priority);
    form.append("typed_text", typedText);

    if (fileInput.files.length > 0) {
      form.append("file", fileInput.files[0]);
    }

    const res = await fetch(INGESTION_URL, {
      method: "POST",
      body: form
    });
    
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const backendData = await res.json();

    // 2. Handle the AI Safety Halts
    if (backendData.status === "halted_for_clarification") {
      const alerts = backendData.system_alerts || [];
      showStatus("error", "System alert: " + alerts.map(a => a.message).join(" | "));
      return;
    }

    // 3. Translate the FastAPI success data to match Fitri/Anna's UI variables
    const actionsList = backendData.result?.execution_results?.executed_actions || [];
    
    // Dig into the update_record action safely
    const updateAction = actionsList.find(a => a.tool === "update_record") || {};
    
    // THE GOD-MODE EXTRACTOR: Check every possible folder Rizwi or Groq could have hidden the data in
    const extractedData = updateAction.params 
                       || updateAction.result?.params 
                       || updateAction.result?.data 
                       || updateAction.result?.record
                       || updateAction.result
                       || {};

    // Forcibly grab the arrays no matter what vocabulary the AI used
    const foundSymptoms = extractedData.diagnoses || extractedData.symptoms || extractedData.diagnosis || [];
    const foundPrescriptions = extractedData.prescriptions || extractedData.medications || extractedData.drugs || [];

    const formattedData = {
        status: backendData.status,
        actions: actionsList,
        system_alerts: backendData.system_alerts || [],
        structured_clinical_data: {
            symptoms: foundSymptoms,
            diagnosis_codes: foundSymptoms,
            prescriptions_logged: foundPrescriptions
        }
    };

    showStatus("success", "Note processed successfully.");
    displayResult(formattedData, { patientId, doctorId, department, priority });

  } catch (err) {
    showStatus("error", `Something went wrong: ${err.message}`);
  } finally {
    document.getElementById("submit-btn").disabled = false;
  }
}

function displayResult(data, meta) {
  const panel   = document.getElementById("results-panel");
  const content = document.getElementById("result-content");
  const cd      = data.structured_clinical_data || {};
  const actions = data.actions || [];
  const alerts  = data.system_alerts || [];

  const alertHtml = alerts.length
    ? `<div class="alert-box"><strong>System alert</strong><p>${alerts.join("<br>")}</p></div>`
    : "";

  const rxRows = (cd.prescriptions_logged || []).map(rx => {
  // Fallback 1: If Groq just outputs a flat string instead of an object
  if (typeof rx === 'string') {
    return `<tr><td>${rx}</td><td>-</td><td>-</td></tr>`;
  }
  
  // Fallback 2: Check every possible word Groq might use for the keys
  const drugName = rx.drug || rx.medication || rx.name || "Unknown";
  const dosage = rx.dosage || rx.dose || rx.amount || "-";
  const route = rx.route || rx.method || rx.frequency || "-";

  return `<tr><td>${drugName}</td><td>${dosage}</td><td>${route}</td></tr>`;
}).join("");

  const actionTags = actions.map(a =>
    `<span class="badge">${a.tool}</span>`
  ).join(" ");

  
  content.innerHTML = `
    ${alertHtml}
    <div class="result-row"><span class="result-label">Patient</span><span class="result-value">${meta.patientId}</span></div>
    <div class="result-row"><span class="result-label">Doctor</span><span class="result-value">${meta.doctorId}</span></div>
    <div class="result-row"><span class="result-label">Department</span><span class="result-value">${meta.department}</span></div>
    <div class="result-row"><span class="result-label">Priority</span><span class="result-value badge">${meta.priority}</span></div>
    <div class="result-row"><span class="result-label">Status</span><span class="result-value" style="color:var(--color-text-success)">${data.status}</span></div>
    <div class="section-label" style="margin-top:14px">Symptoms</div>
    <p style="font-size:13px;color:var(--color-text-secondary)">${(cd.symptoms || []).join(", ") || "None"}</p>
    <div class="section-label">Diagnosis codes</div>
    <p style="font-size:13px;color:var(--color-text-secondary)">${(cd.diagnosis_codes || []).join(", ") || "None"}</p>
    <div class="section-label">Prescriptions</div>
    <table class="rx-table">
      <thead><tr><th>Drug</th><th>Dosage</th><th>Route</th></tr></thead>
      <tbody>${rxRows || "<tr><td colspan='3'>None logged</td></tr>"}</tbody>
    </table>
    <div class="section-label">Actions triggered</div>
    <p>${actionTags || "None"}</p>
  `;
  panel.classList.remove("hidden");
}

function showStatus(type, message) {
  const area = document.getElementById("status-area");
  area.className = `status status-${type}`;
  area.textContent = message;
  area.classList.remove("hidden");
}