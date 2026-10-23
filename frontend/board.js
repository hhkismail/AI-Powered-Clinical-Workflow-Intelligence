// Ward board: every bed, who's in it, how sick they are, what they're receiving and
// what should happen next. Data comes from the Mock EMR API (server.py); nothing here
// is hardcoded. Rendering functions are pure (data in, HTML out) so they can be tested
// without a browser; the controller at the bottom only runs on a real page.

const API_BASE = "http://127.0.0.1:3001";
const REFRESH_MS = 5000;

const ACUITY_LABELS = { critical: "Critical", serious: "Serious", stable: "Stable" };
const STATUS_LABELS = { available: "Available", occupied: "Occupied", cleaning: "Being cleaned", maintenance: "Maintenance" };
const ROUTE_LABELS = { oral: "Oral", iv: "IV", im: "IM", subcutaneous: "SC", inhaled: "Inhaled", topical: "Topical", other: "Other" };
const ALERT_ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>';
const CLOSE_ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';

// Everything rendered with innerHTML comes from the database or the LLM, so escape it first
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
}

function relativeTime(iso, now) {
  if (!iso) return "";
  const seconds = Math.max(0, Math.round(((now ?? Date.now()) - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const allergyLine = p => (p.allergies || []).length
  ? `<div class="allergy">${ALERT_ICON}Allergic to ${p.allergies.map(escapeHtml).join(", ")}</div>` : "";

function medicationChip(m) {
  const route = ROUTE_LABELS[m.route];
  return `<span class="med ${m.route === "iv" ? "med-iv" : ""}">${route ? `<span class="route">${escapeHtml(route)}</span>` : ""}` +
         `<b>${escapeHtml(m.drug)}</b>${escapeHtml(m.dose || "")}</span>`;
}

function patientsOf(board) {
  return (board.wards || []).flatMap(w => w.beds).map(b => b.patient).filter(Boolean);
}

function renderSummary(board) {
  const summary = board.summary || {};
  const beds = summary.beds || {};
  const total = Object.values(beds).reduce((sum, n) => sum + n, 0);
  const patients = patientsOf(board);
  const critical = patients.filter(p => p.acuity === "critical").map(p => escapeHtml(p.name));
  const pending = summary.pending_suggestions || 0;
  const tile = (label, value, note, cls) =>
    `<div class="kpi ${cls || ""}"><small>${label}</small><strong>${value}</strong><em>${note}</em></div>`;
  return [
    tile("Beds available", `${beds.available || 0}<span> / ${total}</span>`,
         beds.cleaning ? `${plural(beds.cleaning, "bed")} being cleaned` : "None being cleaned"),
    tile("Occupied", beds.occupied || 0, `${plural(patients.length, "patient")} assigned`),
    tile("Critical", summary.critical_patients || 0, critical.length ? critical.join(", ") : "No critical patients", "kpi-critical"),
    tile("Suggestions to review", pending, pending ? "Waiting on a clinician" : "All reviewed", "kpi-review")
  ].join("");
}

function renderBedCard(bed, openBedId) {
  const head = `
    <div class="card-head">
      <div><div class="bed-name">${escapeHtml(bed.name)}</div>
      <div class="bed-sub">${escapeHtml(bed.id)} · ${escapeHtml(bed.department || "")}${bed.type === "DIAGNOSTIC" ? " · Diagnostic" : ""}</div></div>
      <span class="status status-${escapeHtml(bed.status)}">${escapeHtml(STATUS_LABELS[bed.status] || bed.status)}</span>
    </div>`;

  const p = bed.patient;
  if (!p) {
    const action = bed.status === "cleaning"
      ? `<button class="btn btn-sm" data-action="mark-clean" data-bed="${escapeHtml(bed.id)}">Mark clean</button>` : "";
    return `<article class="bed-card bed-empty">${head}${action}</article>`;
  }

  const meds = p.medications || [];
  const tasks = p.tasks || [];
  const suggested = tasks.filter(t => t.status === "suggested").length;
  const accepted = tasks.filter(t => t.status === "accepted").length;

  return `
    <article class="bed-card bed-occupied acuity-${escapeHtml(p.acuity || "unknown")}${bed.id === openBedId ? " is-open" : ""}"
             tabindex="0" role="button" data-action="open" data-bed="${escapeHtml(bed.id)}"
             aria-label="Open ${escapeHtml(p.name)}, ${escapeHtml(bed.name)}">
      ${head}
      <div class="patient-block">
        <div class="patient-row">
          <div><div class="patient-name">${escapeHtml(p.name)}</div>
          <div class="patient-meta">${escapeHtml(p.patient_id)}${p.age != null ? ` · ${escapeHtml(p.age)} y` : ""}</div></div>
          <span class="acuity">${escapeHtml(ACUITY_LABELS[p.acuity] || "Not assessed")}</span>
        </div>
        ${allergyLine(p)}
      </div>
      <div class="section-label">Medications</div>
      ${meds.length ? `<div class="meds">${meds.slice(0, 4).map(medicationChip).join("")}</div>${meds.length > 4 ? `<div class="bed-sub">+${meds.length - 4} more</div>` : ""}`
                    : `<div class="bed-sub">None active</div>`}
      <div class="card-foot">
        <span>${accepted ? `${plural(accepted, "task")} in progress` : "No tasks in progress"}</span>
        ${suggested ? `<span class="to-review">${suggested} to review</span>` : ""}
      </div>
    </article>`;
}

// Beds without a patient are compact tiles, so a wing of many beds stays scannable
function renderBedTile(bed) {
  const action = bed.status === "cleaning"
    ? `<button class="tile-action" data-action="mark-clean" data-bed="${escapeHtml(bed.id)}">Mark clean</button>` : "";
  return `
    <div class="bed-tile tile-${escapeHtml(bed.status)}" title="${escapeHtml(bed.id)}">
      <span class="tile-name">${escapeHtml(bed.name)}</span>
      <span class="status status-${escapeHtml(bed.status)}">${escapeHtml(STATUS_LABELS[bed.status] || bed.status)}</span>
      ${action}
    </div>`;
}

function renderBoard(board, openBedId) {
  return (board.wards || []).map(ward => {
    const occupied = ward.beds.filter(b => b.patient);
    const others = ward.beds.filter(b => !b.patient);
    const free = ward.beds.filter(b => b.status === "available").length;
    return `
    <section class="wing">
      <h2>${escapeHtml(ward.wing)} <span>${free} of ${ward.beds.length} free</span></h2>
      ${occupied.length ? `<div class="bed-list">${occupied.map(b => renderBedCard(b, openBedId)).join("")}</div>` : ""}
      ${others.length ? `<div class="bed-tiles">${others.map(renderBedTile).join("")}</div>` : ""}
    </section>`;
  }).join("");
}

function renderTask(t) {
  const meta = t.status === "accepted"
    ? `Accepted by ${escapeHtml(t.decided_by || "unknown")}`
    : `Suggested by ${t.suggested_by === "ai" ? "AI" : "a clinician"}`;
  const buttons = t.status === "suggested"
    ? `<button class="btn btn-sm btn-accept" data-action="decide" data-decision="accept" data-task="${escapeHtml(t.id)}">Accept</button>
       <button class="btn btn-sm btn-reject" data-action="decide" data-decision="reject" data-task="${escapeHtml(t.id)}">Reject</button>`
    : `<button class="btn btn-sm" data-action="decide" data-decision="done" data-task="${escapeHtml(t.id)}">Mark done</button>`;
  return `
    <li class="task task-${escapeHtml(t.status)}">
      <div class="task-text">${escapeHtml(t.description)}</div>
      <div class="task-meta"><span class="category">${escapeHtml(t.category)}</span><span>${meta}</span></div>
      <div class="task-buttons">${buttons}</div>
    </li>`;
}

function renderDischarge(bed, confirming) {
  const p = bed.patient;
  if (!confirming) {
    return `<div class="discharge"><button class="btn" data-action="discharge-start">Discharge patient…</button></div>`;
  }
  const meds = (p.medications || []).length;
  const open = (p.tasks || []).length;
  return `
    <div class="discharge discharge-confirm" role="group" aria-label="Confirm discharge">
      <p><strong>Discharge ${escapeHtml(p.name)}?</strong></p>
      <p class="muted small">${escapeHtml(bed.name)} goes to cleaning. ${plural(meds, "active medication")} will be marked completed
        and ${plural(open, "open task")} cancelled. Nothing is deleted.</p>
      <div class="task-buttons">
        <button class="btn btn-sm btn-danger" data-action="discharge-confirm" data-bed="${escapeHtml(bed.id)}">Discharge</button>
        <button class="btn btn-sm" data-action="discharge-cancel">Cancel</button>
      </div>
    </div>`;
}

function renderPanel(bed, now, confirmingDischarge) {
  const p = bed.patient;
  const meds = p.medications || [];
  const tasks = p.tasks || [];
  const medLine = m => `<li><span class="route ${m.route === "iv" ? "route-iv" : ""}">${escapeHtml(ROUTE_LABELS[m.route] || "")}</span>
    <div><b>${escapeHtml(m.drug)}</b> ${escapeHtml(m.dose || "")}${m.frequency ? `<small>${escapeHtml(m.frequency)}</small>` : ""}</div></li>`;
  return `
    <div class="drawer-head">
      <div><h2>${escapeHtml(p.name)}</h2>
      <p>${escapeHtml(p.patient_id)}${p.age != null ? ` · ${escapeHtml(p.age)} years` : ""} · ${escapeHtml(bed.name)} (${escapeHtml(bed.id)})</p></div>
      <button class="btn-close" data-action="close" aria-label="Close">${CLOSE_ICON}</button>
    </div>
    <div class="drawer-body">
      <div class="acuity-line acuity-${escapeHtml(p.acuity || "unknown")}">
        <span class="acuity">${escapeHtml(ACUITY_LABELS[p.acuity] || "Not assessed")}</span>
        ${p.acuity_updated_at ? `<span class="muted small">Assessed ${escapeHtml(relativeTime(p.acuity_updated_at, now))}</span>` : ""}
      </div>
      ${(p.allergies || []).length ? `<div class="allergy allergy-banner">${ALERT_ICON}Allergic to ${p.allergies.map(escapeHtml).join(", ")}</div>` : ""}
      ${p.medical_history ? `<div class="section-label">History</div><p>${escapeHtml(p.medical_history)}</p>` : ""}
      <div class="section-label">Active medications</div>
      ${meds.length ? `<ul class="med-lines">${meds.map(medLine).join("")}</ul>` : `<p class="muted">None active</p>`}
      <div class="section-label">Next steps</div>
      <p class="muted small">AI suggestions only become tasks once a clinician accepts them.</p>
      ${tasks.length ? `<ul class="task-list">${tasks.map(renderTask).join("")}</ul>` : `<p class="muted">No open tasks</p>`}
      ${renderDischarge(bed, confirmingDischarge)}
    </div>`;
}

function findBed(board, bedId) {
  for (const ward of board.wards || []) {
    for (const bed of ward.beds) if (bed.id === bedId) return bed;
  }
  return null;
}

// ---------- Controller (browser only) ----------

if (typeof document !== "undefined") {
  // board.html#bed=RES-ICU-01 opens that bed's panel, so a patient can be linked to
  const bedFromHash = () => decodeURIComponent((location.hash.match(/^#bed=(.+)$/) || [])[1] || "") || null;
  const state = { board: null, openBed: bedFromHash(), loadedAt: null, confirmDischarge: false };
  const $ = id => document.getElementById(id);

  // Shared with the notes page, so a clinician only enters their ID once
  const clinicianInput = $("clinician-id");
  try { clinicianInput.value = localStorage.getItem("ophia.clinicianId") || ""; } catch (e) { /* storage blocked */ }
  clinicianInput.addEventListener("change", () => {
    try { localStorage.setItem("ophia.clinicianId", clinicianInput.value.trim()); } catch (e) { /* storage blocked */ }
  });

  function showError(message) {
    const banner = $("board-error");
    banner.textContent = message;
    banner.classList.toggle("hidden", !message);
  }

  function render() {
    if (!state.board) return;
    $("summary").innerHTML = renderSummary(state.board);
    $("board").innerHTML = renderBoard(state.board, state.openBed);
    $("nav-review-count").textContent = state.board.summary?.pending_suggestions || "";
    const bed = state.openBed && findBed(state.board, state.openBed);
    if (bed && bed.patient) {
      $("panel-content").innerHTML = renderPanel(bed, undefined, state.confirmDischarge);
      $("panel").classList.remove("hidden");
    } else {
      // The patient may have moved or been discharged since the link was made
      $("panel").classList.add("hidden");
    }
  }

  function setOpenBed(bedId) {
    state.openBed = bedId;
    state.confirmDischarge = false;
    history.replaceState(null, "", bedId ? `#bed=${encodeURIComponent(bedId)}` : location.pathname);
    render();
    if (bedId) $("panel").querySelector(".btn-close")?.focus();
  }
  window.addEventListener("hashchange", () => { state.openBed = bedFromHash(); render(); });

  async function load() {
    try {
      const res = await fetch(`${API_BASE}/api/ward-board`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || `Server error: ${res.status}`);
      state.board = data;
      state.loadedAt = Date.now();
      showError("");
      render();
    } catch (err) {
      showError(`Can't reach the ward board API (${err.message}). Is server.py running on port 3001?`);
    }
  }

  async function post(path, body) {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {})
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || `Server error: ${res.status}`);
    return data;
  }

  document.addEventListener("click", async event => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    try {
      if (action === "open") {
        setOpenBed(target.dataset.bed);
      } else if (action === "close") {
        setOpenBed(null);
      } else if (action === "decide") {
        const clinician = clinicianInput.value.trim();
        if (!clinician) {
          showError("Enter your clinician ID in the sidebar before deciding on a task.");
          clinicianInput.focus();
          return;
        }
        target.disabled = true;
        await post(`/api/tasks/${encodeURIComponent(target.dataset.task)}/decision`,
                   { decision: target.dataset.decision, clinician_id: clinician });
        await load();
      } else if (action === "discharge-start" || action === "discharge-cancel") {
        state.confirmDischarge = action === "discharge-start";
        render();
      } else if (action === "discharge-confirm") {
        const clinician = clinicianInput.value.trim();
        if (!clinician) {
          showError("Enter your clinician ID in the sidebar before discharging a patient.");
          clinicianInput.focus();
          return;
        }
        target.disabled = true;
        await post(`/api/beds/${encodeURIComponent(target.dataset.bed)}/discharge`, { clinician_id: clinician });
        setOpenBed(null);   // the patient has left the bed
        await load();
      } else if (action === "mark-clean") {
        target.disabled = true;
        await post(`/api/beds/${encodeURIComponent(target.dataset.bed)}/mark-clean`);
        await load();
      }
    } catch (err) {
      showError(err.message);
      await load();
    }
  });

  // Keyboard access for bed cards
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && state.openBed) setOpenBed(null);
    if ((event.key === "Enter" || event.key === " ") && event.target.matches?.(".bed-card[data-action='open']")) {
      event.preventDefault();
      event.target.click();
    }
  });

  // Poll while the tab is visible; refresh straight away when it comes back
  setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
  setInterval(() => {
    if (state.loadedAt) $("updated").textContent = `Updated ${relativeTime(new Date(state.loadedAt).toISOString())}`;
  }, 1000);
  load();
}
