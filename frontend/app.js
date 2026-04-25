// logic of the frontend application
// ── Only one URL needed — your own ingestion.py ──
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
  if (!typedText && !file) {
    showStatus("error", "Please type a note or upload a file.");
    return;
  }

  showStatus("loading", "Processing note… please wait.");
  document.getElementById("submit-btn").disabled = true;

  try {
    // Always send as multipart form — ingestion.py handles the rest
    const form = new FormData();
    form.append("patient_id",  patientId);
    form.append("doctor_id",   doctorId);
    form.append("department",  department);
    form.append("priority",    priority);
    form.append("typed_text",  typedText);
    form.append("file",  file);

    const res = await fetch(INGESTION_URL, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    const data = await res.json();

    if (data.error) {
      showStatus("error", data.error);
      return;
    }

    const alerts = data.system_alerts || [];
    if (alerts.length > 0) {
      showStatus("error", "System alert: " + alerts.join(" | "));
    } else {
      showStatus("success", "Note processed successfully.");
    }

    displayResult(data, { patientId, doctorId, department, priority });

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

  const rxRows = (cd.prescriptions_logged || []).map(rx =>
    `<tr><td>${rx.drug}</td><td>${rx.dosage}</td><td>${rx.route}</td></tr>`
  ).join("");

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

