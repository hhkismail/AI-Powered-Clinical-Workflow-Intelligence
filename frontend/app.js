// Clinical notes page: submit a note to the ingestion service, show what the AI did,
// and show the patient's context (allergies, medications, bed) while the note is written.
// Rendering functions are pure (data in, HTML out) so they can be tested without a
// browser; the controller at the bottom only runs on a real page.

const INGESTION_URL = "http://127.0.0.1:5000/api/process-note";   // Flask ingestion, not FastAPI
const EMR_API = "http://127.0.0.1:3001";

const ACUITY_LABELS = { critical: "Critical", serious: "Serious", stable: "Stable" };
const WARD_LABELS = { icu: "ICU", observation: "observation", general: "general ward" };
const ROUTE_LABELS = { oral: "Oral", iv: "IV", im: "IM", subcutaneous: "SC", inhaled: "Inhaled", topical: "Topical", other: "Other" };
const ALERT_ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>';

// Everything rendered with innerHTML comes from the user, the database or the LLM, so escape it first
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const list = items => (items || []).map(escapeHtml).join(", ");

// ---------- Patient context ----------

function renderContext(p) {
  const orders = p.medication_orders || [];
  const homeMeds = p.active_prescriptions || [];
  return `
    ${(p.allergies || []).length ? `<div class="allergy allergy-banner">${ALERT_ICON}Allergic to ${list(p.allergies)}</div>` : ""}
    <dl class="facts" style="margin-top:${(p.allergies || []).length ? "12px" : "0"}">
      <dt>Patient</dt><dd><strong>${escapeHtml(p.name)}</strong>${p.age != null ? `, ${escapeHtml(p.age)}` : ""}</dd>
      <dt>Acuity</dt><dd>${p.acuity ? `<span class="acuity acuity-${escapeHtml(p.acuity)}">${escapeHtml(ACUITY_LABELS[p.acuity])}</span>` : "Not assessed"}</dd>
      <dt>Bed</dt><dd>${renderBedFact(p)}</dd>
      <dt>Ward orders</dt><dd>${orders.length ? orders.map(m => `${m.route === "iv" ? "<b>IV</b> " : ""}${escapeHtml(m.drug)} ${escapeHtml(m.dose || "")}` +
        (m.allergy_warning ? ` <span class="allergy-inline" title="${escapeHtml(m.allergy_warning)}">${ALERT_ICON}allergy warning</span>` : "")).join("<br>") : "None"}</dd>
      <dt>Regular meds</dt><dd>${homeMeds.length ? list(homeMeds) : "None recorded"}</dd>
      <dt>History</dt><dd>${escapeHtml(p.medical_history || "None recorded")}</dd>
    </dl>
    <p class="context-note">A prescription that conflicts with a known allergy is halted for review, and nothing is changed.</p>`;
}

function renderBedFact(p) {
  const w = p.waiting_for_bed;
  const waitingLink = w ? `<a href="board.html#waiting=${encodeURIComponent(w.id)}">waiting for a${/^[aeiou]/i.test(WARD_LABELS[w.ward_type] || "") ? "n" : ""} ${escapeHtml(WARD_LABELS[w.ward_type] || w.ward_type)} bed</a>` : "";
  if (p.bed) {
    const bed = `<a href="board.html#bed=${encodeURIComponent(p.bed.id)}">${escapeHtml(p.bed.resource_name)}</a> · ${escapeHtml(p.bed.wing)}`;
    return w ? `${bed}<br>${waitingLink.replace("waiting for", "Waiting for a transfer to")}` : bed;
  }
  return w ? waitingLink.replace(">waiting", ">Waiting") : "Not admitted";
}

function renderContextMissing(patientId) {
  return `<div class="notice notice-warning"><strong>No record for ${escapeHtml(patientId)}</strong>
    The note can still be processed, but there is no history to check allergies against.</div>`;
}

// ---------- Result of processing a note ----------

// What the hospital APIs actually did, in plain language
function describeAction(a) {
  const r = a.result || {};
  if (a.tool === "update_record") {
    const params = r.params || {};
    const diagnoses = (params.diagnoses || []).length;
    const parts = [`${diagnoses} ${diagnoses === 1 ? "diagnosis" : "diagnoses"}`,
                   plural((params.prescriptions || []).length, "prescription")];
    if (params.acuity) parts.push(`acuity ${ACUITY_LABELS[params.acuity] || params.acuity}`);
    const suggested = r.care_tasks_suggested || 0;
    const stopped = r.medications_stopped || [];
    const proposed = r.stops_proposed || 0;
    const missing = r.discontinue_not_found || [];
    return `Record updated: ${escapeHtml(parts.join(", "))}` +
           (suggested ? `. ${plural(suggested, "next step")} sent to the ward board for review` : "") +
           (stopped.length ? `. Stopped as the note says: ${list(stopped)}` : "") +
           (proposed ? `. ${plural(proposed, "medication stop")} proposed for a clinician to confirm` : "") +
           (missing.length ? `. Not on the ward orders, so not stopped: ${list(missing)}` : "");
  }
  if (a.tool === "reserve_bed" && r.status === "queued") {
    const label = WARD_LABELS[r.waiting_for] || r.waiting_for;
    return `No ${escapeHtml(label)} bed free: added to the waiting list (position ${escapeHtml(r.position)})`;
  }
  if (a.tool === "reserve_bed") {
    const where = `${escapeHtml(r.allocation?.bed || r.reservation_id)} (${escapeHtml(r.allocation?.ward || "")})`;
    if (r.already_assigned) return `Already in ${where}; no new bed needed`;
    return `Bed reserved: ${where}` + (r.transferred_from ? `, transferred from ${list(r.transferred_from)}` : "");
  }
  if (a.tool === "schedule_appointment") {
    const d = r.scheduled_details || {};
    return `Follow-up booked${d.date ? ` for ${escapeHtml(d.date)}` : ""}${d.location ? ` at ${escapeHtml(d.location)}` : ""}`;
  }
  return escapeHtml(a.tool);
}

function renderResult(data) {
  const alerts = data.system_alerts || [];
  const executed = data.result?.execution_results?.executed_actions || [];
  const alertText = alerts.map(a => `<div>${escapeHtml(a.type)}: ${escapeHtml(a.message)}</div>`).join("");

  let banner;
  if (data.status === "halted_for_clarification") {
    banner = `<div class="notice notice-error"><strong>Halted for review. Nothing was changed.</strong>${alertText}</div>`;
  } else if (data.status === "partial_success") {
    banner = `<div class="notice notice-warning"><strong>Processed with problems. Some actions failed.</strong>${alertText}</div>`;
  } else {
    banner = `<div class="notice notice-success"><strong>Note processed</strong>The patient record and ward board are up to date.</div>`;
  }
  // Possible allergy cross-reactivity doesn't stop a note, but it must be seen
  const allergyWarnings = alerts.filter(a => a.type === "Allergy Warning");
  if (allergyWarnings.length && data.status !== "halted_for_clarification") {
    banner += `<div class="notice notice-warning"><strong>Allergy warning</strong>${allergyWarnings.map(a => `<div>${escapeHtml(a.message)}</div>`).join("")}</div>`;
  }
  if (data.ai === "mock") {
    banner += `<div class="notice notice-info"><strong>Mock AI mode</strong>Planned by keyword rules, not the LLM. Add a Groq key and turn off MOCK_AI for real extraction.</div>`;
  }
  if (data.status === "halted_for_clarification") return banner;

  const record = executed.find(a => a.tool === "update_record")?.result?.params || {};
  const bed = executed.find(a => a.tool === "reserve_bed")?.result;
  const rx = record.prescriptions || [];
  const queued = executed.find(a => a.tool === "reserve_bed" && a.result?.status === "queued");
  const failures = alerts.filter(a => a.type !== "Allergy Warning");
  const actions = executed.map(a => a === queued
      ? `<li><span class="pending">●</span><span>${describeAction(a)}</span></li>`
      : `<li><span class="tick">✓</span><span>${describeAction(a)}</span></li>`)
    .concat(failures.map(a => `<li><span class="cross">✕</span><span>${escapeHtml(a.message)}</span></li>`)).join("");

  return `${banner}
    <div class="section-label">What was done</div>
    <ul class="result-actions">${actions || "<li>No actions were needed</li>"}</ul>
    ${(record.diagnoses || []).length ? `<div class="section-label">Diagnoses</div><p>${list(record.diagnoses)}</p>` : ""}
    ${rx.length ? `<div class="section-label">Prescriptions</div>
      <table class="rx-table"><thead><tr><th>Drug</th><th>Dose</th><th>Route</th><th>Frequency</th></tr></thead><tbody>
      ${rx.map(r => typeof r === "string" ? `<tr><td colspan="4">${escapeHtml(r)}</td></tr>`
        : `<tr><td>${escapeHtml(r.drug)}</td><td>${escapeHtml(r.dosage || r.dose || "–")}</td><td>${escapeHtml(r.route || "–")}</td><td>${escapeHtml(r.frequency || "–")}</td></tr>`).join("")}
      </tbody></table>` : ""}
    ${data.result?.llm_reasoning ? `<details style="margin-top:14px"><summary class="small muted" style="cursor:pointer">${data.ai === "mock" ? "Why the rules chose these actions" : "Why the AI chose these actions"}</summary><p class="small" style="margin-top:8px">${escapeHtml(data.result.llm_reasoning)}</p></details>` : ""}
    ${bed?.reservation_id ? `<p style="margin-top:14px"><a href="board.html#bed=${encodeURIComponent(bed.reservation_id)}">Open on the ward board →</a></p>` : ""}
    ${queued ? `<p style="margin-top:14px"><a href="board.html#waiting=${encodeURIComponent(queued.result.request_id)}">See the waiting list on the ward board →</a></p>` : ""}`;
}

// ---------- Controller (browser only) ----------

if (typeof document !== "undefined") {
  const $ = id => document.getElementById(id);
  const clinicianInput = $("clinician-id");
  try { clinicianInput.value = localStorage.getItem("ophia.clinicianId") || ""; } catch (e) { /* storage blocked */ }
  clinicianInput.addEventListener("change", () => {
    try { localStorage.setItem("ophia.clinicianId", clinicianInput.value.trim()); } catch (e) { /* storage blocked */ }
  });

  function formError(message) {
    $("form-error").textContent = message;
    $("form-error").classList.toggle("hidden", !message);
  }

  // Patient context, refreshed as the ID is typed
  let contextTimer = null;
  let contextFor = null;
  async function loadContext() {
    const id = $("patient-id").value.trim();
    contextFor = id;
    if (!id) {
      $("context").innerHTML = `<p class="context-empty">Enter a patient ID to see allergies, current medications and bed.</p>`;
      return;
    }
    try {
      const res = await fetch(`${EMR_API}/api/patient/${encodeURIComponent(id)}`);
      if (contextFor !== id) return;   // a newer ID was typed meanwhile
      if (res.status === 404) { $("context").innerHTML = renderContextMissing(id); return; }
      const data = await res.json();
      if (!res.ok) throw new Error(data.message || res.status);
      $("context").innerHTML = renderContext(data);
    } catch (err) {
      if (contextFor === id) $("context").innerHTML = `<p class="context-empty">Couldn't load the patient record (${escapeHtml(err.message)}). Is server.py running?</p>`;
    }
  }
  $("patient-id").addEventListener("input", () => { clearTimeout(contextTimer); contextTimer = setTimeout(loadContext, 350); });
  loadContext();

  // File attachment
  const fileInput = $("file-input");
  function showFile() {
    const file = fileInput.files[0];
    $("file-name").textContent = file ? file.name : "Or attach a photo of a handwritten note, or a voice memo";
    $("file-clear").classList.toggle("hidden", !file);
    $("file-pick").textContent = file ? "Change" : "Attach";
  }
  fileInput.addEventListener("change", showFile);
  $("file-clear").addEventListener("click", () => { fileInput.value = ""; showFile(); });

  $("clear-btn").addEventListener("click", () => {
    $("typed-text").value = "";
    fileInput.value = "";
    showFile();
    formError("");
    $("status-area").classList.add("hidden");
    $("result-panel").classList.add("hidden");
  });

  $("note-form").addEventListener("submit", async event => {
    event.preventDefault();
    const patientId = $("patient-id").value.trim();
    const clinician = clinicianInput.value.trim();
    const typedText = $("typed-text").value.trim();

    if (!clinician) { formError("Enter your clinician ID in the sidebar first."); clinicianInput.focus(); return; }
    if (!patientId) { formError("Enter a patient ID."); $("patient-id").focus(); return; }
    if (!typedText && !fileInput.files.length) { formError("Type a note or attach a file."); $("typed-text").focus(); return; }
    formError("");

    const form = new FormData();
    form.append("patient_id", patientId);
    form.append("doctor_id", clinician);
    form.append("department", $("department").value);
    form.append("priority", document.querySelector("input[name='priority']:checked").value);
    form.append("typed_text", typedText);
    if (fileInput.files.length) form.append("file", fileInput.files[0]);

    const button = $("submit-btn");
    button.disabled = true;
    button.textContent = "Processing…";
    $("result-panel").classList.add("hidden");
    $("status-area").className = "notice notice-info";
    $("status-area").textContent = "Reading the note and checking it against the patient record. This usually takes a few seconds.";

    try {
      const res = await fetch(INGESTION_URL, { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Server error: ${res.status}`);
      $("status-area").classList.add("hidden");
      $("result-content").innerHTML = renderResult(data);
      $("result-panel").classList.remove("hidden");
      $("result-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
      loadContext();   // acuity, bed and medications may have changed
    } catch (err) {
      $("status-area").className = "notice notice-error";
      $("status-area").textContent = `Something went wrong: ${err.message}`;
    } finally {
      button.disabled = false;
      button.textContent = "Process note";
    }
  });
}
