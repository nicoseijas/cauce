import maplibregl, { ExpressionSpecification, Map } from "maplibre-gl";
import type { Estado } from "./estado";
type ActivacionLocalidad = NonNullable<Estado["activacion"]>[string];

const CAPAS_TR = ["inund-tr-fill", "inund-tr-line"];

let cargado = false;
let escenario = 0;
let activacion: Record<string, ActivacionLocalidad> = {};
let uteRioNegro: Estado["ute_rio_negro"];
let factoresCurso: Estado["factores_curso"] = {};
let avisosLluvia: AvisoLluvia[] = [];
let coberturaActivacion: Estado["activacion_cobertura"];
let estadoActualVigente = false;

// Umbrales orientativos de "lluvia abundante" (del orden de las advertencias
// meteorológicas de INUMET); son un aviso de atención sobre la cuenca, nunca
// una mancha inferida: la cadena es lluvia → caudal → nivel → mancha.
const AVISO_MM24 = 50;
const AVISO_MM72 = 100;

type AvisoLluvia = { clave: string; lugar: string; detalle: string };

function mm(v: number): string {
  return String(v).replace(".", ",");
}

function calcularAvisosLluvia(estado?: Estado): AvisoLluvia[] {
  if (!estado) return [];
  const avisos: AvisoLluvia[] = [];
  for (const e of estado.lluvia?.estaciones ?? []) {
    if (e.mm24 >= AVISO_MM24 || e.mm72 >= AVISO_MM72) {
      const fuente = e.fuente ?? "INUMET";
      // INIA publica el día pluviométrico cerrado (09 a 09 h): no es la
      // ventana móvil de 24 h de INUMET y puede tener hasta ~30 h de atraso
      const ventana = fuente === "INIA" && e.fecha
        ? `${mm(e.mm24)} mm el ${e.fecha.slice(8, 10)}/${e.fecha.slice(5, 7)} (09–09 h)`
        : `${mm(e.mm24)} mm/24 h`;
      avisos.push({
        clave: e.nombre,
        lugar: e.nombre,
        detalle: `${ventana} · ${mm(e.mm72)} mm/72 h (${fuente})`,
      });
    }
  }
  for (const e of estado.ana?.estaciones ?? []) {
    if (e.mm24 >= AVISO_MM24 && e.horas <= 24) {
      avisos.push({
        clave: e.id,
        lugar: e.nombre,
        detalle: `${mm(e.mm24)} mm/24 h (ANA)`,
      });
    }
  }
  return avisos;
}

function nombrePeriodo(p: number): string {
  return p >= 9999 ? "creciente extrema" : `${p} años`;
}

function filtroActivas(): ExpressionSpecification {
  const ramas: ExpressionSpecification[] = [];
  for (const [cod, a] of Object.entries(activacion)) {
    if (a.periodo_activo > 0) {
      ramas.push([
        "all",
        ["==", ["get", "localidad_cod"], cod],
        ["<=", ["get", "periodo"], a.periodo_activo],
      ]);
    }
  }
  return ramas.length
    ? (["any", ...ramas] as unknown as ExpressionSpecification)
    : ["==", ["get", "periodo"], -1];
}

function coma(n: number): string {
  return n.toFixed(2).replace(".", ",");
}

const ETIQUETAS_TIPO: Record<string, string> = {
  fluvial: "fluviales",
  costera_estuarina: "costeras/estuarinas",
  pluvial_urbana: "pluvial urbana",
  mixta_no_separada: "mixta sin separar",
  sin_clasificar: "sin clasificar",
};

function resumenTipos(cobertura: NonNullable<Estado["activacion_cobertura"]>): string {
  return Object.entries(cobertura.tipos_inundacion ?? {})
    .filter(([, cantidad]) => cantidad > 0)
    .map(([tipo, cantidad]) => `${cantidad} ${ETIQUETAS_TIPO[tipo] ?? tipo}`)
    .join(", ");
}

function resumenAhora(): { html: string; nivel: string; corto: string } {
  const activas = Object.entries(activacion).filter(([, a]) => a.periodo_activo > 0);
  const crecidas = Object.entries(factoresCurso)
    .filter(([, v]) => v.factor >= 2)
    .sort((a, b) => b[1].factor - a[1].factor);

  const lineas: string[] = [];
  let nivel = "verde";
  let corto = "Estado hídrico disponible";

  if (!estadoActualVigente) {
    nivel = "ambar";
    corto = "Estado sin actualizar — inundación actual no evaluada";
    lineas.push(
      `<div class="ahora-linea"><span class="dot ambar"></span><span>` +
      `No hay un estado reciente. Se muestran los escenarios oficiales ` +
      `precalculados, pero no se evalúa si están superados ahora.</span></div>`,
    );
  } else if (!coberturaActivacion || coberturaActivacion.habilitadas === 0) {
    nivel = "ambar";
    const candidatas = coberturaActivacion?.configuradas ?? 0;
    const tipos = coberturaActivacion ? resumenTipos(coberturaActivacion) : "";
    const conEstacion = coberturaActivacion?.con_estacion_superficial ?? 0;
    const conCurso = coberturaActivacion?.con_curso_compatible ?? 0;
    corto = "Activación automática deshabilitada — sin localidades validadas";
    lineas.push(
      `<div class="ahora-linea"><span class="dot ambar"></span><span>` +
      `Activación automática deshabilitada: 0 de ${candidatas} localidades ` +
      `candidatas tienen datum y relación hidráulica completamente validados. ` +
      `No puede afirmarse que ninguna mancha esté superada.` +
      (tipos ? ` Casos separados: ${tipos}.` : "") +
      (candidatas ? ` ${conEstacion} tienen estación superficial y ${conCurso} ` +
        `además coinciden con el curso.` : "") +
      `</span></div>`,
    );
  } else if (activas.length) {
    nivel = "roja";
    corto = `${activas.length} mancha${activas.length > 1 ? "s" : ""} de inundación superada${activas.length > 1 ? "s" : ""}`;
    lineas.push(
      `<div class="ahora-linea"><span class="dot roja"></span><span class="alerta">` +
      activas.map(([, a]) =>
        `⚠ ${a.estacion}: superada la mancha de ${nombrePeriodo(a.periodo_activo)} ` +
        `(nivel ${coma(a.nivel)} m)`).join("<br>") +
      `</span></div>`);
  } else if (!coberturaActivacion.fuente_disponible) {
    nivel = "ambar";
    corto = "DINAGUA sin dato apto — inundación actual no evaluada";
    lineas.push(
      `<div class="ahora-linea"><span class="dot ambar"></span><span>` +
      `DINAGUA no aporta un dato apto en esta actualización. ` +
      `No puede afirmarse que ninguna mancha esté superada.</span></div>`,
    );
  } else if (coberturaActivacion.evaluadas < coberturaActivacion.habilitadas) {
    nivel = "ambar";
    corto = `${coberturaActivacion.evaluadas} de ${coberturaActivacion.habilitadas} localidades evaluadas`;
    lineas.push(
      `<div class="ahora-linea"><span class="dot ambar"></span><span>` +
      `Cobertura parcial: ${coberturaActivacion.evaluadas} de ` +
      `${coberturaActivacion.habilitadas} localidades habilitadas evaluadas. ` +
      `No se emite un resultado negativo nacional.</span></div>`,
    );
  } else {
    corto = `Sin manchas superadas entre ${coberturaActivacion.evaluadas} localidades evaluadas`;
    lineas.push(
      `<div class="ahora-linea"><span class="dot verde"></span><span>` +
      `Ninguna mancha superada entre las ${coberturaActivacion.evaluadas} ` +
      `localidades habilitadas y evaluadas.</span></div>`,
    );
  }

  if (crecidas.length) {
    if (nivel === "verde") nivel = "ambar";
    corto += ` · ${crecidas.length} señal${crecidas.length > 1 ? "es" : ""} elevada${crecidas.length > 1 ? "s" : ""}`;
    const top = crecidas.slice(0, 3).map(([curso, v], i) => {
      // el factor llega recortado al clamp del pipeline: 20 significa "al menos 20"
      const fx = v.factor >= 20 ? "≥20" : v.factor.toFixed(1).replace(".", ",");
      const tipo = v.insumo_clasificacion === "pronosticado" ? "pronóstico" : "observación";
      const texto = `${curso} ${fx}× (${tipo})`;
      return i === 0 ? `<strong>${texto}</strong>` : texto;
    });
    const resto = crecidas.length > 3 ? ` · +${crecidas.length - 3} más` : "";
    lineas.push(
      `<div class="ahora-det"><span class="dot ambar"></span><span>` +
      `${crecidas.length} curso${crecidas.length > 1 ? "s" : ""} con escala visual elevada: ` +
      `${top.join(" · ")}${resto} <span style="color:#6a86a1">` +
      `(estimación aplicada al curso; no prueba inundación)</span></span></div>`);
  }

  if (avisosLluvia.length) {
    if (nivel === "verde") nivel = "ambar";
    corto += ` · lluvia abundante (${avisosLluvia.length})`;
    lineas.push(
      `<div class="ahora-det"><span class="dot ambar"></span><span>` +
      `Lluvia abundante: ` +
      avisosLluvia.map((a) => `${a.lugar} ${a.detalle}`).join(" · ") +
      ` — atención en su cuenca ` +
      `<span style="color:#6a86a1">(no implica inundación)</span></span></div>`);
  }

  const proximos = Object.values(activacion)
    .filter((a) => a.proximo)
    .sort((x, y) => x.proximo!.faltan_m - y.proximo!.faltan_m)
    .slice(0, 2);
  for (const a of proximos) {
    lineas.push(
      `<div class="ahora-det"><span class="dot ambar"></span><span>` +
      `${a.estacion}: a ${coma(a.proximo!.faltan_m)} m de su mancha de ` +
      `${nombrePeriodo(a.proximo!.periodo)}</span></div>`);
  }
  return { html: lineas.join(""), nivel, corto };
}

const NOMBRES_FUENTE: Record<string, string> = {
  dinagua_wfs: "DINAGUA", salto_grande: "Salto Grande", inumet_lluvia: "INUMET",
  inia_lluvia: "INIA", ina: "INA", ute_rio_negro: "UTE", ana: "ANA", sohma: "SOHMA",
};

function fechaCorta(valor: string | null): string {
  if (!valor) return "sin fecha conocida";
  const fecha = new Date(valor);
  return Number.isFinite(fecha.getTime())
    ? fecha.toLocaleString("es-UY", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : valor;
}

function escaparHtml(valor: string): string {
  return valor.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]!);
}

function llenarFuentes(estado?: Estado): void {
  const resumen = document.getElementById("estado-fuentes-resumen")!;
  const detalle = document.getElementById("estado-fuentes-detalle")!;
  const fuentes = Object.entries(estado?.fuentes_detalle ?? {})
    .filter(([clave, f]) => clave !== "caru" && f.estado !== "no_implementada");
  const problemas = fuentes.filter(([, f]) => f.estado !== "ok").length;
  resumen.textContent = estado
    ? `Fuentes: ${fuentes.length - problemas} aptas · ${problemas} con problema`
    : "Fuentes: sin archivo de estado";
  if (!fuentes.length) {
    detalle.textContent = "No hay metadatos de fuentes disponibles.";
    return;
  }
  detalle.innerHTML = fuentes.map(([clave, f]) => {
    const bien = f.estado === "ok";
    const rotulo = bien ? "apta" : f.estado.replace("_", " ");
    return `<div class="fuente-fila"><span>${NOMBRES_FUENTE[clave] ?? clave}</span>` +
      `<span class="${bien ? "estado-ok" : "estado-mal"}">${rotulo}</span>` +
      `<span class="fuente-fecha">última observación: ` +
      `${escaparHtml(fechaCorta(f.ultima_observacion))}</span></div>`;
  }).join("");
}

function llenarControlCalidad(estado?: Estado): void {
  const resumen = document.getElementById("estado-qc-resumen")!;
  const detalle = document.getElementById("estado-qc-detalle")!;
  const qc = estado?.control_calidad;
  if (!qc) {
    resumen.textContent = "Control de calidad: sin metadatos";
    detalle.textContent = "Este archivo de estado no publica resultados QC.";
    return;
  }
  const contar = (variable: "nivel" | "caudal", estadoQc: string) =>
    (qc.resumen[variable] as Record<string, number | undefined>)[estadoQc] ?? 0;
  const problemas = qc.incidencias.length;
  resumen.textContent = `QC v${qc.version}: ${problemas} incidencia${problemas === 1 ? "" : "s"}`;

  const filasIncidencia = qc.incidencias.map((i) =>
    `<div class="fuente-fila"><span>${escaparHtml(i.estacion)} · ${i.variable}</span>` +
    `<span class="estado-mal">${i.estado}</span>` +
    `<span class="fuente-fecha">${escaparHtml(i.codigos.join(", ").replaceAll("_", " "))}` +
    ` · valor original ${i.valor} · ${escaparHtml(fechaCorta(i.fecha))}</span></div>`,
  ).join("");
  const vigilancia = qc.vigilancia_reforzada.map((v) =>
    `<div class="fuente-fila"><span>${escaparHtml(v.estacion)}</span>` +
    `<span class="estado-mal">vigilancia</span>` +
    `<span class="fuente-fecha">${escaparHtml(v.motivo)}</span></div>`,
  ).join("");
  detalle.innerHTML =
    `<div>Nivel: ${contar("nivel", "ok")} aptos · ${contar("nivel", "vencido")} vencidos · ` +
    `${contar("nivel", "dudoso")} dudosos · ${contar("nivel", "rechazado")} rechazados.</div>` +
    `<div>Caudal: ${contar("caudal", "ok")} aptos · ${contar("caudal", "vencido")} vencidos · ` +
    `${contar("caudal", "dudoso")} dudosos · ${contar("caudal", "rechazado")} rechazados.</div>` +
    (filasIncidencia || `<div style="color:#6a86a1">Sin incidencias dudosas o rechazadas.</div>`) +
    (vigilancia ? `<div style="margin-top:7px;color:#8fa8bd">Antecedentes que exigen vigilancia reforzada:</div>${vigilancia}` : "") +
    `<div style="margin-top:7px;color:#6a86a1">No corrige ni interpola valores. ` +
    `${escaparHtml(qc.metodo.limitacion)}.</div>`;
}

function llenarPrevision(): void {
  const det = document.getElementById("creciente-prevision")!;
  if (!uteRioNegro?.dias?.length) return;
  const hoy = uteRioNegro.dias[0];
  const maxMercedes = uteRioNegro.maximos.find((m) => /Mercedes/.test(m.lugar));
  document.getElementById("prevision-resumen")!.innerHTML =
    `Río Negro — pronóstico oficial · horizonte 7 días` +
    (maxMercedes
      ? ` <span style="color:#8fa8bd">· Mercedes máx ${coma(maxMercedes.nivel)} m` +
        ` el ${maxMercedes.fecha.slice(0, 5)}</span>`
      : "");
  const act = uteRioNegro.actualizado
    ? `act. ${uteRioNegro.actualizado.slice(8, 10)}/${uteRioNegro.actualizado.slice(5, 7)} (UTE)`
    : "UTE";
  const partes: string[] = [];
  if (hoy.erogado_palmar) {
    partes.push(
      `<div>Palmar: suelta prevista para hoy ` +
      `${hoy.erogado_palmar.toLocaleString("es-UY")} m³/s</div>`);
  }
  // se conserva el paréntesis con la escala de referencia de cada nivel
  const ciudades = uteRioNegro.maximos.filter((m) =>
    /Mercedes|Paso de los Toros|Polanco/.test(m.lugar));
  for (const m of ciudades) {
    const lugar = m.lugar.replace(/^Ciudad( de)?\s*/, "");
    partes.push(`<div>${lugar}: máx previsto ${coma(m.nivel)} m el ${m.fecha.slice(0, 5)}</div>`);
  }
  partes.push(
    `<div style="color:#6a86a1">Pronóstico determinista · horizonte 7 días · ` +
    `probabilidad e incertidumbre no publicadas por UTE · ${act}</div>`,
  );
  document.getElementById("prevision-detalle")!.innerHTML = partes.join("");
  det.style.display = "block";
}

async function cargarCapas(map: Map, base: string): Promise<void> {
  const [tr, cri, dre, ame] = await Promise.all([
    fetch(`${base}data/inundacion_tr.geojson`).then((r) => r.json()),
    fetch(`${base}data/inundacion_cri.geojson`).then((r) => r.json()),
    fetch(`${base}data/drenaje.geojson`).then((r) => r.json()),
    fetch(`${base}data/amenazas.geojson`).then((r) => r.json()),
  ]);
  map.addSource("inund-tr", { type: "geojson", data: tr });
  map.addSource("inund-cri", { type: "geojson", data: cri });
  map.addSource("drenaje", { type: "geojson", data: dre });
  map.addSource("amenazas", { type: "geojson", data: ame });

  const COLOR_PERIODO: ExpressionSpecification = [
    "step", ["get", "periodo"],
    "#e05c5c", 11, "#e08a5c", 101, "#e0b95c",
  ];
  map.addLayer({
    id: "inund-tr-fill",
    type: "fill",
    source: "inund-tr",
    paint: {
      "fill-color": COLOR_PERIODO,
      "fill-opacity": ["interpolate", ["linear"], ["zoom"], 8, 0.25, 11, 0.4],
    },
  }, "rios-glow");
  map.addLayer({
    id: "inund-tr-line",
    type: "line",
    source: "inund-tr",
    paint: { "line-color": COLOR_PERIODO, "line-width": 1.2, "line-opacity": 0.8 },
  }, "rios-glow");
  map.addLayer({
    id: "inund-cri-fill",
    type: "fill",
    source: "inund-cri",
    layout: { visibility: "none" },
    paint: { "fill-color": "#c08bf0", "fill-opacity": 0.16 },
  }, "rios-glow");
  map.addLayer({
    id: "inund-cri",
    type: "line",
    source: "inund-cri",
    layout: { visibility: "none" },
    paint: { "line-color": "#c08bf0", "line-width": 1, "line-opacity": 0.6 },
  }, "rios-glow");
  map.addLayer({
    id: "drenaje-fill",
    type: "fill",
    source: "drenaje",
    layout: { visibility: "none" },
    paint: { "fill-color": "#e0a45c", "fill-opacity": 0.25 },
  }, "rios-glow");
  map.addLayer({
    id: "amenazas",
    type: "circle",
    source: "amenazas",
    layout: { visibility: "none" },
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2, 10, 5],
      "circle-color": "#e0a45c",
      "circle-opacity": 0.7,
      "circle-stroke-color": "#0b141d",
      "circle-stroke-width": 0.8,
    },
  }, "rios-glow");
  map.addLayer({
    id: "inund-activa",
    type: "fill",
    source: "inund-tr",
    filter: filtroActivas(),
    paint: { "fill-color": "#ff4d4d", "fill-opacity": 0.45 },
  }, "rios-glow");
  map.addLayer({
    id: "inund-activa-line",
    type: "line",
    source: "inund-tr",
    filter: filtroActivas(),
    paint: { "line-color": "#ff6b6b", "line-width": 2 },
  }, "rios-glow");

  const popup = (html: string, lngLat: maplibregl.LngLat) =>
    new maplibregl.Popup({ closeButton: false, maxWidth: "280px" })
      .setLngLat(lngLat).setHTML(html).addTo(map);

  const popupMancha = (e: maplibregl.MapLayerMouseEvent) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    const a = activacion[p.localidad_cod as string];
    const activa = a && a.periodo_activo >= Number(p.periodo);
    const cabecera = activa
      ? `<span class="alerta">⚠ ACTIVA AHORA</span> — nivel ${a.nivel.toFixed(2)} m en ${a.estacion}<br>`
      : "";
    const incertidumbre = activa
      ? `<span class="aclara">Resultado estimado a partir de una relación ` +
        `nivel→escenario previamente habilitada. No es un aviso oficial; ` +
        `consulte las fuentes y autoridades indicadas.</span>`
      : "";
    popup(
      cabecera +
      `<strong>Mancha de inundación · ${p.tipo_curva}</strong><br>` +
      `${p.curso ?? ""}${p.cota_oficial ? ` · cota ${p.cota_oficial} m` : ""}<br>` +
      `<span style="color:#8fa8bd">${String(p.fuentes ?? "").slice(0, 120)}</span>` +
      incertidumbre,
      e.lngLat,
    );
  };
  map.on("click", "inund-tr-fill", popupMancha);
  // la mancha activa se dibuja aunque el escenario esté oculto, y entonces
  // inund-tr-fill no tiene features bajo el cursor
  map.on("click", "inund-activa", (e) => {
    if (map.queryRenderedFeatures(e.point, { layers: ["inund-tr-fill"] }).length) return;
    popupMancha(e);
  });
  map.on("click", "inund-cri-fill", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    popup(
      `<strong>Inundación registrada</strong><br>` +
      `${p.curso ?? ""} · ${p.fecha_evento ?? "fecha s/d"}<br>` +
      `<span style="color:#8fa8bd">${String(p.fuentes ?? "").slice(0, 120)}</span>`,
      e.lngLat,
    );
  });
  map.on("click", "drenaje-fill", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    popup(
      `<strong>Drenaje urbano · ${p.localidad ?? ""}</strong><br>` +
      `<span style="color:#8fa8bd">${String(p.descripcion_conflicto ?? "").slice(0, 180)}</span>`,
      e.lngLat,
    );
  });
  map.on("click", "amenazas", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    const tipos = [
      ["ribera", "inundación de ribera"], ["canadas", "cañadas"],
      ["drenaje", "drenaje pluvial"], ["presas", "presas"],
      ["costas", "costera"], ["accesibilidad", "accesibilidad"],
    ].filter(([k]) => Number(p[k]) === 1).map(([, v]) => v);
    popup(
      `<strong>${p.localidad}</strong> (${p.departamento})<br>` +
      `<span style="color:#8fa8bd">Amenazas identificadas: ${tipos.join(", ") || "s/d"}</span>`,
      e.lngLat,
    );
  });
}

function crearCapaLluvia(map: Map, estado: Estado): void {
  const lluvia = estado.lluvia;
  if (!lluvia) return;
  map.addSource("lluvia", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: lluvia.estaciones.map((e) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [e.lon, e.lat] },
        properties: e,
      })),
    } as GeoJSON.GeoJSON,
  });
  map.addLayer({
    id: "lluvia",
    type: "circle",
    source: "lluvia",
    layout: { visibility: "none" },
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["get", "mm72"], 0, 4, 150, 24],
      // escala fría: el rojo queda reservado para manchas activas
      "circle-color": [
        "step", ["get", "mm72"],
        "#3b566e", 20, "#5a9bd6", 50, "#8f7ce0", 100, "#c46fe0",
      ],
      "circle-opacity": 0.55,
      "circle-stroke-color": "#cfe0ee",
      "circle-stroke-width": 1,
    },
  });
  map.on("click", "lluvia", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    const fuente = p.fuente ?? "INUMET";
    const pie = fuente === "INIA"
      ? `acumulado diario 09–09 h · último día ${p.fecha}`
      : `hasta ${String(lluvia.hasta).slice(0, 16)} UTC`;
    new maplibregl.Popup({ closeButton: false, maxWidth: "240px" })
      .setLngLat(e.lngLat)
      .setHTML(
        `<strong>${p.nombre}</strong> (${fuente})<br>` +
        `lluvia 24 h: ${p.mm24} mm · 72 h: ${p.mm72} mm<br>` +
        `<span style="color:#8fa8bd">${pie}</span>`)
      .addTo(map);
  });
}

async function crearCapaCuencasLluvia(map: Map, base: string): Promise<void> {
  if (!avisosLluvia.length) return;
  const claves = new Set(avisosLluvia.map((a) => a.clave));
  let fc: GeoJSON.FeatureCollection;
  try {
    fc = await (await fetch(`${base}data/cuencas_lluvia.geojson`)).json();
  } catch {
    return;
  }
  fc.features = fc.features.filter((f) =>
    ((f.properties?.estaciones ?? []) as string[]).some((e) => claves.has(e)),
  );
  if (!fc.features.length) return;

  map.addSource("cuencas-lluvia", { type: "geojson", data: fc });
  const debajo = map.getLayer("rios-glow") ? "rios-glow" : undefined;
  map.addLayer({
    id: "cuencas-lluvia-fill",
    type: "fill",
    source: "cuencas-lluvia",
    layout: { visibility: "none" },
    paint: { "fill-color": "#e8c95a", "fill-opacity": 0.08 },
  }, debajo);
  map.addLayer({
    id: "cuencas-lluvia-line",
    type: "line",
    source: "cuencas-lluvia",
    layout: { visibility: "none" },
    paint: {
      "line-color": "#e8c95a",
      "line-width": 1.6,
      "line-dasharray": [3, 2],
      "line-opacity": 0.8,
    },
  }, debajo);
  map.on("click", "cuencas-lluvia-fill", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    const popup = (html: string, lngLat: maplibregl.LngLat) =>
      new maplibregl.Popup({ closeButton: false, maxWidth: "280px" })
        .setLngLat(lngLat).setHTML(html).addTo(map);
    const dentro = (JSON.parse(String(p.estaciones)) as string[])
      .map((c) => avisosLluvia.find((a) => a.clave === c))
      .filter((a): a is AvisoLluvia => a != null);
    popup(
      `<strong>Cuenca: ${p.cuenca}</strong><br>` +
      dentro.map((a) => `${a.lugar}: ${a.detalle}`).join("<br>") +
      `<br><span style="color:#8fa8bd">Aviso de atención por lluvia ` +
      `abundante. No implica inundación: la lluvia se traduce en caudal y ` +
      `nivel antes que en mancha.</span>`,
      e.lngLat,
    );
  });

  const activo = document.getElementById("creciente")!.classList.contains("activo");
  aplicarVisibilidad(map, activo);
}

function aplicarEscenario(map: Map): void {
  for (const id of CAPAS_TR) {
    map.setFilter(id, ["<=", ["get", "periodo"], escenario]);
  }
}

function visibilidad(map: Map, id: string, on: boolean): void {
  map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
}

function aplicarVisibilidad(map: Map, activo: boolean): void {
  const conCri = (document.getElementById("chk-cri") as HTMLInputElement).checked;
  const conDre = (document.getElementById("chk-dre") as HTMLInputElement).checked;
  const conLlu = (document.getElementById("chk-llu") as HTMLInputElement).checked;
  const visibles: Record<string, boolean> = {
    "inund-tr-fill": activo,
    "inund-tr-line": activo,
    "inund-activa": activo,
    "inund-activa-line": activo,
    "inund-cri": activo && conCri,
    "inund-cri-fill": activo && conCri,
    "drenaje-fill": activo && conDre,
    "amenazas": activo && conDre,
    "lluvia": activo && conLlu,
    // el aviso por lluvia abundante es excepcional: se muestra siempre que
    // el modo creciente esté activo, sin depender del checkbox de lluvia
    "cuencas-lluvia-fill": activo,
    "cuencas-lluvia-line": activo,
  };
  for (const [id, on] of Object.entries(visibles)) {
    if (map.getLayer(id)) visibilidad(map, id, on);
  }
}

export function setupCreciente(
  map: Map,
  base: string,
  estado?: Estado,
  vigente = false,
): void {
  const estadoActual = estado && vigente ? estado : undefined;
  estadoActualVigente = Boolean(estadoActual);
  coberturaActivacion = estado?.activacion_cobertura;
  activacion = estadoActual?.activacion ?? {};
  uteRioNegro = estadoActual?.ute_rio_negro;
  factoresCurso = estadoActual?.factores_curso ?? {};
  avisosLluvia = calcularAvisosLluvia(estadoActual);
  if (estadoActual) crearCapaLluvia(map, estadoActual);
  void crearCapaCuencasLluvia(map, base);
  const panel = document.getElementById("creciente")!;
  const toggle = document.getElementById("creciente-toggle")!;
  const titulo = document.getElementById("creciente-titulo")!;
  const opciones = document.getElementById("creciente-opciones")!;

  const ahora = resumenAhora();
  document.getElementById("creciente-estado")!.innerHTML = ahora.html;
  document.getElementById("hoja-resumen")!.textContent = ahora.corto;
  document.getElementById("hoja-dot")!.className = `dot ${ahora.nivel}`;
  llenarFuentes(estado);
  llenarControlCalidad(estado);
  llenarPrevision();

  toggle.addEventListener("click", async () => {
    const activo = panel.classList.toggle("activo");
    opciones.style.display = activo ? "block" : "none";
    if (activo && !cargado) {
      cargado = true;
      titulo.textContent = "Cargando…";
      await cargarCapas(map, base);
      titulo.textContent = "Modo creciente";
      aplicarEscenario(map);
    }
    if (map.getLayer("inund-tr-fill")) aplicarVisibilidad(map, activo);
  });

  for (const btn of Array.from(opciones.querySelectorAll<HTMLButtonElement>("[data-periodo]"))) {
    btn.addEventListener("click", () => {
      escenario = Number(btn.dataset.periodo);
      for (const b of Array.from(opciones.querySelectorAll("[data-periodo]"))) {
        b.classList.toggle("sel", b === btn);
      }
      if (cargado) aplicarEscenario(map);
    });
  }
  for (const id of ["chk-cri", "chk-dre", "chk-llu"]) {
    (document.getElementById(id) as HTMLInputElement).addEventListener("change", () => {
      aplicarVisibilidad(map, panel.classList.contains("activo"));
    });
  }

  // abierto por defecto: el estado de activación es lo primero que se ve
  (toggle as HTMLButtonElement).click();
}
