/* Planificador de expansión Genea: interfaz web.
   Toda la información sale de la API (/api/...): la interfaz no calcula nada del modelo. */
"use strict";

const API = "";  // misma URL que sirve la página
const $ = (s, el = document) => el.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null || Number.isNaN(n)) ? "s/d" : Number(n).toLocaleString("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n, d = 0) => (n == null) ? "s/d" : (n > 0 && n * 100 < 0.5 * 10 ** -d) ? `&lt;${fmt(10 ** -d, d)}%` : fmt(n * 100, d) + "%";

const ESTADO = { modelo: null, paises: [], pesos: null, filtroP: 0, ultimoRanking: null, fichaBase: null };
const ORDEN_COMP = ["mercado", "diversidad_origen", "conectividad", "poblacion", "mayores65_pct"];
const PRESETS = {
  "Base (TP3)": { mercado: 35, diversidad_origen: 20, conectividad: 15, poblacion: 20, mayores65_pct: 10 },
  "Mercado primero": { mercado: 60, diversidad_origen: 10, conectividad: 5, poblacion: 20, mayores65_pct: 5 },
  "Perfil genealógico": { mercado: 25, diversidad_origen: 30, conectividad: 25, poblacion: 10, mayores65_pct: 10 },
  "Equilibrado": { mercado: 20, diversidad_origen: 20, conectividad: 20, poblacion: 20, mayores65_pct: 20 },
};
const segColor = (s) => `var(--seg${s})`;
const chipP = (p) => `<span class="chip p${p}">Prioridad ${p}</span>`;
const chipSeg = (s, nombre) => `<span class="seg" style="--c:${segColor(s)}">${esc(nombre)}</span>`;

/* ---------------------------------------------------------------- API */
async function api(ruta, opciones = {}) {
  const r = await fetch(API + ruta, { headers: { "Content-Type": "application/json" }, ...opciones });
  let cuerpo = null;
  try { cuerpo = await r.json(); } catch (_) { /* respuesta sin JSON */ }
  if (!r.ok) {
    const e = new Error(cuerpo?.error?.mensaje || `Error ${r.status}`);
    e.detalles = cuerpo?.error?.detalles || [];
    e.status = r.status;
    throw e;
  }
  return cuerpo;
}
function cajaError(e) {
  const det = (e.detalles || []).filter((d) => d.mensaje).map((d) => `<li><b>${esc(d.campo)}</b>: ${esc(d.mensaje)}</li>`).join("");
  return `<div class="error-caja" role="alert">${esc(e.message)}${det ? `<ul>${det}</ul>` : ""}</div>`;
}
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

/* ---------------------------------------------------------------- tema (manual) */
function aplicarTema(t) {
  document.documentElement.dataset.theme = t;
  $("#tema").setAttribute("aria-label", t === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro");
  try { localStorage.setItem("genea-tema", t); } catch (_) { /* sin almacenamiento */ }
}
$("#tema").addEventListener("click", () => aplicarTema(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
try { const t = localStorage.getItem("genea-tema"); if (t === "dark" || t === "light") aplicarTema(t); } catch (_) { /* nada */ }

/* ---------------------------------------------------------------- navegación */
const VISTAS = ["ranking", "pais", "simulador", "apellido", "como"];
function navegar() {
  const [vista, arg] = (location.hash.replace("#", "") || "ranking").split("/");
  const v = VISTAS.includes(vista) ? vista : "ranking";
  VISTAS.forEach((x) => { $(`#v-${x}`).hidden = x !== v; });
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("activo", a.dataset.tab === v));
  if (v === "pais") mostrarFicha(decodeURIComponent(arg || $("#sel-pais").value || "AR"));
  if (v === "simulador" && arg) { $("#sim-base").value = decodeURIComponent(arg); cargarBaseSim(); }
  if (v === "apellido" && arg) { $("#in-apellido").value = decodeURIComponent(arg); buscarApellido(); }
  window.scrollTo({ top: 0 });
}
window.addEventListener("hashchange", navegar);

/* ---------------------------------------------------------------- dónde entrar */
function armarPesos() {
  const nombres = ESTADO.modelo.nombres_componentes;
  ESTADO.pesos = { ...PRESETS["Base (TP3)"] };
  $("#presets").innerHTML = Object.keys(PRESETS).map((n, i) => `<button type="button" class="chip-boton${i === 0 ? " activo" : ""}" data-preset="${esc(n)}">${esc(n)}</button>`).join("");
  $("#sliders").innerHTML = ORDEN_COMP.map((c) => `
    <div class="slider">
      <div class="lbl"><label for="w-${c}">${esc(nombres[c])}</label><b id="wv-${c}"></b></div>
      <input type="range" id="w-${c}" min="0" max="100" step="1" value="${ESTADO.pesos[c]}" data-c="${c}">
    </div>`).join("");
  $("#presets").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-preset]"); if (!b) return;
    ESTADO.pesos = { ...PRESETS[b.dataset.preset] };
    ORDEN_COMP.forEach((c) => { $(`#w-${c}`).value = ESTADO.pesos[c]; });
    marcarPreset(); pintarPesos(); recalcular();
  });
  $("#sliders").addEventListener("input", (ev) => {
    const c = ev.target.dataset.c; if (!c) return;
    ESTADO.pesos[c] = Number(ev.target.value);
    marcarPreset(); pintarPesos(); recalcularDiferido();
  });
  pintarPesos();
}
function marcarPreset() {
  document.querySelectorAll("[data-preset]").forEach((b) => {
    const p = PRESETS[b.dataset.preset];
    b.classList.toggle("activo", ORDEN_COMP.every((c) => p[c] === ESTADO.pesos[c]));
  });
}
function pintarPesos() {
  const total = ORDEN_COMP.reduce((s, c) => s + ESTADO.pesos[c], 0) || 1;
  ORDEN_COMP.forEach((c) => { $(`#wv-${c}`).textContent = fmt(100 * ESTADO.pesos[c] / total) + "%"; });
}
async function recalcular() {
  const total = ORDEN_COMP.reduce((s, c) => s + ESTADO.pesos[c], 0);
  if (total === 0) { $("#kpis-ranking").innerHTML = cajaError(new Error("Al menos un peso tiene que ser mayor a cero.")); return; }
  try {
    const r = await api("/api/ranking", { method: "POST", body: JSON.stringify({ pesos: ESTADO.pesos }) });
    ESTADO.ultimoRanking = r;
    pintarRanking();
  } catch (e) { $("#kpis-ranking").innerHTML = cajaError(e); }
}
const recalcularDiferido = debounce(recalcular, 300);

function pintarRanking() {
  const r = ESTADO.ultimoRanking; if (!r) return;
  const p1 = r.paises.filter((p) => p.prioridad === 1);
  $("#kpis-ranking").innerHTML = `
    <div class="kpi"><div class="v">${p1.length}</div><div class="t">mercados en Prioridad 1</div><div class="s">${p1.slice(0, 4).map((p) => esc(p.pais)).join(", ")}${p1.length > 4 ? "…" : ""}</div></div>
    <div class="kpi"><div class="v">${esc(r.paises[0].pais)}</div><div class="t">mercado número 1</div><div class="s">puntaje ${fmt(r.paises[0].puntaje, 1)}</div></div>
    <div class="kpi"><div class="v">${r.top10_compartido_con_base}/10</div><div class="t">del top 10 coinciden con el ranking base</div><div class="s">correlación ${fmt(r.correlacion_con_ranking_base, 2)}</div></div>`;
  const filas = r.paises.filter((p) => !ESTADO.filtroP || p.prioridad === ESTADO.filtroP);
  $("#tabla-ranking").innerHTML = `
    <thead><tr><th>#</th><th>País</th><th>Segmento</th><th>Puntaje</th><th class="num">Prob. top 10</th><th>Prioridad</th><th class="num">vs. base</th></tr></thead>
    <tbody>${filas.map((p) => {
      const c = p.cambio_puesto, cl = c > 0 ? "sube" : c < 0 ? "baja" : "igual";
      const txt = c > 0 ? `▲ ${c}` : c < 0 ? `▼ ${-c}` : "=";
      return `<tr class="clic" data-cod="${esc(p.codigo)}" tabindex="0">
        <td>${p.puesto}</td>
        <td><div class="pais-celda"><b>${esc(p.pais)}</b><small>${esc(p.codigo)}</small></div></td>
        <td>${chipSeg(p.segmento, p.nombre_segmento)}</td>
        <td><div class="mini-barra"><div class="pista"><div class="relleno" style="width:${Math.max(0, Math.min(100, p.puntaje))}%"></div></div><span>${fmt(p.puntaje, 1)}</span></div></td>
        <td class="num">${pct(p.prob_top10)}</td>
        <td>${chipP(p.prioridad)}</td>
        <td class="num"><span class="cambio ${cl}">${txt}</span></td></tr>`;
    }).join("")}</tbody>`;
}
$("#filtro-prioridad").addEventListener("click", (ev) => {
  const b = ev.target.closest("button"); if (!b) return;
  ESTADO.filtroP = Number(b.dataset.p);
  document.querySelectorAll("#filtro-prioridad button").forEach((x) => x.classList.toggle("activo", x === b));
  pintarRanking();
});
$("#tabla-ranking").addEventListener("click", (ev) => { const tr = ev.target.closest("tr[data-cod]"); if (tr) location.hash = `#pais/${tr.dataset.cod}`; });
$("#tabla-ranking").addEventListener("keydown", (ev) => { const tr = ev.target.closest("tr[data-cod]"); if (tr && ev.key === "Enter") location.hash = `#pais/${tr.dataset.cod}`; });

/* ---------------------------------------------------------------- ficha */
function barraIndice(nombre, valor, centro) {
  const pos = (v) => 50 + Math.max(-3, Math.min(3, v)) / 3 * 50;
  const a = pos(Math.min(0, valor)), b = pos(Math.max(0, valor));
  return `<div class="indice"><div class="lbl"><span>${esc(nombre)}</span><b>${fmt(valor, 2)}</b></div>
    <div class="divergente"><div class="cero"></div><div class="valor" style="left:${a}%;width:${b - a}%"></div>
    <div class="centro" style="left:${pos(centro)}%" title="Centro del segmento: ${fmt(centro, 2)}"></div></div></div>`;
}
function barrasAportes(aportes) {
  const nombres = ESTADO.modelo.nombres_componentes;
  const max = Math.max(0.05, ...ORDEN_COMP.map((c) => Math.abs(aportes[c])));
  return ORDEN_COMP.map((c) => {
    const v = aportes[c], w = Math.abs(v) / max * 50;
    const izq = v < 0 ? 50 - w : 50;
    return `<div class="aporte"><span>${esc(nombres[c])}</span>
      <div class="pista"><div class="cero"></div><div class="valor" style="left:${izq}%;width:${w}%;background:${v < 0 ? "var(--err)" : "var(--bar)"}"></div></div>
      <span class="num">${v >= 0 ? "+" : ""}${fmt(v, 2)}</span></div>`;
  }).join("");
}
function listaPuentes(puentes, nombrePais) {
  if (!puentes.length) return `<p class="vacio">Sin países con afinidad de apellidos de 0,2 o más. En la fuente, sus apellidos casi no se comparten con otros países.</p>`;
  return `<ul class="puentes">${puentes.map((p) => `<li><div><b>${esc(p.pais)}</b><small>${fmt(p.migrantes_2024)} migrantes en común con ${esc(nombrePais)} (ONU 2024)</small></div><span class="sim">${fmt(p.similitud, 2)}</span></li>`).join("")}</ul>`;
}
async function mostrarFicha(codigo) {
  $("#sel-pais").value = codigo;
  const caja = $("#ficha");
  caja.innerHTML = `<p class="cargando">Cargando…</p>`;
  try {
    const f = await api(`/api/paises/${encodeURIComponent(codigo)}`);
    if (!f.en_modelo) {
      caja.innerHTML = `<div class="tarjeta"><h2>${esc(f.pais)}</h2><p>${esc(f.motivo)}</p>
        <p><a class="boton" href="#simulador/${esc(f.codigo)}">Evaluarlo en el simulador</a></p>
        <h3>Países puente</h3>${listaPuentes(f.puentes, f.pais)}</div>`;
      return;
    }
    const s = f.segmento, r = f.ranking, ind = ESTADO.modelo.nombres_componentes;
    caja.innerHTML = `
      <div class="tarjeta" style="margin-bottom:1rem">
        <div class="cabecera-ficha">
          <div><h2>${esc(f.pais)}</h2><div class="meta">${esc(f.region_es)} · ${esc(f.ingreso)}${f.origen_imputado ? " · origen imputado con la mediana regional" : ""}</div></div>
          <div class="numeros">
            <div><b>${r.puesto}°</b><span>de 65 en el ranking</span></div>
            <div><b>${fmt(r.puntaje, 1)}</b><span>puntaje (0 a 100)</span></div>
            <div><b>${pct(r.prob_top10)}</b><span>prob. de top 10</span></div>
            <div style="justify-content:center">${chipP(r.prioridad)}</div>
          </div>
        </div>
        <div class="estrategia" style="--c:${segColor(s.id)}">
          <div class="etiqueta">Segmento: ${esc(s.nombre)}</div>
          <div class="rasgo">${esc(s.rasgo)}</div>
          <div class="como">Cómo entrar: ${esc(s.estrategia)}</div>
        </div>
      </div>
      <div class="grilla-3">
        <div class="tarjeta"><h3>Índices del país</h3>
          ${barraIndice(ind.diversidad_origen, f.indices.diversidad_origen, s.centroide["Diversidad de origen"])}
          ${barraIndice(ind.conectividad, f.indices.conectividad, s.centroide["Conectividad de apellidos"])}
          ${barraIndice(ind.mercado, f.indices.mercado, s.centroide["Mercado"])}
          <div class="leyenda"><span><i style="background:var(--bar)"></i>país (desvíos)</span><span><i style="background:var(--accent)"></i>centro del segmento</span></div>
        </div>
        <div class="tarjeta"><h3>Por qué está en ese puesto</h3>
          <p class="nota" style="margin:0 0 .7rem">Aporte de cada componente al puntaje: valor estandarizado por su peso.</p>
          ${barrasAportes(r.aportes)}
        </div>
        <div class="tarjeta"><h3>Países puente</h3>
          <p class="nota" style="margin:0 0 .4rem">Con quién comparte más apellidos: entrar acá abre la puerta a estos mercados.</p>
          ${listaPuentes(f.puentes, f.pais)}
        </div>
      </div>
      <p style="margin-top:1rem"><a class="boton" href="#simulador/${esc(f.codigo)}">Simular un escenario para ${esc(f.pais)}</a></p>`;
  } catch (e) { caja.innerHTML = cajaError(e); }
}
$("#sel-pais").addEventListener("change", (ev) => { location.hash = `#pais/${ev.target.value}`; });

/* ---------------------------------------------------------------- simulador */
const GRUPOS = [
  ["Apellidos y origen", ["diversidad_origen", "n_familias_relevantes", "cuota_apellidos_transregionales", "paises_por_apellido_pond", "similitud_max"]],
  ["Mercado", ["pbi_pc_ppa", "internet_pct", "urbana_pct"]],
  ["Demografía", ["poblacion", "mayores65_pct"]],
];
function armarSimulador() {
  const m = ESTADO.modelo;
  const opciones = ESTADO.paises.slice().sort((a, b) => a.pais.localeCompare(b.pais, "es"));
  $("#sim-base").innerHTML = `<option value="">País nuevo (vacío)</option>` +
    opciones.map((p) => `<option value="${esc(p.codigo)}">${esc(p.pais)}</option>`).join("") + `<option value="TW">Taiwán (sin datos del Banco Mundial)</option>`;
  $("#sim-ejemplos").innerHTML = `
    <button type="button" class="chip-boton" data-ej="ar">Argentina con más PBI e internet</button>
    <button type="button" class="chip-boton" data-ej="tw">Taiwán, sin datos</button>`;
  const vars = m.variables_entrada;
  $("#sim-campos").innerHTML = `
    <fieldset class="grupo"><legend>Categorías</legend><div class="campos">
      <label class="campo" data-campo="region"><span>Región</span><select name="region"><option value="">Sin indicar</option>${m.regiones.map((r) => `<option value="${esc(r.codigo)}">${esc(r.nombre)}</option>`).join("")}</select></label>
      <label class="campo" data-campo="income"><span>Nivel de ingreso</span><select name="income"><option value="">Sin indicar</option>${m.niveles_ingreso.map((n) => `<option>${esc(n)}</option>`).join("")}</select></label>
    </div></fieldset>` + GRUPOS.map(([titulo, campos]) => `
    <fieldset class="grupo"><legend>${esc(titulo)}</legend><div class="campos">
      ${campos.map((c) => `<label class="campo" data-campo="${c}"><span>${esc(vars[c].nombre)} <small>(${esc(vars[c].unidad)})</small></span>
        <input type="number" step="any" name="${c}" inputmode="decimal" placeholder="vacío: se imputa"></label>`).join("")}
    </div></fieldset>`).join("");
  $("#sim-base").addEventListener("change", cargarBaseSim);
  $("#sim-reset").addEventListener("click", cargarBaseSim);
  $("#sim-campos").addEventListener("input", marcarCambios);
  $("#sim-ejemplos").addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-ej]"); if (!b) return;
    if (b.dataset.ej === "ar") {
      $("#sim-base").value = "AR"; await cargarBaseSim();
      $("[name=pbi_pc_ppa]").value = 45000; $("[name=internet_pct]").value = 95; marcarCambios();
    } else { $("#sim-base").value = "TW"; await cargarBaseSim(); }
    evaluar();
  });
  $("#form-sim").addEventListener("submit", (ev) => { ev.preventDefault(); evaluar(); });
}
const REGION_A_CODIGO = (txt) => (ESTADO.modelo.regiones.find((r) => r.codigo === txt || r.nombre === txt) || {}).codigo || "";
async function cargarBaseSim() {
  const cod = $("#sim-base").value;
  const form = $("#form-sim");
  form.querySelectorAll("input, select[name]").forEach((el) => { el.value = ""; });
  ESTADO.fichaBase = null;
  if (cod) {
    try {
      const f = await api(`/api/paises/${cod}`);
      ESTADO.fichaBase = f;
      form.querySelector("[name=region]").value = REGION_A_CODIGO(f.region);
      if (f.ingreso) form.querySelector("[name=income]").value = f.ingreso;
      Object.entries(f.variables || {}).forEach(([k, v]) => { const el = form.querySelector(`[name=${k}]`); if (el && v != null) el.value = +Number(v).toPrecision(6); });
    } catch (e) { $("#sim-resultado").innerHTML = cajaError(e); }
  }
  marcarCambios();
  $("#sim-resultado").innerHTML = `<div class="tarjeta"><p class="vacio">${cod ? "Cambiá algún dato y tocá Evaluar." : "Completá los datos que tengas y tocá Evaluar. Lo que quede vacío se imputa."}</p></div>`;
}
function valoresBase() {
  const f = ESTADO.fichaBase; if (!f || !f.en_modelo) return {};
  const v = {}; Object.entries(f.variables).forEach(([k, x]) => { v[k] = x == null ? "" : String(+Number(x).toPrecision(6)); });
  v.region = REGION_A_CODIGO(f.region); v.income = f.ingreso; return v;
}
function marcarCambios() {
  const base = valoresBase();
  document.querySelectorAll("#sim-campos .campo").forEach((c) => {
    const el = c.querySelector("input, select"); c.classList.remove("error"); c.querySelector(".msg")?.remove();
    c.classList.toggle("cambiado", !!ESTADO.fichaBase?.en_modelo && el.value !== (base[el.name] ?? ""));
  });
}
async function evaluar() {
  const form = $("#form-sim"), datos = {};
  // Con un país de base solo se envía lo que cambió: la API conserva el resto de los datos originales
  const base0 = ESTADO.fichaBase?.en_modelo ? valoresBase() : null;
  let borrados = [];
  form.querySelectorAll("#sim-campos input, #sim-campos select").forEach((el) => {
    if (base0 && el.value === (base0[el.name] ?? "")) return;
    if (el.value === "") { if (base0) borrados.push(el.name); return; }
    datos[el.name] = el.type === "number" ? Number(el.value) : el.value;
  });
  if (borrados.length) {
    $("#sim-resultado").innerHTML = cajaError(new Error("Para probar con datos faltantes usá \"País nuevo\" o Taiwán: en un escenario, los campos vacíos conservan el dato original."));
    return;
  }
  const base = $("#sim-base").value || null;
  if (!base && Object.keys(datos).length === 0) { $("#sim-resultado").innerHTML = cajaError(new Error("Cargá al menos un dato del país nuevo.")); return; }
  $("#sim-resultado").innerHTML = `<p class="cargando">Evaluando…</p>`;
  try {
    const r = await api("/api/evaluar", { method: "POST", body: JSON.stringify({ base_codigo: base, pais: datos, pesos: ESTADO.pesos }) });
    pintarEvaluacion(r);
  } catch (e) {
    $("#sim-resultado").innerHTML = cajaError(e);
    (e.detalles || []).forEach((d) => {
      const c = document.querySelector(`#sim-campos [data-campo="${(d.campo || "").replace("pais.", "")}"]`);
      if (c) { c.classList.add("error"); c.insertAdjacentHTML("beforeend", `<span class="msg">${esc(d.mensaje)}</span>`); }
    });
  }
}
function pintarEvaluacion(r) {
  const s = r.segmento, k = r.ranking, o = r.comparacion_original;
  const cambioSeg = o ? (o.segmento === s.id ? `<span>Se mantiene en el mismo segmento.</span>` :
    `<span>Pasa de</span> ${chipSeg(o.segmento, o.nombre_segmento)} <span>a</span> ${chipSeg(s.id, s.nombre)}`) : "";
  const cambioPuesto = o ? `<div class="s">antes: ${o.puesto}° (${fmt(o.puntaje, 1)})</div>` : "";
  const maxD = Math.max(...r.distancias_segmentos.map((d) => d.distancia));
  const avisos = r.avisos.length ? `<ul class="avisos">${r.avisos.map((a) => `<li class="${a.tipo === "fuera_de_rango_observado" ? "info" : ""}">${esc(a.mensaje)}</li>`).join("")}</ul>`
    : `<p class="vacio">Sin imputaciones: todos los datos fueron provistos.</p>`;
  $("#sim-resultado").innerHTML = `
    <div class="kpis">
      <div class="kpi"><div class="v">${k.puesto}°</div><div class="t">de ${k.de} en el ranking</div>${cambioPuesto}</div>
      <div class="kpi"><div class="v">${fmt(k.puntaje, 1)}</div><div class="t">puntaje (escala de los 65 países)</div><div class="s">prob. top 10: ${pct(k.prob_top10, 1)}</div></div>
      <div class="kpi"><div class="v" style="font-size:1.1rem;padding:.35rem 0">${chipP(k.prioridad)}</div><div class="t">${o && o.prioridad !== k.prioridad ? `antes: Prioridad ${o.prioridad}` : "nivel de prioridad"}</div></div>
    </div>
    <div class="tarjeta">
      <div class="estrategia" style="--c:${segColor(s.id)}">
        <div class="etiqueta">${esc(r.nombre)} · segmento</div>
        <div class="como">${esc(s.nombre)}</div>
        <div class="rasgo">${esc(s.estrategia)}</div>
      </div>
      ${cambioSeg ? `<div class="cambio-seg" style="margin-top:.8rem">${cambioSeg}</div>` : ""}
    </div>
    <div class="grilla-2">
      <div class="tarjeta"><h3>Datos y calidad <span class="calidad ${r.calidad}">calidad ${esc(r.calidad)}</span></h3>${avisos}</div>
      <div class="tarjeta"><h3>Cercanía a cada segmento</h3>
        <ul class="distancias">${r.distancias_segmentos.map((d) => `<li><span>${chipSeg(d.segmento, d.nombre)}</span>
          <div class="pista"><div class="relleno" style="--c:${segColor(d.segmento)};width:${100 - 85 * d.distancia / maxD}%"></div></div><span class="num">${fmt(d.distancia, 2)}</span></li>`).join("")}</ul>
        <p class="nota">Distancia al centro de cada segmento en los tres índices: queda en el más cercano.</p>
      </div>
    </div>
    <div class="tarjeta"><h3>Aporte de cada componente al puntaje</h3>${barrasAportes(k.aportes)}
      <p class="nota">Con los pesos elegidos en "Dónde entrar": ${ORDEN_COMP.map((c) => `${esc(ESTADO.modelo.nombres_componentes[c])} ${pct(ESTADO.pesos[c] / ORDEN_COMP.reduce((t, x) => t + ESTADO.pesos[x], 0))}`).join(", ")}.</p></div>`;
}

/* ---------------------------------------------------------------- apellido */
const sugerirApellido = debounce(async (texto) => {
  if (texto.trim().length < 2) return;
  try {
    const r = await api(`/api/apellidos?q=${encodeURIComponent(texto)}`);
    $("#sug-apellido").innerHTML = r.sugerencias.map((s) => `<option value="${esc(s)}">`).join("");
  } catch (_) { /* las sugerencias son opcionales */ }
}, 250);
$("#in-apellido").addEventListener("input", (ev) => sugerirApellido(ev.target.value));
$("#form-apellido").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const t = $("#in-apellido").value.trim();
  if (location.hash === `#apellido/${encodeURIComponent(t)}`) buscarApellido(); else location.hash = `#apellido/${encodeURIComponent(t)}`;
});
async function buscarApellido() {
  const t = $("#in-apellido").value.trim(), caja = $("#res-apellido");
  if (t.length < 2) { caja.innerHTML = cajaError(new Error("Escribí un apellido de al menos 2 letras.")); return; }
  caja.innerHTML = `<p class="cargando">Buscando…</p>`;
  try {
    const r = await api(`/api/apellidos/${encodeURIComponent(t)}`);
    const max = Math.max(...r.paises.map((p) => p.registros));
    const prioritarios = r.paises.filter((p) => p.prioridad === 1).map((p) => p.pais);
    const mensaje = prioritarios.length
      ? `Tu apellido aparece en <b>${r.cantidad_paises} ${r.cantidad_paises === 1 ? "país" : "países"}</b>. Genea va a entrar primero a <b>${esc(prioritarios.join(", "))}</b>: ahí vas a poder buscar otras ramas de tu familia desde el lanzamiento.`
      : `Tu apellido aparece en <b>${r.cantidad_paises} ${r.cantidad_paises === 1 ? "país" : "países"}</b>. Ninguno está en la primera ola de Genea, así que la búsqueda en esos países llegaría en una etapa siguiente.`;
    caja.innerHTML = `
      <div class="res-cabecera"><h2>${esc(r.apellido)}</h2>
        <p>${r.origen ? `Origen según la fuente: ${esc(r.origen)}` : "La fuente no informa su origen"}${r.familia_origen ? ` · familia ${esc(r.familia_origen)}` : ""}${r.se_busco_sin_particulas ? " · buscado sin partículas" : ""}</p></div>
      <div class="mensaje-usuario">${mensaje}</div>
      <div class="tarjeta"><div class="tabla-scroll"><table class="tabla">
        <thead><tr><th>País</th><th>Registros en la fuente</th><th class="num">Puesto en el país</th><th>Para Genea</th></tr></thead>
        <tbody>${r.paises.map((p) => `<tr${p.en_modelo ? ` class="clic" data-cod="${esc(p.codigo)}"` : ""}>
          <td><div class="pais-celda"><b>${esc(p.pais)}</b><small>${esc(p.codigo)}</small></div></td>
          <td><div class="mini-barra"><div class="pista"><div class="relleno" style="width:${100 * p.registros / max}%"></div></div><span>${fmt(p.registros)}</span></div></td>
          <td class="num">${p.puesto_en_pais ? `${fmt(p.puesto_en_pais)}°` : "s/d"}</td>
          <td>${p.en_modelo ? `${chipP(p.prioridad)} <small class="vacio">${esc(p.nombre_segmento)}</small>` : `<small class="vacio">fuera del modelo</small>`}</td></tr>`).join("")}</tbody>
      </table></div><p class="nota">${esc(r.nota)}</p></div>`;
    caja.querySelectorAll("tr[data-cod]").forEach((tr) => tr.addEventListener("click", () => { location.hash = `#pais/${tr.dataset.cod}`; }));
  } catch (e) {
    const sug = (e.detalles || []).flatMap((d) => d.sugerencias || []);
    caja.innerHTML = `<div class="tarjeta" style="text-align:center"><p><b>${esc(e.message)}</b></p>
      <p class="vacio">La fuente registra los apellidos más frecuentes de cada país, así que muchos apellidos no figuran.</p>
      ${sug.length ? `<p>¿Quisiste decir?</p><div class="sugerencias">${sug.map((s) => `<a class="chip-boton" href="#apellido/${encodeURIComponent(s)}">${esc(s)}</a>`).join("")}</div>` : ""}</div>`;
  }
}

/* ---------------------------------------------------------------- cómo funciona */
function armarComo() {
  const m = ESTADO.modelo, e = m.embudo_seleccion, nombres = m.nombres_componentes;
  const escalon = (txt, n, final = false) => `<div class="escalon${final ? " final" : ""}"><div><div class="txt">${esc(txt)}</div><div class="pista"><div class="relleno" style="width:${Math.max(2, 100 * n / e.total)}%"></div></div></div><b>${n}</b></div>`;
  const ganadora = e.candidatas[0];
  $("#como").innerHTML = `
    <div class="grilla-2">
      <div class="tarjeta"><h2>Tres capas, tres preguntas</h2>
        <ol class="pasos">
          <li><b>Segmentación</b>: qué tipo de mercado es cada país y cómo conviene entrar. k-means con 5 segmentos sobre tres índices.</li>
          <li><b>Ranking</b>: en qué orden entrar. Puntaje ponderado y 5.000 simulaciones de pesos para medir su robustez.</li>
          <li><b>Países puente</b>: qué mercados se abren desde cada uno. Afinidad de apellidos, validada con la migración de la ONU (rho 0,34, Mantel p &lt; 0,001).</li>
        </ol>
      </div>
      <div class="tarjeta"><h2>Cómo se procesa un país nuevo</h2><ol class="pasos">${m.orden_preparacion.map((p) => `<li>${esc(p)}</li>`).join("")}</ol></div>
    </div>
    <div class="tarjeta" style="margin-top:1rem"><h2>Peso de cada variable</h2>
      <p class="nota" style="margin:0 0 .7rem">Cada índice es el promedio de sus variables estandarizadas, así que cada una pesa lo mismo dentro de su índice. El peso efectivo en el puntaje es el peso del índice dividido por la cantidad de variables.</p>
      <div class="tabla-scroll"><table class="tabla"><thead><tr><th>Variable</th><th>Índice</th><th class="num">Peso en el índice</th><th class="num">Peso efectivo en el puntaje</th></tr></thead>
      <tbody>${m.pesos_variables.map((p) => `<tr><td>${esc(p.nombre)}</td><td>${esc(p.indice)}</td><td class="num">${p.peso_en_indice == null ? "no aplica" : pct(p.peso_en_indice, 1)}</td>
        <td><div class="mini-barra"><div class="pista"><div class="relleno" style="width:${p.peso_efectivo_en_puntaje / 0.2 * 100}%"></div></div><span>${pct(p.peso_efectivo_en_puntaje, 2)}</span></div></td></tr>`).join("")}</tbody></table></div>
      <p class="nota">Pesos del ranking: ${ORDEN_COMP.map((c) => `${esc(nombres[c])} ${pct(m.pesos_ranking[c])}`).join(", ")}.</p>
    </div>
    <div class="grilla-2" style="margin-top:1rem">
      <div class="tarjeta"><h2>Cómo se eligió el modelo</h2>
        <p class="nota" style="margin:0 0 .8rem">Regla fijada antes de ver los resultados. Se aplica como un embudo sobre la grilla.</p>
        <div class="embudo">
          ${escalon("Configuraciones evaluadas", e.total)}
          ${escalon("Estabilidad de 0,7 o más", e.pasan_estabilidad)}
          ${escalon("Además, segmentos de 5 países o más", e.pasan_ambos)}
          ${escalon(`Mayor silhouette: ${ganadora.algoritmo}, k = ${ganadora.k}`, 1, true)}
        </div>
        <p class="nota">Por separado, ${e.pasan_tamano} de las ${e.total} cumplen el tamaño mínimo: el filtro que más recorta es la estabilidad. Las que pasan: ${Object.entries(e.por_espacio).map(([k, v]) => `${esc(k)} ${v.pasan_ambos}`).join(", ")}.</p>
      </div>
      <div class="tarjeta"><h2>Las 5 mejores que pasaron los filtros</h2>
        <div class="tabla-scroll"><table class="tabla"><thead><tr><th>Espacio</th><th>Algoritmo</th><th class="num">k</th><th class="num">Silhouette</th><th class="num">Estabilidad</th></tr></thead>
        <tbody>${e.candidatas.slice(0, 5).map((c, i) => `<tr${i === 0 ? ' style="font-weight:700"' : ""}><td>${esc(c.espacio)}</td><td>${esc(c.algoritmo)}</td><td class="num">${c.k}</td><td class="num">${fmt(c.silhouette, 3)}</td><td class="num">${fmt(c.estabilidad, 3)}</td></tr>`).join("")}</tbody></table></div>
      </div>
    </div>
    <div class="tarjeta" style="margin-top:1rem"><h2>Los cinco segmentos</h2>
      <div class="grilla-3" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">${m.segmentos.map((s) => `<div class="estrategia" style="--c:${segColor(s.id)}"><div class="etiqueta">${esc(s.nombre)} · ${s.paises.length} países</div><div class="rasgo">${esc(s.rasgo)}</div><div class="como" style="font-size:.9rem">${esc(s.estrategia)}</div></div>`).join("")}</div>
    </div>
    <div class="grilla-2" style="margin-top:1rem">
      <div class="tarjeta"><h2>Regla de prioridad</h2><ul>${Object.entries(m.regla_prioridad).map(([k, v]) => `<li>${chipP(k)} ${esc(v)}</li>`).join("")}</ul></div>
      <div class="tarjeta"><h2>Limitaciones</h2><ul>${m.limitaciones.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></div>
    </div>`;
}

/* ---------------------------------------------------------------- inicio */
async function iniciar() {
  try {
    const [modelo, paises] = await Promise.all([api("/api/modelo"), api("/api/paises")]);
    ESTADO.modelo = modelo; ESTADO.paises = paises.paises;
    $("#version").textContent = `Modelo v${modelo.version}.`;
    const ordenados = ESTADO.paises.slice().sort((a, b) => a.pais.localeCompare(b.pais, "es"));
    $("#sel-pais").innerHTML = ordenados.map((p) => `<option value="${esc(p.codigo)}">${esc(p.pais)}</option>`).join("") + `<option value="TW">Taiwán</option>`;
    $("#sel-pais").value = "AR";
    armarPesos(); armarSimulador(); armarComo();
    await recalcular();
    navegar();
  } catch (e) {
    const caja = $("#estado-servicio"); caja.hidden = false;
    caja.innerHTML = `No se pudo conectar con el servicio del modelo. ${esc(e.message)}`;
  }
}
iniciar();
