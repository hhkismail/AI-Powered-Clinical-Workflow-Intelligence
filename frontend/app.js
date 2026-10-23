// Point to the Flask ingestion server, NOT FastAPI
const INGESTION_URL = "http://127.0.0.1:5000/api/process-note";

// Everything rendered with innerHTML comes from the user or the LLM, so escape it first
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
}

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
    
    const backendData = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(backendData.error || `Server error: ${res.status}`);

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

    // partial_success: some actions ran, others were rejected or failed (listed in system_alerts)
    if (backendData.status === "partial_success") {
      showStatus("error", "Note processed, but some actions failed. See the alerts below.");
    } else {
      showStatus("success", "Note processed successfully.");
    }
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
    ? `<div class="alert-box"><strong>System alert</strong><p>${alerts.map(a =>
        typeof a === "string" ? escapeHtml(a) : `${escapeHtml(a.type)}: ${escapeHtml(a.message)}`
      ).join("<br>")}</p></div>`
    : "";

  const rxRows = (cd.prescriptions_logged || []).map(rx => {
  // Fallback 1: If Groq just outputs a flat string instead of an object
  if (typeof rx === 'string') {
    return `<tr><td>${escapeHtml(rx)}</td><td>-</td><td>-</td></tr>`;
  }

  // Fallback 2: Check every possible word Groq might use for the keys
  const drugName = rx.drug || rx.medication || rx.name || "Unknown";
  const dosage = rx.dosage || rx.dose || rx.amount || "-";
  const route = rx.route || rx.method || rx.frequency || "-";

  return `<tr><td>${escapeHtml(drugName)}</td><td>${escapeHtml(dosage)}</td><td>${escapeHtml(route)}</td></tr>`;
}).join("");

  const actionTags = actions.map(a =>
    `<span class="badge">${escapeHtml(a.tool)}</span>`
  ).join(" ");

  const statusColor = data.status === "success" ? "var(--color-text-success)" : "var(--color-text-danger, #b42318)";

  content.innerHTML = `
    ${alertHtml}
    <div class="result-row"><span class="result-label">Patient</span><span class="result-value">${escapeHtml(meta.patientId)}</span></div>
    <div class="result-row"><span class="result-label">Doctor</span><span class="result-value">${escapeHtml(meta.doctorId)}</span></div>
    <div class="result-row"><span class="result-label">Department</span><span class="result-value">${escapeHtml(meta.department)}</span></div>
    <div class="result-row"><span class="result-label">Priority</span><span class="result-value badge">${escapeHtml(meta.priority)}</span></div>
    <div class="result-row"><span class="result-label">Status</span><span class="result-value" style="color:${statusColor}">${escapeHtml(data.status)}</span></div>
    <div class="section-label" style="margin-top:14px">Symptoms</div>
    <p style="font-size:13px;color:var(--color-text-secondary)">${(cd.symptoms || []).map(escapeHtml).join(", ") || "None"}</p>
    <div class="section-label">Diagnosis codes</div>
    <p style="font-size:13px;color:var(--color-text-secondary)">${(cd.diagnosis_codes || []).map(escapeHtml).join(", ") || "None"}</p>
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