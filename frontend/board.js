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
  // A drug given despite possible allergy cross-reactivity stays flagged
  const warn = m.allergy_warning
    ? ` med-warn" title="${escapeHtml(m.allergy_warning)}` : "";
  return `<span class="med ${m.route === "iv" ? "med-iv" : ""}${warn}">${m.allergy_warning ? ALERT_ICON : ""}` +
         `${route ? `<span class="route">${escapeHtml(route)}</span>` : ""}` +
         `<b>${escapeHtml(m.drug)}</b>${escapeHtml(m.dose || "")}</span>`;
}

// Everyone on the board, in a bed or waiting for one, counted once
function patientsOf(board) {
  const all = (board.wards || []).flatMap(w => w.beds).map(b => b.patient)
    .concat((board.waiting || []).map(w => w.patient)).filter(Boolean);
  return [...new Map(all.map(p => [p.patient_id, p])).values()];
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
    tile("Occupied", beds.occupied || 0, summary.waiting
      ? `${plural(summary.waiting, "patient")} waiting for a bed` : "Nobody waiting for a bed"),
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
  const isStop = t.proposed_action === "stop_medication";
  const meta = t.status === "accepted"
    ? `Accepted by ${escapeHtml(t.decided_by || "unknown")}`
    : isStop ? "AI proposes stopping this medication"
    : `Suggested by ${t.suggested_by === "ai" ? "AI" : "a clinician"}`;
  // Accepting a stop proposal stops the drug, so the buttons say exactly that
  const [yes, no] = isStop ? ["Stop it", "Keep it"] : ["Accept", "Reject"];
  const buttons = t.status === "suggested"
    ? `<button class="btn btn-sm ${isStop ? "btn-danger" : "btn-accept"}" data-action="decide" data-decision="accept" data-task="${escapeHtml(t.id)}">${yes}</button>
       <button class="btn btn-sm btn-reject" data-action="decide" data-decision="reject" data-task="${escapeHtml(t.id)}">${no}</button>`
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

// Acuity, allergies, history, medications and tasks: shared by bed and waiting-list drawers
function renderPatientDetails(p, now, confirmStopId) {
  const meds = p.medications || [];
  const tasks = p.tasks || [];
  const stopControl = m => m.id === confirmStopId
    ? `<div class="med-stop-confirm">Stop ${escapeHtml(m.drug)}?
         <button class="btn btn-sm btn-danger" data-action="stop-med-confirm" data-med="${escapeHtml(m.id)}">Stop</button>
         <button class="btn btn-sm" data-action="stop-med-cancel">Cancel</button></div>`
    : `<button class="btn-link" data-action="stop-med-start" data-med="${escapeHtml(m.id)}">Stop</button>`;
  const medLine = m => `<li><span class="route ${m.route === "iv" ? "route-iv" : ""}">${escapeHtml(ROUTE_LABELS[m.route] || "")}</span>
    <div><b>${escapeHtml(m.drug)}</b> ${escapeHtml(m.dose || "")}${m.frequency ? `<small>${escapeHtml(m.frequency)}</small>` : ""}
      ${m.allergy_warning ? `<div class="med-warning-text">${ALERT_ICON}${escapeHtml(m.allergy_warning)}</div>` : ""}</div>
    ${m.id ? stopControl(m) : ""}</li>`;
  return `
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
      ${tasks.length ? `<ul class="task-list">${tasks.map(renderTask).join("")}</ul>` : `<p class="muted">No open tasks</p>`}`;
}

function drawerHead(p, subtitle) {
  return `
    <div class="drawer-head">
      <div><h2>${escapeHtml(p.name)}</h2>
      <p>${escapeHtml(p.patient_id)}${p.age != null ? ` · ${escapeHtml(p.age)} years` : ""} · ${subtitle}</p></div>
      <button class="btn-close" data-action="close" aria-label="Close">${CLOSE_ICON}</button>
    </div>`;
}

function renderPanel(bed, now, confirmingDischarge, confirmStopId) {
  return `
    ${drawerHead(bed.patient, `${escapeHtml(bed.name)} (${escapeHtml(bed.id)})`)}
    <div class="drawer-body">
      ${renderPatientDetails(bed.patient, now, confirmStopId)}
      ${renderDischarge(bed, confirmingDischarge)}
    </div>`;
}

// ---------- Waiting for a bed ----------

const WARD_LABELS = { icu: "ICU", observation: "observation", general: "general ward" };

function waitingActions(w) {
  const label = WARD_LABELS[w.ward_type] || w.ward_type;
  const free = w.free_matching_beds || 0;
  const assign = free
    ? `<button class="btn btn-sm btn-primary" data-action="assign" data-request="${escapeHtml(w.request_id)}">Assign bed</button>`
    : `<button class="btn btn-sm" disabled title="No ${escapeHtml(label)} bed is free">No ${escapeHtml(label)} bed free</button>`;
  return `${assign}<button class="btn btn-sm" data-action="cancel-request" data-request="${escapeHtml(w.request_id)}">Remove</button>`;
}

function waitingSubtitle(w, now) {
  const label = WARD_LABELS[w.ward_type] || w.ward_type;
  const since = w.requested_at ? `, waiting ${escapeHtml(relativeTime(w.requested_at, now).replace(" ago", ""))}` : "";
  return w.current_bed
    ? `In ${escapeHtml(w.current_bed.name)}, needs an ${escapeHtml(label)} bed${since}`
    : `Needs a${/^[aeiou]/i.test(label) ? "n" : ""} ${escapeHtml(label)} bed${since}`;
}

function renderWaiting(board, openRequestId, now) {
  const waiting = board.waiting || [];
  if (!waiting.length) return "";
  const rows = waiting.map(w => {
    const p = w.patient || { name: "Unknown patient", patient_id: "" };
    return `
      <li class="waiting-row acuity-${escapeHtml(p.acuity || "unknown")}${w.request_id === openRequestId ? " is-open" : ""}"
          tabindex="0" role="button" data-action="open-waiting" data-request="${escapeHtml(w.request_id)}"
          aria-label="Open ${escapeHtml(p.name)}, waiting for a bed">
        <div class="waiting-who">
          <div class="patient-name">${escapeHtml(p.name)} <span class="patient-meta">${escapeHtml(p.patient_id)}${p.age != null ? ` · ${escapeHtml(p.age)} y` : ""}</span></div>
          <div class="bed-sub">${waitingSubtitle(w, now)}${w.clinical_reason ? ` · ${escapeHtml(w.clinical_reason)}` : ""}</div>
          ${allergyLine(p)}
        </div>
        <span class="acuity">${escapeHtml(ACUITY_LABELS[p.acuity] || "Not assessed")}</span>
        <div class="waiting-actions">${waitingActions(w)}</div>
      </li>`;
  }).join("");
  return `
    <section class="waiting panel">
      <h2>Waiting for a bed <span>${waiting.length}</span></h2>
      <ul class="waiting-list">${rows}</ul>
    </section>`;
}

function renderWaitingPanel(w, now, confirmStopId) {
  return `
    ${drawerHead(w.patient, waitingSubtitle(w, now))}
    <div class="drawer-body">
      ${renderPatientDetails(w.patient, now, confirmStopId)}
      <div class="discharge"><div class="task-buttons">${waitingActions(w)}</div></div>
    </div>`;
}

function findBed(board, bedId) {
  for (const ward of board.wards || []) {
    for (const bed of ward.beds) if (bed.id === bedId) return bed;
  }
  return null;
}

function findWaiting(board, requestId) {
  return (board.waiting || []).find(w => w.request_id === requestId) || null;
}

// ---------- Controller (browser only) ----------

if (typeof document !== "undefined") {
  // board.html#bed=RES-ICU-01 or #waiting=<request id> opens that patient's drawer, so it can be linked to
  const openFromHash = () => {
    const m = location.hash.match(/^#(bed|waiting)=(.+)$/);
    return m ? { kind: m[1], id: decodeURIComponent(m[2]) } : null;
  };
  const state = { board: null, open: openFromHash(), loadedAt: null, confirmDischarge: false, confirmStop: null };
  const openId = kind => (state.open && state.open.kind === kind ? state.open.id : null);
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
    $("waiting").innerHTML = renderWaiting(state.board, openId("waiting"));
    $("board").innerHTML = renderBoard(state.board, openId("bed"));
    $("nav-review-count").textContent = state.board.summary?.pending_suggestions || "";

    const bed = openId("bed") && findBed(state.board, openId("bed"));
    const waiting = openId("waiting") && findWaiting(state.board, openId("waiting"));
    if (bed && bed.patient) {
      $("panel-content").innerHTML = renderPanel(bed, undefined, state.confirmDischarge, state.confirmStop);
      $("panel").classList.remove("hidden");
    } else if (waiting && waiting.patient) {
      $("panel-content").innerHTML = renderWaitingPanel(waiting, undefined, state.confirmStop);
      $("panel").classList.remove("hidden");
    } else {
      // The patient may have moved, got a bed or been discharged since the link was made
      $("panel").classList.add("hidden");
    }
  }

  function setOpen(kind, id) {
    state.open = kind && id ? { kind, id } : null;
    state.confirmDischarge = false;
    state.confirmStop = null;
    history.replaceState(null, "", state.open ? `#${kind}=${encodeURIComponent(id)}` : location.pathname);
    render();
    if (state.open) $("panel").querySelector(".btn-close")?.focus();
  }
  window.addEventListener("hashchange", () => { state.open = openFromHash(); render(); });

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

  // Decisions are recorded against a clinician, so ask for the ID before acting
  function clinicianFor(what) {
    const clinician = clinicianInput.value.trim();
    if (!clinician) {
      showError(`Enter your clinician ID in the sidebar before ${what}.`);
      clinicianInput.focus();
    }
    return clinician;
  }

  document.addEventListener("click", async event => {
    const target = event.target.closest("[data-action]");
    if (!target || target.disabled) return;
    const action = target.dataset.action;
    try {
      if (action === "open") {
        setOpen("bed", target.dataset.bed);
      } else if (action === "open-waiting") {
        setOpen("waiting", target.dataset.request);
      } else if (action === "close") {
        setOpen(null);
      } else if (action === "decide") {
        const clinician = clinicianFor("deciding on a task");
        if (!clinician) return;
        target.disabled = true;
        await post(`/api/tasks/${encodeURIComponent(target.dataset.task)}/decision`,
                   { decision: target.dataset.decision, clinician_id: clinician });
        await load();
      } else if (action === "discharge-start" || action === "discharge-cancel") {
        state.confirmDischarge = action === "discharge-start";
        render();
      } else if (action === "discharge-confirm") {
        const clinician = clinicianFor("discharging a patient");
        if (!clinician) return;
        target.disabled = true;
        await post(`/api/beds/${encodeURIComponent(target.dataset.bed)}/discharge`, { clinician_id: clinician });
        setOpen(null);   // the patient has left the bed
        await load();
      } else if (action === "assign") {
        const clinician = clinicianFor("assigning a bed");
        if (!clinician) return;
        target.disabled = true;
        const result = await post(`/api/bed-requests/${encodeURIComponent(target.dataset.request)}/assign`,
                                  { clinician_id: clinician });
        await load();
        setOpen("bed", result.reservation_id);   // show the patient in their new bed
      } else if (action === "cancel-request") {
        const clinician = clinicianFor("removing a patient from the waiting list");
        if (!clinician) return;
        target.disabled = true;
        await post(`/api/bed-requests/${encodeURIComponent(target.dataset.request)}/cancel`, { clinician_id: clinician });
        if (openId("waiting") === target.dataset.request) setOpen(null);
        await load();
      } else if (action === "stop-med-start" || action === "stop-med-cancel") {
        state.confirmStop = action === "stop-med-start" ? target.dataset.med : null;
        render();
      } else if (action === "stop-med-confirm") {
        const clinician = clinicianFor("stopping a medication");
        if (!clinician) return;
        target.disabled = true;
        await post(`/api/medications/${encodeURIComponent(target.dataset.med)}/stop`, { clinician_id: clinician });
        state.confirmStop = null;
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

  // Keyboard access for bed cards and waiting-list rows
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && state.open) setOpen(null);
    if ((event.key === "Enter" || event.key === " ") &&
        event.target.matches?.(".bed-card[data-action='open'], .waiting-row[data-action='open-waiting']")) {
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
