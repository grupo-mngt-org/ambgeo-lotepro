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
const map = L.map("map", { preferCanvas: true }).setView([-15.78, -47.93], 12);
L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 20, attribution: "Tiles &copy; Esri" }
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
$("btn-login").onclick = async () => {
  try {
    const res = await api("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("user").value, password: $("pass").value }),
    });
    const data = await res.json();
    token = data.token;
    $("login").classList.add("hidden");
    $("work").classList.remove("hidden");
    $("who").textContent = "👤 " + data.user;
    await loadProfiles();
    msg("Escolha a cidade e clique em Analisar.", "ok");
  } catch (e) { msg("Login falhou: " + e.message, "err"); }
};

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

  html += `<div class="pp-links">`
    + `<a href="${p.street_view}" target="_blank">📍 Street View</a>`
    + ` · <a href="https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lon}" target="_blank">🗺️ Maps</a>`
    + ` · <a href="https://www.registrodeimoveis.org.br" target="_blank">🏛️ ONR (matrícula)</a></div>`;
  html += `<button class="pp-ficha" onclick="openFicha(${p.id})">📋 Ficha do lote</button>`;
  html += `<button class="pp-layout" onclick="openLayout(${p.id})">🏘️ Estudo de implantação</button>`;
  return html;
}

function drawFeatures(features) {
  if (resultLayer) map.removeLayer(resultLayer);
  resultLayer = L.geoJSON({ type: "FeatureCollection", features }, {
    style: (f) => ({
      color: "#fff", weight: 1,
      fillColor: scoreColor(f.properties.score) || f.properties.color,
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
  if (f) loadRegistry(f.properties);
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

setMode("city");
