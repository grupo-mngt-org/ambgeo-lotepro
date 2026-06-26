// Lote Pro — frontend (Leaflet). Sem build step; vanilla JS.
const $ = (id) => document.getElementById(id);
let token = null;
let resultLayer = null, boundaryLayer = null;
let lastProjectId = null;       // projeto da análise corrente (exports / reanálise)
let lastFeatures = [];          // candidatos da última análise (para filtrar cenários)
let picked = null;              // sugestão escolhida {lat, lon, osm_type, osm_id}
let profilesList = [];          // perfis de finalidade vindos da API
let lotsInfo = {};              // fichas dos lotes {id: {matricula, status, layout...}}
let currentLot = null;          // lote com ficha aberta
let mode = "city";              // "city" (cidade inteira) | "radius" (endereço+raio)
let polling = false;

// Cor do lote pelo score de viabilidade (verde = melhor)
function scoreColor(score) {
  if (score == null) return null;
  if (score >= 80) return "#1e8e3e";
  if (score >= 65) return "#7ac943";
  if (score >= 50) return "#f1c40f";
  if (score >= 35) return "#e67e22";
  return "#e74c3c";
}

// Mapa com basemap de satélite gratuito (Esri World Imagery, sem chave).
// preferCanvas: milhares de polígonos (cidade inteira) sem travar o DOM.
const map = L.map("map", { preferCanvas: true, maxZoom: 21 }).setView([-15.78, -47.93], 12);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  {
    // O Esri World Imagery só tem imagem real até ~z19 na maior parte do Brasil;
    // pedir z20+ devolve o tile cinza "Map data not yet available". maxNativeZoom
    // faz o Leaflet AMPLIAR o último tile real em vez de pedir um que não existe.
    maxNativeZoom: 19, maxZoom: 21, attribution: "Tiles &copy; Esri",
  }
).addTo(map);

function msg(text, kind = "") { const el = $("msg"); el.textContent = text; el.className = kind; }

async function api(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, token ? { Authorization: "Bearer " + token } : {});
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res;
}

// ----------------------------- Login --------------------------------------
async function applyLogin(data) {
  token = data.token;
  $("login").classList.add("hidden");
  $("work").classList.remove("hidden");
  $("who").textContent = "👤 " + data.user;
  await loadProfiles();
  msg("Escolha a cidade e clique em Analisar.", "ok");
}

$("btn-login").onclick = async () => {
  try {
    const res = await api("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("user").value, password: $("pass").value }),
    });
    await applyLogin(await res.json());
  } catch (e) { msg("Login falhou: " + e.message, "err"); }
};

// Login Google (Identity Services). Só inicializa se o backend devolver um
// client_id (GOOGLE_CLIENT_ID configurado); senão segue só o usuário/senha.
async function onGoogleCredential(resp) {
  try {
    const res = await api("/api/auth/google", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: resp.credential }),
    });
    await applyLogin(await res.json());
  } catch (e) { msg("Login Google falhou: " + e.message, "err"); }
}

async function initGoogleLogin() {
  try {
    const cfg = await (await fetch("/api/auth/config")).json();
    if (!cfg.google_client_id || !window.google?.accounts?.id) return;
    google.accounts.id.initialize({
      client_id: cfg.google_client_id, callback: onGoogleCredential,
    });
    google.accounts.id.renderButton($("g-signin"), { theme: "outline", size: "large", width: 240 });
    $("g-sep").classList.remove("hidden");
  } catch { /* sem login Google — segue usuário/senha */ }
}

// O script GSI carrega async; tenta agora e também no load da janela.
initGoogleLogin();
window.addEventListener("load", initGoogleLogin);

// --------------------------- Modo (cidade | raio) --------------------------
function setMode(m) {
  mode = m;
  $("tab-city").classList.toggle("active", m === "city");
  $("tab-radius").classList.toggle("active", m === "radius");
  $("radius-wrap").classList.toggle("hidden", m === "city");
  $("search-title").textContent = m === "city"
    ? "Qual cidade você quer prospectar?" : "Onde você quer prospectar?";
  $("search").placeholder = m === "city"
    ? "Digite o nome da cidade…" : "Digite um endereço ou bairro…";
  $("btn-analyze").textContent = m === "city"
    ? "Analisar cidade inteira" : "Analisar área";
  picked = null;
  hideSuggest();
}
$("tab-city").onclick = () => setMode("city");
$("tab-radius").onclick = () => setMode("radius");

// --------------------- Perfis de finalidade --------------------------------
async function loadProfiles() {
  try {
    profilesList = await (await api("/api/profiles")).json();
  } catch { profilesList = []; }
  const sel = $("profile");
  sel.innerHTML = profilesList.map((p) => `<option value="${p.key}">${p.label}</option>`).join("");
  sel.onchange = applyProfileDefaults;
  applyProfileDefaults();
}

function applyProfileDefaults() {
  const p = profilesList.find((x) => x.key === $("profile").value);
  if (!p) return;
  $("profile-desc").textContent = p.desc;
  $("target-min").value = p.target_area_m2[0];
  $("target-max").value = p.target_area_m2[1];
}

// -------------------------- Autocomplete -----------------------------------
let acTimer = null;
$("search").addEventListener("input", () => {
  picked = null;
  const q = $("search").value.trim();
  clearTimeout(acTimer);
  if (q.length < 3) return hideSuggest();
  acTimer = setTimeout(async () => {
    try {
      const cities = mode === "city" ? 1 : 0;
      const list = await (await api(
        `/api/geocode/suggest?q=${encodeURIComponent(q)}&cities=${cities}`)).json();
      renderSuggest(list);
    } catch { hideSuggest(); }
  }, 350);
});

function renderSuggest(list) {
  const ul = $("suggest");
  ul.innerHTML = "";
  if (!list.length) return hideSuggest();
  list.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s.label;
    li.onclick = () => {
      $("search").value = s.label;
      picked = s;
      hideSuggest();
      map.setView([s.lat, s.lon], mode === "city" ? 12 : 16);
    };
    ul.appendChild(li);
  });
  ul.classList.remove("hidden");
}
function hideSuggest() { $("suggest").classList.add("hidden"); }
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap")) hideSuggest();
});
$("search").addEventListener("blur", () => setTimeout(hideSuggest, 150));
$("search").addEventListener("keydown", (e) => { if (e.key === "Escape") hideSuggest(); });

// -------- Smart pairing: DW/GEE provider ↔ fonte de edificações --------------
$("adv-provider").addEventListener("change", () => {
  const p = $("adv-provider").value;
  const needsGee = p === "dynamic_world" || p === "gee";
  $("gee-tip").classList.toggle("hidden", !needsGee);
  if (p === "dynamic_world" && $("adv-buildings-src").value === "auto") {
    $("adv-buildings-src").value = "google";
  }
  if (p === "footprint" && $("adv-buildings-src").value === "google") {
    $("adv-buildings-src").value = "auto";
  }
});

// ----------------------- Análise (job com progresso) ------------------------
function analyzeBody() {
  return {
    mode,
    query: $("search").value.trim(),
    lat: picked ? picked.lat : null,
    lon: picked ? picked.lon : null,
    osm_type: picked ? picked.osm_type : null,
    osm_id: picked ? picked.osm_id : null,
    radius_m: parseFloat($("adv-radius").value),
    buildings_source: $("adv-buildings-src").value,
    profile: $("profile").value,
    target_min_m2: parseFloat($("target-min").value) || null,
    target_max_m2: parseFloat($("target-max").value) || null,
    enrich: true,
    provider: $("adv-provider").value,
    min_area_m2: parseFloat($("adv-min-area").value),
    max_occupation_ratio: parseFloat($("adv-max-occ").value) / 100,
    min_width_m: parseFloat($("adv-min-width").value),
    building_buffer_m: parseFloat($("adv-bbuffer").value),
    max_area_m2: (parseFloat($("adv-max-area-ha").value) || 200) * 10000,
  };
}

function showProgress(on) {
  $("progress").classList.toggle("hidden", !on);
  $("btn-analyze").disabled = on;
  if (!on) { $("pg-fill").style.width = "0%"; $("pg-detail").textContent = ""; }
}

$("btn-analyze").onclick = async () => {
  hideSuggest();
  const q = $("search").value.trim();
  if (!q && !picked) return msg("Digite a cidade ou um endereço.", "err");
  msg("");
  showProgress(true);
  $("pg-stage").textContent = "Enviando análise…";
  $("pg-pct").textContent = "";
  try {
    const data = await (await api("/api/analyze/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(analyzeBody()),
    })).json();
    pollJob(data.job_id);
  } catch (e) { showProgress(false); msg("Erro: " + e.message, "err"); }
};

async function pollJob(jobId) {
  if (polling) return;
  polling = true;
  const tick = async () => {
    let j;
    try {
      j = await (await api(`/api/jobs/${jobId}`)).json();
    } catch (e) {
      polling = false; showProgress(false);
      return msg("Erro ao consultar o progresso: " + e.message, "err");
    }
    if (j.status === "running") {
      $("pg-fill").style.width = (j.progress || 0) + "%";
      $("pg-stage").textContent = j.stage || "Processando…";
      $("pg-pct").textContent = (j.progress || 0).toFixed(0) + "%";
      $("pg-detail").textContent = j.detail || "";
      return setTimeout(tick, 1200);
    }
    polling = false;
    showProgress(false);
    if (j.status === "error") return msg("Erro: " + j.error, "err");
    const data = j.result;
    lastProjectId = data.project_id;
    onAnalysis(data);
    const extra = data.mode === "city"
      ? `${data.area_km2} km² · ${(data.blocks || 0).toLocaleString("pt-BR")} quadras · `
      : "";
    msg(`Análise de "${data.query}" — ${data.count} lotes candidatos `
      + `(${extra}${(data.buildings || 0).toLocaleString("pt-BR")} edificações, `
      + `${data.buildings_source}).`, "ok");
  };
  tick();
}

// Reanálise rápida com os dados já baixados (ex.: após enviar zoneamento).
$("btn-reanalyze").onclick = async () => {
  if (!lastProjectId) return msg("Faça uma análise primeiro.", "err");
  msg("Reanalisando…");
  try {
    const data = await (await api(`/api/projects/${lastProjectId}/detect`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: $("adv-provider").value, mode: "gaps",
        min_area_m2: parseFloat($("adv-min-area").value),
        max_occupation_ratio: parseFloat($("adv-max-occ").value) / 100,
        min_width_m: parseFloat($("adv-min-width").value),
        building_buffer_m: parseFloat($("adv-bbuffer").value),
        max_area_m2: (parseFloat($("adv-max-area-ha").value) || 200) * 10000,
        profile: $("profile").value,
        target_min_m2: parseFloat($("target-min").value) || null,
        target_max_m2: parseFloat($("target-max").value) || null,
        enrich: true,
      }),
    })).json();
    onAnalysis(data);
    msg(`Reanálise concluída — ${data.count} lotes.`, "ok");
  } catch (e) { msg("Erro: " + e.message, "err"); }
};

// --------------------- Resultado + relatório -------------------------------
function onAnalysis(data) {
  lastFeatures = (data.results && data.results.features) || [];
  lotsInfo = data.lots_info || {};
  closeLayout();
  // Reseta o Motor de Bolhas para a nova análise.
  $("bolha-panel").classList.add("hidden"); bolhaLot = null;
  colorMode = "score"; bolhaLineByLot = {};
  $("bolhas-summary").classList.add("hidden");
  $("bolhas-map-bar").classList.toggle("hidden", !lastFeatures.length);

  if (boundaryLayer) { map.removeLayer(boundaryLayer); boundaryLayer = null; }
  if (data.boundary) {
    boundaryLayer = L.geoJSON(data.boundary, {
      style: { color: "#38bdf8", weight: 2.5, dashArray: "6 4", fill: false },
    }).addTo(map);
  }

  drawFeatures(lastFeatures);
  if (boundaryLayer && boundaryLayer.getBounds().isValid()) {
    map.fitBounds(boundaryLayer.getBounds(), { padding: [20, 20] });
  } else if (data.center) {
    map.setView([data.center.lat, data.center.lon], 15);
  }
  renderReport(data.report, data);
  renderRanking(lastFeatures);
}

const FLAG_LABELS = {
  encravado: "⚠️ Encravado (sem frente p/ via)",
  ingreme: "⚠️ Declividade acima do limite do perfil",
  sem_dado_relevo: "ℹ️ Relevo sem dado (consultado só nos maiores lotes)",
};

function popupHtml(p) {
  const info = lotsInfo[String(p.id)] || {};
  let html = `<div class="pp-head"><b>Lote ${p.id}</b>`;
  if (p.score != null) {
    html += ` <span class="pp-grade" style="background:${scoreColor(p.score)}">`
      + `${p.grade} · ${p.score.toFixed(0)}</span>`;
  }
  html += `</div>`;
  html += `Área: <b>${p.area_m2.toLocaleString("pt-BR")} m²</b>`
    + ` · Ocupação: ${(p.occupation * 100).toFixed(1)}%<br>`;
  if (p.slope_pct != null)
    html += `Declividade: <b>${p.slope_pct}%</b> (desnível ${p.elev_range_m ?? "?"} m)<br>`;
  if (p.frontage_m != null)
    html += `Testada: <b>${p.frontage_m.toLocaleString("pt-BR")} m</b><br>`;
  html += `Zoneamento: ${p.zoning}<br>`;

  (p.flags || "").split(";").filter(Boolean).forEach((f) => {
    html += `<div class="pp-flag">${FLAG_LABELS[f] || f}</div>`;
  });

  // Breakdown do score (barras por critério)
  if (p.score_breakdown) {
    try {
      const bd = JSON.parse(p.score_breakdown);
      html += `<div class="pp-bd">`;
      for (const k of Object.keys(bd)) {
        const c = bd[k];
        const pct = c.score == null ? 0 : Math.round(c.score * 100);
        const txt = c.score == null ? "s/ dado" : `${pct}`;
        html += `<div class="pp-bd-row"><span>${c.label}</span>`
          + `<span class="pp-bar"><i style="width:${pct}%"></i></span><em>${txt}</em></div>`;
      }
      html += `</div>`;
    } catch {}
  }

  if (info.matricula) html += `Matrícula: <b>${info.matricula}</b><br>`;
  if (info.status && info.status !== "novo") html += `Status: <b>${info.status}</b><br>`;
  if (info.layout && info.layout.stats)
    html += `Estudo salvo: <b>${info.layout.stats.units} casas</b><br>`;
  if (info.bolha && info.bolha.bolha_nome)
    html += `🫧 Bolha: <b>${info.bolha.bolha_nome}</b> (${info.bolha.score_aplicabilidade}/100)<br>`;

  html += `<div class="pp-links">`
    + `<a href="${p.street_view}" target="_blank">📍 Street View</a>`
    + ` · <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}" target="_blank">🗺️ Maps</a>`
    + ` · <a href="https://www.registrodeimoveis.org.br" target="_blank">🏛️ ONR (matrícula)</a></div>`;
  html += `<button class="pp-bolha" onclick="openBolha(${p.id})">🫧 Analisar bolha (IA)</button>`;
  html += `<button class="pp-ficha" onclick="openFicha(${p.id})">📋 Ficha do lote</button>`;
  html += `<button class="pp-layout" onclick="openLayout(${p.id})">🏘️ Estudo de implantação</button>`;
  return html;
}

function drawFeatures(features) {
  if (resultLayer) map.removeLayer(resultLayer);
  resultLayer = L.geoJSON({ type: "FeatureCollection", features }, {
    style: (f) => ({
      color: "#fff", weight: 1,
      fillColor: featureFill(f),
      fillOpacity: 0.55,
    }),
    onEachFeature: (f, layer) => {
      layer.bindPopup(() => popupHtml(f.properties), { maxWidth: 320 });
      layer._lotId = f.properties.id;
    },
  }).addTo(map);
  if (!boundaryLayer && resultLayer.getBounds().isValid()) {
    map.fitBounds(resultLayer.getBounds(), { padding: [25, 25] });
  }
}

// ------------------------- Ranking (top lotes) ------------------------------
function renderRanking(features) {
  const box = $("ranking");
  const scored = features.filter((f) => f.properties.score != null)
    .sort((a, b) => b.properties.score - a.properties.score).slice(0, 10);
  if (!scored.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.innerHTML = `<h3>🏆 Melhores lotes</h3>` + scored.map((f) => {
    const p = f.properties;
    const info = lotsInfo[String(p.id)] || {};
    const st = info.status && info.status !== "novo" ? ` · <em>${info.status}</em>` : "";
    return `<button class="rank-item" data-lot="${p.id}">
      <span class="rank-grade" style="background:${scoreColor(p.score)}">${p.grade}</span>
      <span class="rank-body"><b>Lote ${p.id}</b> · ${p.area_m2.toLocaleString("pt-BR")} m²${st}<br>
      <small>score ${p.score.toFixed(0)}${p.slope_pct != null ? ` · decliv. ${p.slope_pct}%` : ""}${p.frontage_m != null ? ` · testada ${Math.round(p.frontage_m)} m` : ""}</small></span>
    </button>`;
  }).join("");
  box.classList.remove("hidden");

  box.querySelectorAll(".rank-item").forEach((btn) => {
    btn.onclick = () => focusLot(parseInt(btn.dataset.lot));
  });
}

function focusLot(lotId) {
  if (!resultLayer) return;
  resultLayer.eachLayer((layer) => {
    if (layer._lotId === lotId) {
      map.fitBounds(layer.getBounds(), { padding: [60, 60] });
      layer.openPopup();
    }
  });
}

// ----------- Estudo de implantação (estilo TestFit, tempo real) -------------
const LAY_PARAM_IDS = [
  "lot_width_m", "lot_depth_m", "house_width_m", "house_depth_m",
  "front_setback_m", "side_setback_m", "back_setback_m",
  "road_width_m", "perimeter_margin_m",
];
let layoutLayer = null, layoutLot = null, layoutTimer = null, lastLayout = null;
let layoutBusy = false, layoutQueued = false;

function layParams() {
  const p = {};
  LAY_PARAM_IDS.forEach((k) => { p[k] = parseFloat($("lay-" + k).value); });
  p.angle_deg = $("lay-auto-angle").checked ? null : parseFloat($("lay-angle_deg").value);
  return p;
}

function setLayParams(p) {
  if (!p) return;
  LAY_PARAM_IDS.forEach((k) => {
    if (p[k] != null) { $("lay-" + k).value = p[k]; updateVal(k); }
  });
  const manual = p.angle_deg != null;
  $("lay-auto-angle").checked = !manual;
  $("lay-angle_deg").disabled = !manual;
  if (manual) { $("lay-angle_deg").value = p.angle_deg; updateVal("angle_deg", "°"); }
}

function updateVal(k, suffix = " m") {
  const el = $("v-" + k);
  if (el) el.textContent = $("lay-" + k).value + suffix;
}

window.openLayout = function (lotId) {
  const f = lastFeatures.find((x) => x.properties.id === lotId);
  if (!f) return;
  layoutLot = lotId;
  $("lay-lot").textContent = "#" + lotId
    + ` · ${f.properties.area_m2.toLocaleString("pt-BR")} m²`;
  $("lay-msg").textContent = "";
  const saved = (lotsInfo[String(lotId)] || {}).layout;
  if (saved && saved.params) setLayParams(saved.params);
  $("layout-panel").classList.remove("hidden");
  map.closePopup();
  focusLot(lotId);
  requestLayout();
  $("layout-panel").scrollIntoView({ behavior: "smooth" });
};

async function requestLayout() {
  if (layoutLot == null) return;
  if (layoutBusy) { layoutQueued = true; return; }
  const f = lastFeatures.find((x) => x.properties.id === layoutLot);
  if (!f) return;
  layoutBusy = true;
  try {
    const data = await (await api("/api/layout/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geometry: f.geometry, params: layParams() }),
    })).json();
    lastLayout = data;
    drawLayout(data);
    renderLayoutStats(data.stats);
    if ($("lay-auto-angle").checked) {
      $("lay-angle_deg").value = data.angle_used;
      updateVal("angle_deg", "°");
    }
  } catch (e) {
    $("lay-msg").textContent = "Erro: " + e.message;
  } finally {
    layoutBusy = false;
    if (layoutQueued) { layoutQueued = false; requestLayout(); }
  }
}

const LAYOUT_STYLES = {
  road: { color: "#475569", weight: 0.5, fillColor: "#64748b", fillOpacity: 0.9 },
  lot: { color: "#fff", weight: 1, fill: false, dashArray: "3 3" },
  house: { color: "#7c2d12", weight: 1, fillColor: "#f59e0b", fillOpacity: 0.9 },
  green: { color: "#16a34a", weight: 0.5, fillColor: "#22c55e", fillOpacity: 0.3 },
};

function drawLayout(data) {
  if (layoutLayer) map.removeLayer(layoutLayer);
  layoutLayer = L.geoJSON(data.features, {
    // interactive:false → o desenho da implantação NÃO captura cliques; assim dá
    // para clicar em outro lote por baixo e abrir um novo estudo.
    interactive: false,
    style: (f) => LAYOUT_STYLES[f.properties.kind] || {},
  }).addTo(map);
}

function renderLayoutStats(s) {
  if (!s) return;
  $("lay-stats").innerHTML = `
    <div class="ls-big">${s.units} <small>casas</small></div>
    <div class="ls-grid">
      <span>${s.density_units_ha} casas/ha</span>
      <span>lote médio ${s.avg_lot_m2.toLocaleString("pt-BR")} m²</span>
      <span>casa ${s.house_area_m2.toLocaleString("pt-BR")} m²</span>
      <span>aproveitamento ${s.efficiency_pct}%</span>
      <span>vias ${(s.roads_area_m2 / 10000).toFixed(2)} ha</span>
      <span>verde ${(s.green_area_m2 / 10000).toFixed(2)} ha</span>
    </div>
    ${s.truncated ? '<div class="pp-flag">Estudo truncado (terreno muito grande p/ o lote escolhido)</div>' : ""}`;
}

LAY_PARAM_IDS.forEach((k) => {
  $("lay-" + k).addEventListener("input", () => {
    updateVal(k);
    clearTimeout(layoutTimer);
    layoutTimer = setTimeout(requestLayout, 180);
  });
});
$("lay-angle_deg").addEventListener("input", () => {
  updateVal("angle_deg", "°");
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(requestLayout, 180);
});
$("lay-auto-angle").addEventListener("change", () => {
  $("lay-angle_deg").disabled = $("lay-auto-angle").checked;
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(requestLayout, 100);
});

$("lay-save").onclick = async () => {
  if (layoutLot == null || !lastProjectId || !lastLayout) return;
  try {
    const saved = await (await api(`/api/projects/${lastProjectId}/lots/${layoutLot}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: { params: layParams(), stats: lastLayout.stats } }),
    })).json();
    lotsInfo[String(layoutLot)] = saved;
    $("lay-msg").textContent = `✔ Estudo salvo (${lastLayout.stats.units} casas).`;
  } catch (e) { $("lay-msg").textContent = "Erro: " + e.message; }
};

function closeLayout() {
  $("layout-panel").classList.add("hidden");
  if (layoutLayer) { map.removeLayer(layoutLayer); layoutLayer = null; }
  layoutLot = null;
  lastLayout = null;
}
$("lay-close").onclick = closeLayout;

// ------------------- Ficha do lote (CRM de prospecção) ----------------------
let fichaUF = "GO"; // UF do lote aberto (define o tribunal no DataJud)

window.openFicha = function (lotId) {
  currentLot = lotId;
  const info = lotsInfo[String(lotId)] || {};
  $("ficha-lot").textContent = "#" + lotId;
  $("fi-matricula").value = info.matricula || "";
  $("fi-inscricao").value = info.inscricao || "";
  $("fi-proprietario").value = info.proprietario || "";
  $("fi-contato").value = info.contato || "";
  $("fi-status").value = info.status || "novo";
  $("fi-notas").value = info.notas || "";
  $("fi-msg").textContent = "";
  $("fi-cnpj-out").innerHTML = "";
  $("fi-proc-out").innerHTML = "";
  renderProcLinks();

  const f = lastFeatures.find((x) => x.properties.id === lotId);
  if (f) { loadRegistry(f.properties); loadCar(f.properties); }
  $("ficha").classList.remove("hidden");
  $("ficha").scrollIntoView({ behavior: "smooth" });
};

// Endereço oficial do lote (Nominatim) + links de consulta que funcionam.
async function loadRegistry(p) {
  const box = $("fi-registry");
  box.innerHTML = "Consultando endereço oficial…";
  try {
    const r = await (await api(`/api/registry/point?lat=${p.lat}&lon=${p.lon}`)).json();
    const e = r.endereco || {};
    if (e.uf) fichaUF = e.uf;
    const lines = [
      e.logradouro, e.bairro,
      [e.cidade, e.uf].filter(Boolean).join(" – "),
      e.cep ? "CEP " + e.cep : null,
    ].filter(Boolean);
    box.innerHTML = `<h4>📌 Endereço oficial do lote</h4>`
      + (lines.length
          ? `<div class="reg-addr">${lines.join("<br>")}</div>`
          : `<div class="reg-addr">Endereço não disponível para este ponto.</div>`)
      + `<p class="hint">${r.aviso}</p>`;
    $("ficha-links").innerHTML =
      (r.links || []).map((l) => `<a href="${l.url}" target="_blank">${l.label}</a>`).join("")
      + `<a href="${p.street_view}" target="_blank">📍 Street View</a>
         <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}" target="_blank">🗺️ Google Maps</a>
         <span class="hint">Urbano: consulte também o geoportal/IPTU da prefeitura pela inscrição imobiliária.</span>`;
    renderProcLinks();
  } catch (err) {
    box.innerHTML = `<span class="err">Consulta de endereço falhou: ${err.message}</span>`;
  }
}

// Imóvel rural no CAR (SICAR) — traz os dados em tela (não só link).
let carLayer = null;
async function loadCar(p) {
  const box = $("fi-car");
  box.innerHTML = "🌳 Consultando CAR (imóvel rural)…";
  try {
    const c = await (await api(`/api/registry/car?lat=${p.lat}&lon=${p.lon}`)).json();
    if (!c.found) {
      box.innerHTML = `<h4>🌳 CAR — Cadastro Ambiental Rural</h4>
        <div class="hint">Este ponto não está dentro de um imóvel rural cadastrado
        (normal em área urbana). <a href="https://consultapublica.car.gov.br/publico/imoveis/index" target="_blank">Abrir consulta pública do CAR</a></div>`;
      return;
    }
    const areaTxt = c.area_ha != null
      ? c.area_ha.toLocaleString("pt-BR", { maximumFractionDigits: 4 }) + " ha" : "—";
    box.innerHTML = `<h4>🌳 CAR — Imóvel rural</h4>
      <div class="reg-addr">
        Status do cadastro: <b>${c.status_label || "—"}</b><br>
        Tipo de imóvel: <b>${c.tipo_label || "—"}</b><br>
        Município: <b>${c.municipio || "—"}</b><br>
        Área: <b>${areaTxt}</b><br>
        ${c.data_disponibilizacao ? `Atualização: ${c.data_disponibilizacao}<br>` : ""}
        Código CAR: <code>${c.codigo || "—"}</code>
      </div>
      <div class="ficha-links">
        ${c.url ? `<a href="${c.url}" target="_blank">🔗 Abrir no CAR (car.gov.br)</a>` : ""}
        <button class="secondary" id="fi-car-draw">📐 Mostrar imóvel no mapa</button>
      </div>`;
    if (c.geometry) {
      $("fi-car-draw").onclick = () => {
        if (carLayer) map.removeLayer(carLayer);
        carLayer = L.geoJSON(c.geometry, {
          interactive: false,
          style: { color: "#16a34a", weight: 2, fillColor: "#22c55e",
                   fillOpacity: 0.18, dashArray: "5 4" },
        }).addTo(map);
        if (carLayer.getBounds().isValid())
          map.fitBounds(carLayer.getBounds(), { padding: [40, 40] });
      };
    }
  } catch (e) {
    box.innerHTML = `<span class="err">Consulta CAR falhou: ${e.message}</span>`;
  }
}

// Proprietário PJ: CNPJ → Receita Federal (BrasilAPI), com quadro de sócios.
$("fi-cnpj-go").onclick = async () => {
  const out = $("fi-cnpj-out");
  out.innerHTML = "Consultando Receita Federal…";
  try {
    const c = await (await api(
      `/api/registry/cnpj/${encodeURIComponent($("fi-cnpj").value)}`)).json();
    let html = `<b>${c.razao_social || "?"}</b> · ${c.cnpj}<br>`;
    if (c.nome_fantasia) html += `Fantasia: ${c.nome_fantasia}<br>`;
    html += `Situação: <b>${c.situacao || "?"}</b>`
      + (c.data_situacao ? ` desde ${c.data_situacao}` : "") + `<br>`;
    if (c.atividade) html += `Atividade: ${c.atividade}<br>`;
    if (c.capital_social != null)
      html += `Capital social: R$ ${Number(c.capital_social).toLocaleString("pt-BR")}<br>`;
    if (c.endereco) html += `Endereço: ${c.endereco}<br>`;
    if (c.telefone) html += `Tel: ${c.telefone}`;
    if (c.email) html += ` · ${c.email}`;
    if (c.socios && c.socios.length) {
      html += `<div class="reg-socios"><b>Sócios (QSA):</b><ul>`
        + c.socios.map((s) =>
            `<li>${s.nome}${s.qualificacao ? " — " + s.qualificacao : ""}</li>`).join("")
        + `</ul></div>`;
    }
    html += `<button class="secondary" id="fi-cnpj-fill">⤵ Usar como proprietário na ficha</button>`;
    out.innerHTML = html;
    $("fi-cnpj-fill").onclick = () => {
      $("fi-proprietario").value = `${c.razao_social} (CNPJ ${c.cnpj})`;
      renderProcLinks();
    };
  } catch (err) { out.innerHTML = `<span class="err">${err.message}</span>`; }
};

// Processo por número CNJ → DataJud (metadados públicos).
$("fi-proc-go").onclick = async () => {
  const out = $("fi-proc-out");
  out.innerHTML = "Consultando DataJud (CNJ) — pode levar ~20 s…";
  try {
    const r = await (await api(
      `/api/registry/processo?numero=${encodeURIComponent($("fi-proc").value)}&uf=${fichaUF}`)).json();
    out.innerHTML = r.processos.map((pr) =>
      `<div class="reg-proc"><b>${pr.numero}</b> · ${pr.tribunal || ""} ${pr.grau || ""}<br>
       ${pr.classe || ""}${pr.assuntos && pr.assuntos.length ? " — " + pr.assuntos.join("; ") : ""}<br>
       ${pr.orgao || ""}${pr.ajuizamento ? " · ajuizado em " + pr.ajuizamento : ""}<br>
       ${pr.ultimo_movimento
          ? `Último movimento: <b>${pr.ultimo_movimento.nome}</b> (${pr.ultimo_movimento.data}) · ${pr.movimentos} movimentos`
          : ""}</div>`).join("")
      + `<p class="hint">${r.aviso}</p>`;
  } catch (err) { out.innerHTML = `<span class="err">${err.message}</span>`; }
};

// Links de busca de processos PELO NOME do proprietário (sem API pública: LGPD).
function renderProcLinks() {
  const nome = ($("fi-proprietario").value || "").split("(")[0].trim();
  const q = encodeURIComponent(nome);
  $("fi-proc-links").innerHTML = nome
    ? `<span class="hint">Buscar processos pelo nome do proprietário:</span>
       <a href="https://www.jusbrasil.com.br/busca?q=${q}" target="_blank">🔎 JusBrasil</a>
       <a href="https://www.escavador.com/busca?q=${q}&qo=p" target="_blank">🔎 Escavador</a>`
      + (fichaUF === "GO"
          ? `<a href="https://projudi.tjgo.jus.br/BuscaProcessoPublica" target="_blank">⚖️ TJGO (Projudi)</a>`
          : "")
    : `<span class="hint">Preencha o proprietário (ou consulte o CNPJ) para gerar os links de busca por nome.</span>`;
}
$("fi-proprietario").addEventListener("input", renderProcLinks);

$("fi-close").onclick = () => { $("ficha").classList.add("hidden"); currentLot = null; };
$("fi-layout").onclick = () => { if (currentLot != null) openLayout(currentLot); };

$("fi-save").onclick = async () => {
  if (currentLot == null || !lastProjectId) return;
  try {
    const body = {
      matricula: $("fi-matricula").value,
      inscricao: $("fi-inscricao").value,
      proprietario: $("fi-proprietario").value,
      contato: $("fi-contato").value,
      status: $("fi-status").value,
      notas: $("fi-notas").value,
    };
    const saved = await (await api(`/api/projects/${lastProjectId}/lots/${currentLot}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    lotsInfo[String(currentLot)] = saved;
    $("fi-msg").textContent = "✔ Ficha salva.";
    renderRanking(lastFeatures);
  } catch (e) { $("fi-msg").textContent = "Erro: " + e.message; }
};

function _sourceLabel(data) {
  if (!data) return "";
  const prov = data.provider || $("adv-provider").value || "";
  const src = data.buildings_source || "";
  const provLabel = { footprint: "Footprint local", dynamic_world: "Dynamic World (GEE)", gee: "Sentinel-2 NDVI/NDBI (GEE)" }[prov] || prov;
  const srcLabel = {
    osm: "OSM", overture: "Overture Maps", google: "Google Open Buildings",
    ms: "Microsoft", "ms+osm": "Microsoft + OSM",
  }[src] || src;
  return `<p class="hint source-badge">Motor: <strong>${provLabel}</strong>${srcLabel ? ` · Edificações: <strong>${srcLabel}</strong>` : ""}</p>`;
}

function renderReport(rep, data) {
  const box = $("report");
  if (!rep || !rep.total) {
    box.classList.add("hidden"); box.innerHTML = "";
    if (data) msg(`Nenhum lote candidato encontrado em "${data.query}" com os filtros atuais.`, "err");
    return;
  }
  const cards = rep.scenarios.map((s) => `
    <button class="scenario" data-occ="${s.max_occ}" data-area="${s.min_area}" style="border-left:5px solid ${s.color}">
      <span class="sc-label">${s.label}</span>
      <span class="sc-desc">${s.desc} · ocup ≤ ${(s.max_occ * 100).toFixed(0)}% · ≥ ${s.min_area} m²</span>
      <span class="sc-num">${s.count} lotes · ${s.area_ha} ha</span>
    </button>`).join("");

  const zoning = (rep.by_zoning || []).length
    ? `<h4>Por zoneamento</h4><ul class="mini">`
      + rep.by_zoning.map((z) => `<li>${z.zoning}: ${z.count} lotes · ${z.area_ha} ha</li>`).join("")
      + `</ul>` : "";

  // Filtro pela metragem-alvo escolhida pelo usuário
  const tmin = parseFloat($("target-min").value) || 0;
  const tmax = parseFloat($("target-max").value) || Infinity;
  const inTarget = lastFeatures.filter((f) =>
    f.properties.area_m2 >= tmin && f.properties.area_m2 <= tmax).length;
  const targetCard = `<button class="scenario" data-target="1" style="border-left:5px solid #2563eb">
    <span class="sc-label">Na metragem alvo</span>
    <span class="sc-desc">${tmin.toLocaleString("pt-BR")}–${tmax === Infinity ? "∞" : tmax.toLocaleString("pt-BR")} m²</span>
    <span class="sc-num">${inTarget} lotes</span></button>`;

  box.innerHTML = `
    <h3>Resultado da análise</h3>
    <div class="summary">${rep.total} lotes candidatos · ${rep.area_total_ha} ha no total</div>
    ${_sourceLabel(data)}
    <p class="hint">Clique num cenário para filtrar o mapa:</p>
    <div class="scenarios"><button class="scenario active" data-occ="1" data-area="0">
      <span class="sc-label">Todos</span><span class="sc-num">${rep.total} lotes</span></button>${targetCard}${cards}</div>
    ${zoning}`;
  box.classList.remove("hidden");

  box.querySelectorAll(".scenario").forEach((btn) => {
    btn.onclick = () => {
      box.querySelectorAll(".scenario").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      let shown;
      if (btn.dataset.target) {
        shown = lastFeatures.filter((f) =>
          f.properties.area_m2 >= tmin && f.properties.area_m2 <= tmax);
      } else {
        const maxOcc = parseFloat(btn.dataset.occ), minArea = parseFloat(btn.dataset.area);
        shown = lastFeatures.filter((f) =>
          f.properties.occupation <= maxOcc && f.properties.area_m2 >= minArea);
      }
      drawFeatures(shown);
      renderRanking(shown);
    };
  });
}

// ----------------------- Zoneamento (upload) -------------------------------
$("f-zoning").onchange = async () => {
  const file = $("f-zoning").files[0];
  if (!file) return;
  if (!lastProjectId) return msg("Faça uma análise antes de enviar zoneamento.", "err");
  const fd = new FormData(); fd.append("file", file);
  try {
    const d = await (await api(`/api/projects/${lastProjectId}/layers/zoning`,
      { method: "POST", body: fd })).json();
    msg(`Zoneamento: ${d.features} feições. Clique em "Reanalisar".`, "ok");
  } catch (e) { msg(e.message, "err"); }
};

// --------------------------- Exportação ------------------------------------
document.querySelectorAll(".exp").forEach((b) => {
  b.onclick = async () => {
    if (!lastProjectId) return msg("Faça uma análise primeiro.", "err");
    try {
      const res = await api(`/api/projects/${lastProjectId}/export.${b.dataset.fmt}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "leads." + b.dataset.fmt; a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) { msg(e.message, "err"); }
  };
});

// ===================== Motor de Bolhas (IA) ===============================
const LINE_COLORS = {
  "Área Conquista": "#0ea5e9", "Área Conforto": "#22c55e",
  "Área Detalhe": "#a855f7", "Área Estilo": "#ef4444", "Área +Vida": "#f59e0b",
};
let bolhaLot = null;          // lote com estudo de bolha aberto
let lastBolha = null;         // último estudo gerado/carregado
let bolhaPolling = false;
let colorMode = "score";      // "score" | "bolha"
let bolhaLineByLot = {};      // {lot_id: {linha, bolha, score}} para o mapa de bolhas

// Cor de preenchimento do lote: por score (default) ou por linha de bolha (mapa).
function featureFill(f) {
  if (colorMode === "bolha") {
    const ln = (bolhaLineByLot[String(f.properties.id)] || {}).linha;
    return LINE_COLORS[ln] || "#94a3b8";
  }
  return scoreColor(f.properties.score) || f.properties.color;
}

$("btn-bolhas-map").onclick = loadBolhasMap;

window.openBolha = function (lotId) {
  bolhaLot = lotId;
  const f = lastFeatures.find((x) => x.properties.id === lotId);
  $("bo-lot").textContent = "#" + lotId
    + (f ? ` · ${f.properties.area_m2.toLocaleString("pt-BR")} m²` : "");
  $("bo-msg").textContent = "";
  $("bo-progress").classList.add("hidden");
  const saved = (lotsInfo[String(lotId)] || {}).bolha;
  if (saved) { lastBolha = saved; renderBolhaStudy(saved); $("bo-save").classList.add("hidden"); $("bo-print").classList.remove("hidden"); }
  else { lastBolha = null; $("bo-result").innerHTML =
    `<p class="hint">Clique em <b>Analisar bolha</b> para gerar o estudo de viabilidade.</p>`;
    $("bo-save").classList.add("hidden"); $("bo-print").classList.add("hidden"); }
  $("bolha-panel").classList.remove("hidden");
  map.closePopup();
  focusLot(lotId);
  $("bolha-panel").scrollIntoView({ behavior: "smooth" });
};

$("bo-run").onclick = async () => {
  if (bolhaLot == null) return;
  const f = lastFeatures.find((x) => x.properties.id === bolhaLot);
  if (!f) return ($("bo-msg").textContent = "Lote não encontrado.");
  const faixa = $("bo-faixa").value ? parseInt($("bo-faixa").value) : null;
  const savedLayout = (lotsInfo[String(bolhaLot)] || {}).layout;
  $("bo-msg").textContent = "";
  $("bo-result").innerHTML = "";
  $("bo-save").classList.add("hidden");
  $("bo-print").classList.add("hidden");
  $("bo-run").disabled = true;
  $("bo-progress").classList.remove("hidden");
  $("bo-fill").style.width = "0%";
  $("bo-stage").textContent = "Enviando…";
  $("bo-pct").textContent = "";
  try {
    const data = await (await api("/api/bolha/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: lastProjectId, lot_id: bolhaLot,
        properties: f.properties, lat: f.properties.lat, lon: f.properties.lon,
        target_faixa: faixa,
        layout_stats: savedLayout ? savedLayout.stats : null,
      }),
    })).json();
    pollBolhaJob(data.job_id);
  } catch (e) {
    $("bo-run").disabled = false;
    $("bo-progress").classList.add("hidden");
    $("bo-msg").textContent = "Erro: " + e.message;
  }
};

async function pollBolhaJob(jobId) {
  if (bolhaPolling) return;
  bolhaPolling = true;
  const tick = async () => {
    let j;
    try { j = await (await api(`/api/jobs/${jobId}`)).json(); }
    catch (e) {
      bolhaPolling = false; $("bo-run").disabled = false;
      $("bo-progress").classList.add("hidden");
      return ($("bo-msg").textContent = "Erro ao consultar: " + e.message);
    }
    if (j.status === "running") {
      $("bo-fill").style.width = (j.progress || 0) + "%";
      $("bo-stage").textContent = j.stage || "Processando…";
      $("bo-pct").textContent = (j.progress || 0).toFixed(0) + "%";
      return setTimeout(tick, 1000);
    }
    bolhaPolling = false;
    $("bo-run").disabled = false;
    $("bo-progress").classList.add("hidden");
    if (j.status === "error") return ($("bo-msg").textContent = "Erro: " + j.error);
    const est = j.result.estudo;
    lastBolha = est;
    if (j.result.ficha) lotsInfo[String(bolhaLot)] = j.result.ficha;
    renderBolhaStudy(est);
    $("bo-save").classList.remove("hidden");
    $("bo-print").classList.remove("hidden");
    $("bo-msg").textContent = est.modo === "ia"
      ? `✔ Estudo gerado pela IA (${est.modelo}).`
      : "⚠ IA indisponível — estudo por regras determinísticas.";
  };
  tick();
}

function fmtBRL(v) {
  if (v == null || isNaN(v)) return "—";
  return "R$ " + Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

function renderBolhaStudy(est) {
  const sc = est.score_aplicabilidade;
  const ring = scoreColor(sc) || "#64748b";
  const progs = est.programas || {};
  const progChips = Object.keys(progs).map((k) => {
    const vv = progs[k]; const inc = vv && (vv.incluir != null ? vv.incluir : vv);
    const nome = k === "area_segura" ? "Área Segura" : k === "arte_incrivel" ? "Arte Incrível" : k;
    return `<span class="bo-prog ${inc ? "on" : "off"}" title="${(vv && vv.motivo) || ""}">${inc ? "✓" : "✕"} ${nome}</span>`;
  }).join("");
  const mods = (est.modulos_sugeridos || []).map((m) => `<span class="bo-chip">${m}</span>`).join("");
  const riscos = (est.riscos || []).map((r) => `<li>${r}</li>`).join("");
  const passos = (est.proximos_passos || []).map((p) => `<li>${p}</li>`).join("");
  const alts = (est.alternativas || []).map((a) =>
    `<li><b>${a.bolha_nome}</b> ${a.score != null ? `<span class="bo-altscore">${a.score}</span>` : ""} — ${a.porque || ""}</li>`).join("");
  const v = est.viabilidade || {};
  const chk = est.checklist || {};
  const chkRows = Object.keys(chk).length
    ? `<div class="bo-block"><h4>✅ Checklist da caixa de produto</h4><ul class="bo-chk">`
      + Object.entries(chk).map(([k, val]) => `<li><b>${k.replace(/_/g, " ")}:</b> ${val}</li>`).join("")
      + `</ul></div>` : "";

  $("bo-result").innerHTML = `
    <div class="bo-head">
      <div class="bo-ring" style="--c:${ring}"><span>${sc}</span><small>/100</small></div>
      <div class="bo-title">
        <div class="bo-line">${est.linha || ""}</div>
        <div class="bo-name">${est.bolha_nome || ""}</div>
        <div class="bo-faixa">${est.faixa_label || ""}</div>
      </div>
    </div>
    ${est.modo !== "ia" ? `<div class="pp-flag">${est.aviso_ia || "Modo determinístico (IA indisponível)."}</div>` : ""}
    ${est.divergencia ? `<div class="pp-flag">⚖️ ${est.divergencia}</div>` : ""}
    <div class="bo-block"><h4>👥 Público-alvo</h4><p>${est.publico_alvo || "—"}</p></div>
    <div class="bo-block"><h4>🎯 Promessa central</h4><p>${est.promessa_central || "—"}</p>
      ${est.narrativa ? `<p class="hint">${est.narrativa}</p>` : ""}</div>
    ${est.tipologia ? `<div class="bo-block"><h4>🏠 Tipologia</h4><p>${est.tipologia}</p></div>` : ""}
    <div class="bo-block"><h4>🧱 Módulos sugeridos</h4><div class="bo-chips">${mods || "—"}</div></div>
    <div class="bo-block"><h4>➕ Programas acopláveis</h4><div class="bo-progs">${progChips || "—"}</div></div>
    <div class="bo-block bo-econ"><h4>💰 Viabilidade econômica</h4>
      <div class="bo-econ-grid">
        <span>Preço/unidade${v.preco_teto_oficial ? " (teto)" : " (ref.)"}</span><b>${fmtBRL(v.preco_unidade_ref)}</b>
        <span>Unidades${v.unidades_estimadas ? " (estim.)" : ""}</span><b>${v.unidades ?? "—"}</b>
        <span>VGV estimado</span><b>${fmtBRL(v.vgv_estimado)}</b>
        <span>Custo-alvo máx. (margem ${v.margem_alvo != null ? Math.round(v.margem_alvo * 100) + "%" : "—"})</span><b>${fmtBRL(v.custo_alvo_max)}</b>
      </div>
      <p class="hint">${v.observacao || ""}</p></div>
    ${riscos ? `<div class="bo-block"><h4>⚠️ Riscos</h4><ul>${riscos}</ul></div>` : ""}
    ${chkRows}
    ${est.justificativa ? `<div class="bo-block"><h4>🧭 Justificativa</h4><p>${est.justificativa}</p></div>` : ""}
    ${passos ? `<div class="bo-block"><h4>👉 Próximos passos</h4><ul>${passos}</ul></div>` : ""}
    ${alts ? `<div class="bo-block"><h4>🔁 Bolhas alternativas</h4><ul class="bo-alts">${alts}</ul></div>` : ""}
    <p class="hint bo-aviso">${est.aviso || ""}${est.modelo ? ` · Modelo: ${est.modelo}` : ""}</p>`;
}

$("bo-save").onclick = async () => {
  if (bolhaLot == null || !lastProjectId || !lastBolha) return;
  try {
    const saved = await (await api(`/api/projects/${lastProjectId}/lots/${bolhaLot}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bolha: lastBolha }),
    })).json();
    lotsInfo[String(bolhaLot)] = saved;
    $("bo-msg").textContent = "✔ Estudo de bolha salvo na ficha.";
    $("bo-save").classList.add("hidden");
    renderRanking(lastFeatures);
  } catch (e) { $("bo-msg").textContent = "Erro: " + e.message; }
};

$("bo-close").onclick = () => { $("bolha-panel").classList.add("hidden"); bolhaLot = null; };

// Dossiê imprimível — abre uma janela formatada e dispara a impressão/PDF.
$("bo-print").onclick = () => {
  if (!lastBolha) return;
  const est = lastBolha, v = est.viabilidade || {};
  const lote = est.lote || {};
  const mods = (est.modulos_sugeridos || []).map((m) => `<li>${m}</li>`).join("");
  const riscos = (est.riscos || []).map((r) => `<li>${r}</li>`).join("");
  const passos = (est.proximos_passos || []).map((p) => `<li>${p}</li>`).join("");
  const w = window.open("", "_blank");
  w.document.write(`<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
    <title>Dossiê da Bolha — Lote ${lote.id ?? ""}</title>
    <style>
      body{font:14px/1.5 system-ui,Arial,sans-serif;color:#1e293b;max-width:760px;margin:24px auto;padding:0 16px}
      h1{font-size:22px;margin:0 0 4px} h2{font-size:15px;border-bottom:2px solid #e2e8f0;padding-bottom:3px;margin:18px 0 6px}
      .badge{display:inline-block;background:#0ea5e9;color:#fff;border-radius:6px;padding:3px 10px;font-weight:700}
      .grid{display:grid;grid-template-columns:1fr auto;gap:4px 16px}.grid span{color:#64748b}.grid b{text-align:right}
      .muted{color:#64748b;font-size:12px} ul{margin:4px 0;padding-left:20px}
      @media print{button{display:none}}
    </style></head><body>
    <button onclick="window.print()" style="float:right">🖨️ Imprimir / PDF</button>
    <h1>🫧 Dossiê da Bolha</h1>
    <div class="muted">Lote #${lote.id ?? ""} · ${est.endereco || "endereço n/d"} · ${(lote.area_m2 || 0).toLocaleString("pt-BR")} m²</div>
    <h2>Recomendação</h2>
    <p><span class="badge">${est.score_aplicabilidade}/100</span>
       <b>${est.bolha_nome}</b> — ${est.linha} · ${est.faixa_label || ""}</p>
    <h2>Público &amp; promessa</h2>
    <p><b>Público:</b> ${est.publico_alvo || "—"}</p>
    <p><b>Promessa:</b> ${est.promessa_central || "—"}</p>
    ${est.narrativa ? `<p class="muted">${est.narrativa}</p>` : ""}
    ${est.tipologia ? `<p><b>Tipologia:</b> ${est.tipologia}</p>` : ""}
    <h2>Módulos</h2><ul>${mods || "<li>—</li>"}</ul>
    <h2>Viabilidade econômica</h2>
    <div class="grid">
      <span>Preço/unidade${v.preco_teto_oficial ? " (teto)" : " (ref.)"}</span><b>${fmtBRL(v.preco_unidade_ref)}</b>
      <span>Unidades${v.unidades_estimadas ? " (estim.)" : ""}</span><b>${v.unidades ?? "—"}</b>
      <span>VGV estimado</span><b>${fmtBRL(v.vgv_estimado)}</b>
      <span>Custo-alvo máx.</span><b>${fmtBRL(v.custo_alvo_max)}</b>
    </div><p class="muted">${v.observacao || ""}</p>
    ${riscos ? `<h2>Riscos</h2><ul>${riscos}</ul>` : ""}
    ${est.justificativa ? `<h2>Justificativa</h2><p>${est.justificativa}</p>` : ""}
    ${passos ? `<h2>Próximos passos</h2><ul>${passos}</ul>` : ""}
    <h2 class="muted" style="border:0">Método</h2>
    <p class="muted">${est.aviso || ""}${est.modelo ? ` · Gerado por ${est.modelo}.` : " · Modo determinístico."}</p>
    </body></html>`);
  w.document.close();
};

// ----------------- Mapa de bolhas da cidade (determinístico) ----------------
async function loadBolhasMap() {
  if (!lastProjectId) return msg("Faça uma análise primeiro.", "err");
  msg("Calculando mapa de bolhas…");
  try {
    const data = await (await api(`/api/projects/${lastProjectId}/bolhas-map`)).json();
    bolhaLineByLot = data.lot_line || {};
    colorMode = "bolha";
    drawFeatures(lastFeatures);
    const legend = (data.by_line || []).map((l) =>
      `<li><i style="background:${LINE_COLORS[l.linha] || "#64748b"}"></i>
        <b>${l.linha}</b> — ${l.count} lotes · ${l.area_ha} ha</li>`).join("");
    const box = $("bolhas-summary");
    box.innerHTML = `<h3>🫧 Mapa de bolhas <button id="bolhas-map-off" class="secondary">Voltar ao score</button></h3>
      <p class="hint">Melhor bolha por lote (regra determinística) nos ${data.analyzed} maiores de ${data.total}.</p>
      <ul class="bo-legend">${legend}</ul>`;
    box.classList.remove("hidden");
    $("bolhas-map-off").onclick = () => {
      colorMode = "score"; drawFeatures(lastFeatures); box.classList.add("hidden");
    };
    msg(`Mapa de bolhas: ${data.analyzed} lotes classificados.`, "ok");
  } catch (e) { msg("Erro: " + e.message, "err"); }
}

// ---------- Selecionar/desenhar o próprio terreno (clique CAR / retângulo) ----
let pickMode = false, pickStart = null, pickMoved = false, pickRect = null;
let drawnCounter = 900001;

function setPick(on) {
  pickMode = on;
  $("pick-hint").classList.toggle("hidden", !on);
  $("btn-pick").textContent = on ? "✖ Cancelar seleção" : "📍 Estudar um terreno (clique / desenho)";
  map.getContainer().style.cursor = on ? "crosshair" : "";
  if (on) map.dragging.disable(); else map.dragging.enable();
  if (!on && pickRect) { map.removeLayer(pickRect); pickRect = null; }
  pickStart = null; pickMoved = false;
}
$("btn-pick").onclick = () => setPick(!pickMode);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && pickMode) setPick(false); });

map.on("mousedown", (e) => {
  if (!pickMode) return;
  pickStart = e.latlng; pickMoved = false;
  if (pickRect) { map.removeLayer(pickRect); pickRect = null; }
});
map.on("mousemove", (e) => {
  if (!pickMode || !pickStart) return;
  if (pickStart.distanceTo(e.latlng) > 4) pickMoved = true;
  if (!pickMoved) return;
  const b = L.latLngBounds(pickStart, e.latlng);
  if (pickRect) pickRect.setBounds(b);
  else pickRect = L.rectangle(b, { color: "#0ea5e9", weight: 2, dashArray: "5 4", fillOpacity: 0.1 }).addTo(map);
});
map.on("mouseup", async (e) => {
  if (!pickMode || !pickStart) return;
  const start = pickStart, moved = pickMoved;
  pickStart = null; pickMoved = false;
  if (moved && pickRect) {                      // desenhou um retângulo
    const b = pickRect.getBounds();
    map.removeLayer(pickRect); pickRect = null;
    const w = b.getWest(), s = b.getSouth(), ee = b.getEast(), n = b.getNorth();
    setPick(false);
    studyGeometry({ type: "Polygon",
      coordinates: [[[w, s], [ee, s], [ee, n], [w, n], [w, s]]] });
  } else {                                        // clique simples → tenta CAR
    msg("Consultando imóvel do CAR neste ponto…");
    try {
      const c = await (await api(`/api/registry/car?lat=${start.lat}&lon=${start.lng}`)).json();
      if (c.found && c.geometry) {
        setPick(false);
        msg(`Imóvel rural do CAR: ${c.municipio || ""} · ${c.area_ha} ha. Estudando…`, "ok");
        studyGeometry(c.geometry);
      } else {
        msg("Nenhum imóvel do CAR aqui. Arraste para desenhar um retângulo (ou Esc p/ sair).", "err");
      }
    } catch (err) { msg("Erro CAR: " + err.message, "err"); }
  }
});

async function studyGeometry(geometry) {
  msg("Estudando terreno selecionado…");
  try {
    if (!lastProjectId) {  // cria projeto p/ permitir salvar ficha/bolha
      const pj = await (await api("/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Terrenos selecionados" }),
      })).json();
      lastProjectId = pj.id;
    }
    const nid = drawnCounter++;
    const data = await (await api("/api/parcel/study", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        geometry, profile: $("profile").value,
        target_min_m2: parseFloat($("target-min").value) || null,
        target_max_m2: parseFloat($("target-max").value) || null,
        next_id: nid,
      }),
    })).json();
    const feats = (data.results && data.results.features) || [];
    if (!feats.length) return msg("Não foi possível estudar este terreno.", "err");
    const f = feats[0];
    lastFeatures.push(f);
    $("bolhas-map-bar").classList.remove("hidden");
    drawFeatures(lastFeatures);
    renderRanking(lastFeatures);
    focusLot(f.properties.id);
    resultLayer.eachLayer((l) => { if (l._lotId === f.properties.id) l.openPopup(); });
    msg(`✔ Terreno estudado (lote ${f.properties.id} · `
      + `${Math.round(f.properties.area_m2).toLocaleString("pt-BR")} m²`
      + `${f.properties.score != null ? ` · score ${f.properties.score}` : ""}). `
      + `Abra 🫧 Analisar bolha no popup.`, "ok");
  } catch (e) { msg("Erro: " + e.message, "err"); }
}

setMode("city");
