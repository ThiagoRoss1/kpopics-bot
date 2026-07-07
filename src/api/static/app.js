"use strict";

const KEY = "kpics_token";
let token = localStorage.getItem(KEY) || "";
const $ = (id) => document.getElementById(id);
const blobUrls = [];
let idolsCache = [];
let groupsCache = [];
const addSelected = new Set();      // add-photo idol picker
let selectOrder = [];               // combo selection: photo ids in order

/* ---------------- infra ---------------- */
function toast(msg, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.style.opacity = "1";
  t.style.borderColor = kind === "err" ? "var(--kill)" : kind === "ok" ? "var(--keep)" : "var(--line)";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.style.opacity = "0"), 2600);
}

const authHeaders = () => ({ Authorization: "Bearer " + token });

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (res.status === 401) { logout(); toast("Invalid or missing token.", "err"); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res;
}

function showGate(show) {
  $("gate").classList.toggle("hidden", !show);
  $("bar").classList.toggle("hidden", show);
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  if (!show) setView("queue");
}

function logout() {
  localStorage.removeItem(KEY); token = "";
  blobUrls.splice(0).forEach(URL.revokeObjectURL);
  $("grid").innerHTML = ""; clearSelection();
  showGate(true);
}

/* ---------------- views ---------------- */
function setView(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("bg-panel2", on);
    t.classList.toggle("text-ink", on);
    t.classList.toggle("text-muted", !on);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
  if (name === "queue") loadQueue();
  if (name === "add" || name === "idols") ensureIdols();
}

/* ---------------- queue ---------------- */
function comboLabel(combo) {
  if (!combo) return "";
  const kind = { D: "Duo", T: "Trio", Q: "Quad" }[combo[0]] || "Set";
  const n = combo.slice(1);
  return `${kind} #${n}`;
}

async function loadImage(el, id) {
  try {
    const res = await api(`/photos/${id}/image`);
    const url = URL.createObjectURL(await res.blob());
    blobUrls.push(url);
    el.style.backgroundImage = `url("${url}")`;
  } catch (e) { el.textContent = "image unavailable"; }
}

function metaLine(p) {
  const bits = [];
  if (p.source) bits.push(p.source);
  if (p.date) bits.push(p.date);
  if (p.ai_score != null) bits.push("★" + p.ai_score);
  let s = bits.join(" · ");
  if (p.source_url) s += ` <a href="${p.source_url}" target="_blank" rel="noreferrer" class="text-select/80 hover:underline">↗</a>`;
  return s;
}

function card(p) {
  const el = document.createElement("article");
  el.className = "frame relative rounded-xl overflow-hidden flex flex-col";
  el.dataset.id = p.id;
  el.dataset.idols = (p.idols || []).join(",");
  el.dataset.combo = p.combo || "";
  const tags = (p.idols || []).map((k) => `<span class="font-display text-[11px] px-1.5 py-0.5 rounded bg-black/40 border border-white/10">${k}</span>`).join("")
             || `<span class="text-[11px] text-kill">no idol?</span>`;
  el.innerHTML = `
    <div class="select-num"></div>
    <div class="absolute top-2 right-2 z-[3] flex items-center gap-1.5">
      <button class="badge combo-badge ${p.combo ? "" : "hidden"} text-[11px] font-edge px-2 py-0.5 rounded-full bg-panel/80" title="Ungroup">${comboLabel(p.combo)} ✕</button>
      <button class="sel-btn w-6 h-6 rounded-full border-2 border-white/70 bg-black/30 hover:border-select" title="Select for combo"></button>
    </div>
    <div class="thumb aspect-[3/4] bg-panel2 bg-cover bg-center relative flex items-center justify-center text-muted text-xs">
      <div class="scrim absolute inset-x-0 bottom-0 p-2.5">
        <div class="flex flex-wrap gap-1 mb-1">${tags}</div>
        <div class="font-edge text-[11px] text-muted">${metaLine(p)}</div>
      </div>
    </div>
    <div class="flex gap-1.5 p-2">
      <button class="approve flex-1 py-1.5 rounded-lg font-display font-semibold text-sm bg-keep/90 hover:bg-keep text-[#04160d]">Keep</button>
      <button class="reject px-3 py-1.5 rounded-lg font-semibold text-sm bg-kill/90 hover:bg-kill text-white">✕</button>
      <button class="urgent px-3 py-1.5 rounded-lg text-sm border ${p.urgent ? "border-select text-select" : "border-line text-muted"}" title="Urgent">⚡</button>
    </div>`;

  loadImage(el.querySelector(".thumb"), p.id);
  const [approveBtn, rejectBtn] = el.querySelectorAll(".approve, .reject");
  approveBtn.onclick = () => act(el, p.id, "approve");
  rejectBtn.onclick = () => { if (confirm("Reject this photo? The image is deleted permanently.")) act(el, p.id, "reject"); };
  el.querySelector(".urgent").onclick = (e) => toggleUrgent(p.id, e.currentTarget);
  el.querySelector(".sel-btn").onclick = () => toggleSelect(p.id);
  el.querySelector(".badge").onclick = () => ungroup(p.combo);
  return el;
}

async function act(el, id, action) {
  el.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await api(`/photos/${id}/${action}`, { method: "PATCH" });
    deselect(id);
    el.classList.add("leaving");
    setTimeout(() => { el.remove(); recount(); }, 200);
    toast(action === "approve" ? "Approved" : "Rejected", "ok");
  } catch (e) {
    el.querySelectorAll("button").forEach((b) => (b.disabled = false));
    toast(e.message, "err");
  }
}

async function toggleUrgent(id, btn) {
  const on = !btn.classList.contains("text-select");
  try {
    await api(`/photos/${id}/urgent`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urgent: on }) });
    btn.classList.toggle("text-select", on); btn.classList.toggle("border-select", on);
    btn.classList.toggle("text-muted", !on); btn.classList.toggle("border-line", !on);
  } catch (e) { toast(e.message, "err"); }
}

function recount() {
  const n = $("grid").children.length;
  $("count").textContent = n ? `(${n})` : "";
  $("empty").classList.toggle("hidden", n > 0);
}

async function loadQueue() {
  try {
    const { photos } = await (await api("/photos/pending")).json();
    blobUrls.splice(0).forEach(URL.revokeObjectURL);
    clearSelection();
    const grid = $("grid");
    grid.innerHTML = "";
    photos.forEach((p) => grid.appendChild(card(p)));
    recount();
  } catch (e) { if (e.message !== "unauthorized") toast("Could not load queue: " + e.message, "err"); }
}

/* ---------------- combo selection ---------------- */
function cardEl(id) { return $("grid").querySelector(`[data-id="${id}"]`); }

function toggleSelect(id) {
  const i = selectOrder.indexOf(id);
  if (i >= 0) selectOrder.splice(i, 1);
  else selectOrder.push(id);
  renumber();
  refreshTray();
}
function deselect(id) { const i = selectOrder.indexOf(id); if (i >= 0) { selectOrder.splice(i, 1); renumber(); refreshTray(); } }
function clearSelection() { selectOrder = []; renumber(); refreshTray(); }

function renumber() {
  $("grid").querySelectorAll(".frame").forEach((el) => {
    const pos = selectOrder.indexOf(+el.dataset.id);
    el.classList.toggle("selected", pos >= 0);
    const badge = el.querySelector(".sel-btn");
    badge.classList.toggle("bg-select", pos >= 0);
    el.querySelector(".select-num").textContent = pos >= 0 ? pos + 1 : "";
  });
}

function refreshTray() {
  const tray = $("tray");
  if (selectOrder.length === 0) { tray.classList.add("hidden-tray"); return; }
  tray.classList.remove("hidden-tray");

  const thumbs = $("tray-thumbs");
  thumbs.innerHTML = "";
  selectOrder.forEach((id, i) => {
    const src = cardEl(id)?.querySelector(".thumb")?.style.backgroundImage || "";
    const t = document.createElement("div");
    t.className = "relative w-11 h-14 rounded bg-panel2 bg-cover bg-center shrink-0";
    t.style.backgroundImage = src;
    t.innerHTML = `<span class="absolute -top-1.5 -left-1.5 w-5 h-5 rounded-full bg-select text-[#241a00] text-[11px] font-bold flex items-center justify-center">${i + 1}</span>`;
    thumbs.appendChild(t);
  });

  const idols = new Set(selectOrder.map((id) => cardEl(id)?.dataset.idols));
  const sizeName = { 2: "Duo", 3: "Trio", 4: "Quad" }[selectOrder.length];
  const sameIdol = idols.size === 1;
  const ok = selectOrder.length >= 2 && selectOrder.length <= 4 && sameIdol;
  $("tray-label").textContent = ok ? `${sizeName} · ${[...idols][0].split(",").join(" + ")}`
    : selectOrder.length > 4 ? "Max 4 photos" : !sameIdol ? "Same idol only" : "Pick 2–4";
  $("make-combo").disabled = !ok;
  $("make-combo").classList.toggle("opacity-40", !ok);
}

async function makeCombo() {
  try {
    const { combo, label } = await (await api("/photos/combo", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ photo_ids: selectOrder }),
    })).json();
    selectOrder.forEach((id) => {
      const el = cardEl(id);
      if (!el) return;
      el.dataset.combo = combo;
      const b = el.querySelector(".badge");
      b.textContent = label + " ✕"; b.classList.remove("hidden");
    });
    toast(`Grouped as ${label}`, "ok");
    clearSelection();
  } catch (e) { toast(e.message, "err"); }
}

async function ungroup(combo) {
  if (!combo) return;
  try {
    await api(`/photos/combo/${encodeURIComponent(combo)}`, { method: "DELETE" });
    $("grid").querySelectorAll(`[data-combo="${combo}"]`).forEach((el) => {
      el.dataset.combo = "";
      el.querySelector(".badge").classList.add("hidden");
    });
    toast("Ungrouped");
  } catch (e) { toast(e.message, "err"); }
}

/* ---------------- idols (shared) ---------------- */
async function ensureIdols(force) {
  if (idolsCache.length && !force) { renderIdolViews(); return; }
  try {
    const data = await (await api("/idols")).json();
    idolsCache = data.idols || []; groupsCache = data.groups || [];
    renderIdolViews();
  } catch (e) { if (e.message !== "unauthorized") toast("Could not load idols: " + e.message, "err"); }
}

function renderIdolViews() {
  const picker = $("add-idols");
  picker.innerHTML = idolsCache.length ? "" : `<span class="text-muted text-sm p-1">No idols yet — register one first.</span>`;
  idolsCache.forEach((i) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip text-[13px] px-2.5 py-1 rounded-full border border-line bg-panel" + (addSelected.has(i.key) ? " ring-2 ring-select" : "");
    chip.textContent = i.idol_names[0] || i.key;
    chip.onclick = () => { addSelected.has(i.key) ? addSelected.delete(i.key) : addSelected.add(i.key); chip.classList.toggle("ring-2"); chip.classList.toggle("ring-select"); };
    picker.appendChild(chip);
  });

  const list = $("idol-list"); list.innerHTML = "";
  const byGroup = {};
  idolsCache.forEach((i) => { (byGroup[i.group_key || "—"] ||= []).push(i); });
  Object.keys(byGroup).sort().forEach((g) => {
    const chips = byGroup[g].map((i) => `<span class="font-display text-[13px] px-2 py-0.5 rounded-full bg-panel2 border border-line ${i.kpopping_id ? "text-select" : ""}" title="${i.kpopping_id ? "auto-scrape on" : "no kpopping url"}">${i.idol_names[0] || i.key}</span>`).join(" ");
    const block = document.createElement("div");
    block.innerHTML = `<h3 class="font-display text-xs uppercase tracking-widest text-muted mb-2">${g}</h3><div class="flex flex-wrap gap-1.5">${chips}</div>`;
    list.appendChild(block);
  });

  $("ni-group").innerHTML = groupsCache.map((g) => `<option value="${g.key}">${g.key}</option>`).join("") + `<option value="__new__">+ new group…</option>`;
  toggleNewGroup();
}
function toggleNewGroup() { $("ni-newgroup").classList.toggle("hidden", $("ni-group").value !== "__new__"); }

/* ---------------- add photo ---------------- */
async function submitAdd() {
  if (!addSelected.size) return toast("Pick at least one idol.", "err");
  const url = $("add-url").value.trim(), file = $("add-file").files[0];
  if (!url && !file) return toast("Provide an image URL or a file.", "err");
  const fd = new FormData();
  addSelected.forEach((k) => fd.append("idols", k));
  if (file) fd.append("file", file); else fd.append("image_url", url);
  const date = $("add-date").value.trim(); if (date) fd.append("date", date);
  const album = $("add-album").value.trim(); if (album) fd.append("album_id", album);
  if ($("add-urgent").checked) fd.append("urgent", "1");

  const btn = $("add-submit"); btn.disabled = true;
  try {
    await api("/photos/manual", { method: "POST", body: fd });
    toast("Added to queue", "ok");
    addSelected.clear();
    ["add-url", "add-date", "add-album"].forEach((id) => ($(id).value = ""));
    $("add-file").value = ""; $("add-urgent").checked = false;
    renderIdolViews();
  } catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
}

/* ---------------- register idol ---------------- */
async function submitIdol() {
  const key = $("ni-key").value.trim().toLowerCase();
  const names = $("ni-names").value.split(",").map((s) => s.trim()).filter(Boolean);
  let groupKey = $("ni-group").value;
  const body = { key, idol_names: names, name_tags: $("ni-tags").value.trim() || null };
  if (groupKey === "__new__") {
    groupKey = $("ng-key").value.trim().toLowerCase();
    body.group_names = $("ng-names").value.split(",").map((s) => s.trim()).filter(Boolean);
    body.group_tags = $("ng-tags").value.trim() || null;
  }
  body.group_key = groupKey;
  body.kpopping_url = $("ni-kpurl").value.trim() || null;

  if (!key) return toast("Key is required.", "err");
  if (!names.length) return toast("At least one name is required.", "err");
  if (!groupKey) return toast("Group is required.", "err");

  const btn = $("ni-submit"); btn.disabled = true;
  try {
    const j = await (await api("/idols", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    if (body.kpopping_url && !j.kpopping_linked) toast(`Registered ${key}, but couldn't resolve the Kpopping URL.`, "err");
    else toast(`Registered ${key}${j.kpopping_linked ? " (auto-scrape on)" : ""}`, "ok");
    ["ni-key", "ni-names", "ni-tags", "ng-key", "ng-names", "ng-tags", "ni-kpurl"].forEach((id) => ($(id).value = ""));
    await ensureIdols(true);
  } catch (e) { toast(e.message, "err"); } finally { btn.disabled = false; }
}

/* ---------------- wire up ---------------- */
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => setView(t.dataset.view)));
$("save").onclick = () => { const v = $("token").value.trim(); if (!v) return; token = v; localStorage.setItem(KEY, v); $("token").value = ""; showGate(false); };
$("token").addEventListener("keydown", (e) => { if (e.key === "Enter") $("save").click(); });
$("refresh").onclick = () => { const a = document.querySelector(".tab.bg-panel2")?.dataset.view; a === "queue" ? loadQueue() : ensureIdols(true); };
$("logout").onclick = logout;
$("add-submit").onclick = submitAdd;
$("ni-submit").onclick = submitIdol;
$("ni-group").addEventListener("change", toggleNewGroup);
$("make-combo").onclick = makeCombo;
$("clear-sel").onclick = clearSelection;

if (token) showGate(false); else showGate(true);
