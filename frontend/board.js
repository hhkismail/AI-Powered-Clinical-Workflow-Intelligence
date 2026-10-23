// Ward board: every bed, who's in it, how sick they are, what they're receiving and
// what should happen next. Data comes from the Mock EMR API (server.py); nothing here
// is hardcoded. Rendering functions are pure (data in, HTML out) so they can be tested
// without a browser; the controller at the bottom only runs on a real page.

const API_BASE = "http://127.0.0.1:3001";
const REFRESH_MS = 5000;

const ACUITY_LABELS = { critical: "Critical", serious: "Serious", stable: "Stable" };
const STATUS_LABELS = { available: "Available", occupied: "Occupied", cleaning: "Being cleaned", maintenance: "Maintenance" };
const ROUTE_LABELS = { oral: "Oral", iv: "IV", im: "IM", subcutaneous: "SC", inhaled: "Inhaled", topical: "Topical", other: "Other" };

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

function medicationLine(m) {
  const route = ROUTE_LABELS[m.route] || "";
  const routeTag = route ? `<span class="route ${m.route === "iv" ? "route-iv" : ""}">${escapeHtml(route)}</span>` : "";
  const detail = [m.dose, m.frequency].filter(Boolean).map(escapeHtml).join(" · ");
  return `<li>${routeTag}<strong>${escapeHtml(m.drug)}</strong>${detail ? ` <span class="muted">${detail}</span>` : ""}</li>`;
}

function renderSummary(summary) {
  const beds = summary.beds || {};
  const chip = (label, value, cls) => `<div class="chip ${cls || ""}"><span>${escapeHtml(value)}</span>${escapeHtml(label)}</div>`;
  return [
    chip("available", beds.available || 0, "chip-available"),
    chip("occupied", beds.occupied || 0),
    chip("being cleaned", beds.cleaning || 0, beds.cleaning ? "chip-cleaning" : ""),
    chip("critical", summary.critical_patients || 0, summary.critical_patients ? "chip-critical" : ""),
    chip("AI suggestions to review", summary.pending_suggestions || 0, summary.pending_suggestions ? "chip-pending" : "")
  ].join("");
}

function renderBedCard(bed) {
  const status = `<span class="status-pill status-${escapeHtml(bed.status)}">${escapeHtml(STATUS_LABELS[bed.status] || bed.status)}</span>`;
  const header = `
    <div class="card-head">
      <div><div class="bed-name">${escapeHtml(bed.name)}</div>
      <div class="muted small">${escapeHtml(bed.id)} · ${escapeHtml(bed.department || "")}${bed.type === "DIAGNOSTIC" ? " · Diagnostic" : ""}</div></div>
      ${status}
    </div>`;

  const p = bed.patient;
  if (!p) {
    const action = bed.status === "cleaning"
      ? `<button class="btn-small" data-action="mark-clean" data-bed="${escapeHtml(bed.id)}">Mark clean</button>`
      : "";
    return `<article class="bed-card bed-empty">${header}${action}</article>`;
  }

  const acuity = ACUITY_LABELS[p.acuity];
  const allergies = (p.allergies || []).length
    ? `<div class="allergy">⚠ Allergies: ${p.allergies.map(escapeHtml).join(", ")}</div>` : "";
  const meds = p.medications || [];
  const tasks = p.tasks || [];
  const suggested = tasks.filter(t => t.status === "suggested").length;
  const accepted = tasks.filter(t => t.status === "accepted");

  return `
    <article class="bed-card bed-occupied acuity-${escapeHtml(p.acuity || "unknown")}" tabindex="0" role="button"
             data-action="open" data-bed="${escapeHtml(bed.id)}" aria-label="Open ${escapeHtml(p.name)}, ${escapeHtml(bed.name)}">
      ${header}
      <div class="patient-row">
        <div class="patient-name">${escapeHtml(p.name)}${p.age != null ? ` <span class="muted">${escapeHtml(p.age)}</span>` : ""}</div>
        <span class="acuity-badge">${escapeHtml(acuity || "Acuity not set")}</span>
      </div>
      ${allergies}
      <div class="section-title">Medications</div>
      ${meds.length ? `<ul class="med-list">${meds.slice(0, 4).map(medicationLine).join("")}</ul>${meds.length > 4 ? `<div class="muted small">+${meds.length - 4} more</div>` : ""}`
                    : `<div class="muted small">None active</div>`}
      <div class="section-title">Next steps</div>
      ${accepted.length ? `<ul class="task-list">${accepted.slice(0, 3).map(t => `<li>${escapeHtml(t.description)}</li>`).join("")}</ul>` : ""}
      ${suggested ? `<div class="pending">${suggested} AI suggestion${suggested === 1 ? "" : "s"} to review</div>` : ""}
      ${!accepted.length && !suggested ? `<div class="muted small">None</div>` : ""}
    </article>`;
}

function renderBoard(board) {
  return (board.wards || []).map(ward => `
    <section class="wing">
      <h2>${escapeHtml(ward.wing)}</h2>
      <div class="bed-grid">${ward.beds.map(renderBedCard).join("")}</div>
    </section>`).join("");
}

function renderTask(t) {
  const meta = t.status === "accepted"
    ? `Accepted by ${escapeHtml(t.decided_by || "unknown")}`
    : `Suggested by ${t.suggested_by === "ai" ? "AI" : "clinician"}`;
  const buttons = t.status === "suggested"
    ? `<button class="btn-small btn-accept" data-action="decide" data-decision="accept" data-task="${escapeHtml(t.id)}">Accept</button>
       <button class="btn-small btn-reject" data-action="decide" data-decision="reject" data-task="${escapeHtml(t.id)}">Reject</button>`
    : `<button class="btn-small" data-action="decide" data-decision="done" data-task="${escapeHtml(t.id)}">Mark done</button>`;
  return `
    <li class="task task-${escapeHtml(t.status)}">
      <div><span class="category">${escapeHtml(t.category)}</span> ${escapeHtml(t.description)}
      <div class="muted small">${meta}</div></div>
      <div class="task-buttons">${buttons}</div>
    </li>`;
}

function renderPanel(bed, now) {
  const p = bed.patient;
  const meds = p.medications || [];
  const tasks = p.tasks || [];
  return `
    <div class="panel-head">
      <div><h2>${escapeHtml(p.name)}</h2>
      <div class="muted">${escapeHtml(p.patient_id)}${p.age != null ? ` · ${escapeHtml(p.age)} years` : ""} · ${escapeHtml(bed.name)} (${escapeHtml(bed.id)})</div></div>
      <button class="btn-close" data-action="close" aria-label="Close">×</button>
    </div>
    <div class="acuity-line acuity-${escapeHtml(p.acuity || "unknown")}">
      <span class="acuity-badge">${escapeHtml(ACUITY_LABELS[p.acuity] || "Acuity not set")}</span>
      ${p.acuity_updated_at ? `<span class="muted small">updated ${escapeHtml(relativeTime(p.acuity_updated_at, now))}</span>` : ""}
    </div>
    ${(p.allergies || []).length ? `<div class="allergy">⚠ Allergies: ${p.allergies.map(escapeHtml).join(", ")}</div>` : ""}
    ${p.medical_history ? `<div class="section-title">History</div><p>${escapeHtml(p.medical_history)}</p>` : ""}
    <div class="section-title">Active medications</div>
    ${meds.length ? `<ul class="med-list">${meds.map(medicationLine).join("")}</ul>` : `<p class="muted">None active</p>`}
    <div class="section-title">Next steps</div>
    <p class="muted small">AI suggestions only become tasks once a clinician accepts them.</p>
    ${tasks.length ? `<ul class="task-panel-list">${tasks.map(renderTask).join("")}</ul>` : `<p class="muted">No open tasks</p>`}`;
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
  const state = { board: null, openBed: bedFromHash(), loadedAt: null };
  const $ = id => document.getElementById(id);

  function setOpenBed(bedId) {
    state.openBed = bedId;
    history.replaceState(null, "", bedId ? `#bed=${encodeURIComponent(bedId)}` : location.pathname);
    render();
    // On narrow screens the panel stacks below the board, so bring it into view
    if (bedId && window.matchMedia("(max-width: 900px)").matches) {
      $("panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }
  window.addEventListener("hashchange", () => { state.openBed = bedFromHash(); render(); });

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
    $("summary").innerHTML = renderSummary(state.board.summary || {});
    $("board").innerHTML = renderBoard(state.board);
    const bed = state.openBed && findBed(state.board, state.openBed);
    const panel = $("panel");
    if (bed && bed.patient) {
      $("panel-content").innerHTML = renderPanel(bed);
      panel.classList.remove("hidden");
    } else {
      // The patient may have moved or been discharged since the link was made
      panel.classList.add("hidden");
    }
  }

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
          showError("Enter your clinician ID at the top before deciding on a task.");
          clinicianInput.focus();
          return;
        }
        target.disabled = true;
        await post(`/api/tasks/${encodeURIComponent(target.dataset.task)}/decision`,
                   { decision: target.dataset.decision, clinician_id: clinician });
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
