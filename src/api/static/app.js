"use strict";

const KEY = "kpics_token";
let token = localStorage.getItem(KEY) || "";
const $ = (id) => document.getElementById(id);
const blobUrls = [];
let idolsCache = [];
let groupsCache = [];
const addSelected = new Set();      // add-photo idol picker
let selectOrder = [];               // combo selection: photo ids in order

/* ---------------- queue view state ---------------- */
let queueData = [];                 // raw pending photos from the server (created_at DESC)
const cardsById = new Map();        // photo id -> card element (built once so images load once)
let qMode = "order";                // "order" (pin idols on top) | "filter" (show only matches)
const orderPins = [];               // idol keys, in click order (Order mode)
const filterIdols = new Set();      // idol keys to keep (Filter mode)
let filterGroup = "";               // group key, or "" for all
let filterAlbum = "";               // album_id, or "" for all
let filterUrgent = false;           // Filter mode: urgent-only
let sortScore = false;              // global: rerank by ai_score, high -> low
let onQueue = false;                // is the queue tab the active view
let railHidden = localStorage.getItem("kpics_rail_hidden") === "1";   // user collapsed the rail

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
  onQueue = name === "queue";
  syncRail();
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

async function loadImage(frame, id) {
  const photo = frame.querySelector(".photo");
  try {
    const res = await api(`/photos/${id}/image`);
    const url = URL.createObjectURL(await res.blob());
    blobUrls.push(url);
    photo.style.backgroundImage = `url("${url}")`;
  } catch (e) {
    const msg = frame.querySelector(".ph-msg");
    if (msg) msg.textContent = "image unavailable";
  }
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
    <div class="thumb aspect-[3/4] bg-panel2 relative overflow-hidden">
      <div class="photo transform-gpu absolute inset-0 bg-cover bg-center"></div>
      <span class="ph-msg absolute inset-0 flex items-center justify-center text-muted text-xs"></span>
      <div class="scrim absolute inset-x-0 bottom-0 p-2.5 z-[1]">
        <div class="flex flex-wrap gap-1 mb-1">${tags}</div>
        <div class="font-edge text-[11px] text-muted">${metaLine(p)}</div>
      </div>
    </div>
    <div class="flex gap-1.5 p-2">
      <button class="approve flex-1 py-1.5 rounded-lg font-display font-semibold text-sm bg-keep/90 hover:bg-keep text-[#04160d]">Keep</button>
      <button class="reject px-3 py-1.5 rounded-lg font-semibold text-sm bg-kill/90 hover:bg-kill text-white">✕</button>
      <button class="urgent px-3 py-1.5 rounded-lg text-sm border ${p.urgent ? "border-select text-select" : "border-line text-muted"}" title="Urgent">⚡</button>
    </div>`;

  loadImage(el, p.id);
  const [approveBtn, rejectBtn] = el.querySelectorAll(".approve, .reject");
  approveBtn.onclick = () => act(el, p.id, "approve");
  rejectBtn.onclick = () => act(el, p.id, "reject");
  el.querySelector(".urgent").onclick = (e) => toggleUrgent(p.id, e.currentTarget);
  el.querySelector(".sel-btn").onclick = () => toggleSelect(p.id);
  el.querySelector(".thumb").onclick = (e) => { if (e.target.closest("a")) return; toggleSelect(p.id); };
  el.querySelector(".badge").onclick = () => ungroup(p.combo);
  return el;
}

// Remove one card from the grid + queue data (shared by single act() and batchAct()).
function dropCard(id) {
  const el = cardsById.get(id);
  if (el) { el.classList.add("leaving"); setTimeout(() => { el.remove(); cardsById.delete(id); }, 200); }
  queueData = queueData.filter((p) => p.id !== id);
}

async function act(el, id, action) {
  el.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await api(`/photos/${id}/${action}`, { method: "PATCH" });
    deselect(id);
    dropCard(id);
    setTimeout(() => { refreshFacets(); renderRailIdols(); applyQueueView(); }, 200);
    toast(action === "approve" ? "Approved" : "Rejected", "ok");
  } catch (e) {
    el.querySelectorAll("button").forEach((b) => (b.disabled = false));
    toast(e.message, "err");
  }
}

// Approve or reject every currently-selected photo. Batch reject (>1) confirms once;
// single actions are instant. Combo selection/state is untouched.
async function batchAct(action) {
  const ids = selectOrder.slice();
  if (!ids.length) return;
  if (action === "reject" && ids.length > 1 &&
      !confirm(`Reject ${ids.length} photos? The images are deleted permanently.`)) return;
  [$("batch-approve"), $("batch-reject"), $("make-combo"), $("clear-sel")].forEach((b) => (b.disabled = true));
  let ok = 0;
  for (const id of ids) {
    try {
      await api(`/photos/${id}/${action}`, { method: "PATCH" });
      dropCard(id);
      ok++;
    } catch (e) { toast(e.message, "err"); }
  }
  clearSelection();
  setTimeout(() => { refreshFacets(); renderRailIdols(); applyQueueView(); }, 200);
  toast(`${action === "approve" ? "Approved" : "Rejected"} ${ok}`, "ok");
}

async function toggleUrgent(id, btn) {
  const on = !btn.classList.contains("text-select");
  try {
    await api(`/photos/${id}/urgent`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ urgent: on }) });
    btn.classList.toggle("text-select", on); btn.classList.toggle("border-select", on);
    btn.classList.toggle("text-muted", !on); btn.classList.toggle("border-line", !on);
  } catch (e) { toast(e.message, "err"); }
}

async function loadQueue() {
  try {
    await ensureIdols();               // idol names + group_key for the rail
    const { photos } = await (await api("/photos/pending")).json();
    blobUrls.splice(0).forEach(URL.revokeObjectURL);
    clearSelection();
    cardsById.clear();
    queueData = photos;
    const grid = $("grid");
    grid.innerHTML = "";
    photos.forEach((p) => { const el = card(p); cardsById.set(p.id, el); grid.appendChild(el); });
    refreshFacets(); renderRailIdols(); updateHint(); applyQueueView();
  } catch (e) { if (e.message !== "unauthorized") toast("Could not load queue: " + e.message, "err"); }
}

/* ---------------- queue: order / filter / sort ---------------- */
function groupOf(key) { const i = idolsCache.find((x) => x.key === key); return i ? i.group_key : ""; }
function scoreVal(p) { return p.ai_score == null ? -1 : p.ai_score; }

function passesFilters(p) {
  if (qMode !== "filter") return true;
  const idols = p.idols || [];
  if (filterIdols.size && !idols.some((k) => filterIdols.has(k))) return false;
  if (filterGroup && !idols.some((k) => groupOf(k) === filterGroup)) return false;
  if (filterAlbum && p.album_id !== filterAlbum) return false;
  if (filterUrgent && !p.urgent) return false;
  return true;
}

function groupByIdol(list) {
  // Contiguous per-idol blocks; within a block the server's created_at DESC order is kept (newest
  // first). Block order = pinned idols first (Order mode), then idols by first appearance.
  const buckets = new Map(), appearance = [];
  list.forEach((p) => {
    const k = (p.idols && p.idols[0]) || "—";
    if (!buckets.has(k)) { buckets.set(k, []); appearance.push(k); }
    buckets.get(k).push(p);
  });
  const seen = new Set(), keys = [];
  (qMode === "order" ? orderPins : []).forEach((k) => { if (buckets.has(k) && !seen.has(k)) { keys.push(k); seen.add(k); } });
  appearance.forEach((k) => { if (!seen.has(k)) { keys.push(k); seen.add(k); } });
  const out = [];
  keys.forEach((k) => out.push(...buckets.get(k)));
  return out;
}

function applyQueueView() {
  const grid = $("grid");
  let list = queueData.filter(passesFilters);
  if (sortScore) list = list.slice().sort((a, b) => scoreVal(b) - scoreVal(a));  // grouping yields to score
  else list = groupByIdol(list);

  const visible = new Set(list.map((p) => p.id));
  cardsById.forEach((el, id) => el.classList.toggle("qhide", !visible.has(id)));
  list.forEach((p) => { const el = cardsById.get(p.id); if (el) grid.appendChild(el); });

  const n = list.length;
  $("count").textContent = n ? `(${n})` : "";
  const empty = $("empty");
  if (n === 0) { empty.textContent = queueData.length ? "No photos match these filters." : "No photos waiting for approval."; }
  empty.classList.toggle("hidden", n > 0);
  syncRail();
}

function syncRail() {
  // The rail shows only on the queue tab, when there's something to curate, and when not collapsed.
  // Its toggle button lives in the always-visible top row so a hidden rail can be brought back.
  const show = onQueue && queueData.length > 0 && !railHidden;
  $("qrail").classList.toggle("hidden", !show);
  $("rail-toggle").classList.toggle("hidden", !(onQueue && queueData.length > 0));
  toggleActive($("rail-toggle"), !railHidden);
}

function renderRailIdols() {
  const wrap = $("qidols");
  wrap.innerHTML = "";
  const present = [...new Set(queueData.flatMap((p) => p.idols || []))];
  present.forEach((key) => {
    const idol = idolsCache.find((i) => i.key === key);
    const label = idol ? (idol.idol_names[0] || key) : key;
    const pos = qMode === "order" ? orderPins.indexOf(key) : -1;
    const on = qMode === "order" ? pos >= 0 : filterIdols.has(key);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "qchip shrink-0 font-display text-[13px] px-2.5 py-1 rounded-full border " +
      (on ? "border-select text-ink bg-select/10" : "border-line text-muted bg-panel");
    chip.innerHTML = (pos >= 0
      ? `<span class="inline-flex align-middle w-4 h-4 mr-1 rounded-full bg-select text-[#241a00] text-[10px] font-bold items-center justify-center">${pos + 1}</span>`
      : "") + label;
    chip.onclick = () => toggleRailIdol(key);
    wrap.appendChild(chip);
  });
}

function toggleRailIdol(key) {
  if (qMode === "order") {
    const i = orderPins.indexOf(key);
    if (i >= 0) orderPins.splice(i, 1); else orderPins.push(key);
  } else {
    filterIdols.has(key) ? filterIdols.delete(key) : filterIdols.add(key);
  }
  renderRailIdols(); applyQueueView();
}

function refreshFacets() {
  const groupKeys = [...new Set(queueData.flatMap((p) => (p.idols || []).map(groupOf)).filter(Boolean))].sort();
  const gsel = $("qgroup");
  gsel.innerHTML = `<option value="">All groups</option>` + groupKeys.map((g) => `<option value="${g}">${g}</option>`).join("");
  if (!groupKeys.includes(filterGroup)) filterGroup = "";
  gsel.value = filterGroup;

  const albums = [...new Set(queueData.map((p) => p.album_id).filter(Boolean))].sort();
  const asel = $("qalbum");
  asel.innerHTML = `<option value="">All albums</option>` + albums.map((a) => `<option value="${a}">${a}</option>`).join("");
  if (!albums.includes(filterAlbum)) filterAlbum = "";
  asel.value = filterAlbum;
}

function updateHint() {
  $("qhint").textContent = qMode === "order"
    ? "Order — click idols to pin them to the top in that order; everything else stays grouped below."
    : "Filter — click idols, or pick a group / album / ⚡ to show only matching photos.";
}

function toggleActive(btn, on) {
  btn.classList.toggle("border-select", on);
  btn.classList.toggle("text-select", on);
  btn.classList.toggle("text-muted", !on);
}

function setMode(m) {
  qMode = m;
  const order = m === "order";
  $("mode-order").classList.toggle("bg-select", order);
  $("mode-order").classList.toggle("text-[#241a00]", order);
  $("mode-order").classList.toggle("text-muted", !order);
  $("mode-filter").classList.toggle("bg-select", !order);
  $("mode-filter").classList.toggle("text-[#241a00]", !order);
  $("mode-filter").classList.toggle("text-muted", order);
  document.querySelectorAll(".qfacet").forEach((e) => e.classList.toggle("hidden", order));
  updateHint(); renderRailIdols(); applyQueueView();
}

function resetQueueControls() {
  orderPins.length = 0;
  filterIdols.clear();
  filterGroup = ""; filterAlbum = ""; filterUrgent = false; sortScore = false;
  $("qgroup").value = ""; $("qalbum").value = "";
  toggleActive($("qurgent"), false); toggleActive($("qscore"), false);
  renderRailIdols(); applyQueueView();
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
    const src = cardEl(id)?.querySelector(".photo")?.style.backgroundImage || "";
    const t = document.createElement("div");
    t.className = "relative w-11 h-14 rounded bg-panel2 bg-cover bg-center shrink-0";
    t.style.backgroundImage = src;
    t.innerHTML = `<span class="absolute -top-1.5 -left-1.5 w-5 h-5 rounded-full bg-select text-[#241a00] text-[11px] font-bold flex items-center justify-center">${i + 1}</span>`;
    thumbs.appendChild(t);
  });

  const n = selectOrder.length;
  const ba = $("batch-approve"), br = $("batch-reject");
  ba.textContent = `Approve ${n}`; br.textContent = `Reject ${n}`;
  ba.disabled = br.disabled = false;

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
$("batch-approve").onclick = () => batchAct("approve");
$("batch-reject").onclick = () => batchAct("reject");

/* queue rail */
$("mode-order").onclick = () => setMode("order");
$("mode-filter").onclick = () => setMode("filter");
$("qgroup").onchange = (e) => { filterGroup = e.target.value; applyQueueView(); };
$("qalbum").onchange = (e) => { filterAlbum = e.target.value; applyQueueView(); };
$("qurgent").onclick = () => { filterUrgent = !filterUrgent; toggleActive($("qurgent"), filterUrgent); applyQueueView(); };
$("qscore").onclick = () => { sortScore = !sortScore; toggleActive($("qscore"), sortScore); applyQueueView(); };
$("qreset").onclick = resetQueueControls;
$("rail-toggle").onclick = () => {
  railHidden = !railHidden;
  localStorage.setItem("kpics_rail_hidden", railHidden ? "1" : "0");
  syncRail();
};
setMode("order");

if (token) showGate(false); else showGate(true);
