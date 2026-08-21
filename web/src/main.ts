import maplibregl, {
  ExpressionSpecification,
  GeoJSONSource,
  MapGeoJSONFeature,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { FlowLayer } from "./flow-layer";
import {
  aplicarFactores,
  cargarEstado,
  cargarSeries,
  estacionesComoGeoJSON,
  type Estado,
  type EstacionEstado,
  type SeriePuntos,
} from "./estado";
import { setupCreciente } from "./creciente";

const BASE = import.meta.env.BASE_URL;

const ESCALA_LOG_Q: ExpressionSpecification = [
  "ln", ["+", 1, ["coalesce", ["get", "DIS_AV_CMS"], 0]],
];

const COLOR_CAUDAL: ExpressionSpecification = [
  "interpolate", ["linear"], ESCALA_LOG_Q,
  0, "#1d4460",
  4, "#2e6f9e",
  8, "#57a8d8",
];

const OPACIDAD_GLOW: ExpressionSpecification = [
  "interpolate", ["linear"], ESCALA_LOG_Q,
  3.5, 0, 5.5, 0.10, 8, 0.28,
];

const ES_PANTALLA_CHICA = window.matchMedia("(max-width: 640px)").matches;
const VISTA_INICIAL = {
  center: [-56.0, -32.7] as [number, number],
  zoom: ES_PANTALLA_CHICA ? 6.3 : 8,
};

const map = new maplibregl.Map({
  container: "map",
  hash: true,
  ...VISTA_INICIAL,
  minZoom: 5,
  maxZoom: 13,
  dragRotate: false,
  pitchWithRotate: false,
  touchPitch: false,
  maxPitch: 0,
  attributionControl: false,
  style: {
    version: 8,
    // glyphs autoalojados (Open Sans, Apache-2.0): la URL debe ser absoluta
    glyphs: `${new URL(BASE, location.href).href}fonts/{fontstack}/{range}.pbf`,
    sources: {
      departamentos: { type: "geojson", data: `${BASE}data/departamentos_uy.geojson` },
      vecinos: { type: "geojson", data: `${BASE}data/vecinos.geojson` },
      red: { type: "geojson", data: `${BASE}data/red_uy.geojson` },
      // tramos fusionados por curso: las etiquetas en línea necesitan
      // features largas (los tramos sueltos no alcanzan para un nombre)
      "red-nombres": { type: "geojson", data: `${BASE}data/red_nombres.geojson` },
      "deptos-nombres": { type: "geojson", data: `${BASE}data/departamentos_nombres.geojson` },
      capitales: { type: "geojson", data: `${BASE}data/capitales.geojson` },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#08101a" } },
      {
        id: "vecinos",
        type: "fill",
        source: "vecinos",
        paint: { "fill-color": "#152230" },
      },
      {
        id: "vecinos-limite",
        type: "line",
        source: "vecinos",
        paint: { "line-color": "#2a3d50", "line-width": 0.8 },
      },
      {
        id: "tierra",
        type: "fill",
        source: "departamentos",
        paint: { "fill-color": "#182634" },
      },
      {
        id: "limites",
        type: "line",
        source: "departamentos",
        paint: { "line-color": "#233444", "line-width": 0.6 },
      },
      {
        id: "rios-glow",
        type: "line",
        source: "red",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#6fc0f2",
          "line-opacity": OPACIDAD_GLOW,
          "line-width": [
            "interpolate", ["exponential", 1.6], ["zoom"],
            5, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 0, 4, 4, 8, 12],
            12, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 0, 4, 18, 8, 55],
          ],
          "line-blur": [
            "interpolate", ["exponential", 1.6], ["zoom"],
            5, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 0, 4, 5, 8, 14],
            12, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 0, 4, 22, 8, 60],
          ],
        },
      },
      {
        id: "rios",
        type: "line",
        source: "red",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": COLOR_CAUDAL,
          "line-width": [
            "interpolate", ["exponential", 1.6], ["zoom"],
            5, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 0.3, 4, 1.2, 8, 3.5],
            12, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 1.5, 4, 6, 8, 18],
          ],
          "line-opacity": 0.9,
        },
      },
      {
        id: "rios-hover",
        type: "line",
        source: "red",
        layout: { "line-cap": "round", "line-join": "round" },
        filter: ["==", ["get", "codigo5"], -1],
        paint: {
          "line-color": "#ffd75e",
          "line-width": [
            "interpolate", ["exponential", 1.6], ["zoom"],
            5, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 1, 4, 2, 8, 4.5],
            12, ["interpolate", ["linear"], ESCALA_LOG_Q, 0, 2.5, 4, 7, 8, 20],
          ],
          "line-opacity": 0.9,
        },
      },
      // nombres con jerarquía: ríos grandes desde z7, medianos z8.5, resto z10
      ...([
        {
          id: "nombres-1", minzoom: 7,
          filtro: ["all", ["has", "nombre"],
            [">=", ESCALA_LOG_Q, 5.5]] as ExpressionSpecification,
        },
        {
          id: "nombres-2", minzoom: 8.5,
          filtro: ["all", ["has", "nombre"],
            [">=", ESCALA_LOG_Q, 2.5], ["<", ESCALA_LOG_Q, 5.5]] as ExpressionSpecification,
        },
        {
          id: "nombres-3", minzoom: 10,
          filtro: ["all", ["has", "nombre"],
            ["<", ESCALA_LOG_Q, 2.5]] as ExpressionSpecification,
        },
      ].map(({ id, minzoom, filtro }) => ({
        id,
        type: "symbol" as const,
        source: "red-nombres",
        minzoom,
        filter: filtro,
        layout: {
          "symbol-placement": "line" as const,
          "text-field": ["get", "nombre"] as ExpressionSpecification,
          "text-font": ["Open Sans Semibold"],
          "text-size": [
            "interpolate", ["linear"], ["zoom"],
            7, 10, 12, 15,
          ] as ExpressionSpecification,
          "text-letter-spacing": 0.08,
          "text-max-angle": 60,
          "symbol-spacing": 300,
        },
        paint: {
          "text-color": "#a9c9e2",
          "text-halo-color": "#0b141d",
          "text-halo-width": 1.4,
        },
      }))),
      {
        id: "capitales-punto",
        type: "circle",
        source: "capitales",
        minzoom: 6,
        paint: {
          "circle-radius": ["case", ["==", ["get", "capital_pais"], 1], 4, 2.5],
          "circle-color": "#c9d6e2",
          "circle-opacity": 0.85,
          "circle-stroke-color": "#0b141d",
          "circle-stroke-width": 1,
        },
      },
      {
        id: "capitales-nombre",
        type: "symbol",
        source: "capitales",
        minzoom: 6,
        layout: {
          "text-field": ["get", "nombre"],
          "text-font": ["Open Sans Semibold"],
          "text-size": [
            "interpolate", ["linear"], ["zoom"],
            6, ["case", ["==", ["get", "capital_pais"], 1], 12.5, 10.5],
            12, ["case", ["==", ["get", "capital_pais"], 1], 17, 14],
          ],
          "text-anchor": "top",
          "text-offset": [0, 0.5],
          "symbol-sort-key": ["*", -1, ["get", "pob"]],
        },
        paint: {
          "text-color": "#d8e2ec",
          "text-halo-color": "#0b141d",
          "text-halo-width": 1.3,
        },
      },
      {
        id: "deptos-nombres",
        type: "symbol",
        source: "deptos-nombres",
        minzoom: 5.5,
        maxzoom: 10,
        layout: {
          "text-field": ["upcase", ["get", "nombre"]],
          "text-font": ["Open Sans Semibold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 5.5, 9.5, 9, 15],
          "text-letter-spacing": 0.25,
          "text-padding": 6,
        },
        paint: {
          "text-color": "#46617a",
          "text-halo-color": "#0b141d",
          "text-halo-width": 1,
          "text-opacity": 0.8,
        },
      },
    ],
  },
});

map.touchZoomRotate.disableRotation();
map.keyboard.disableRotation();
// handle de consola para diagnóstico
(window as unknown as { __map: maplibregl.Map }).__map = map;

map.addControl(new maplibregl.AttributionControl({
  compact: true,
  customAttribution:
    "HydroSHEDS/HydroRIVERS · DINAGUA (Min. Ambiente, Uruguay)",
}), "bottom-right");
const ICONO_CASA =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;margin:auto">' +
  '<path d="M3 10.5 12 3l9 7.5"></path><path d="M5 9.5V21h14V9.5"></path></svg>';

class ControlesMapa implements maplibregl.IControl {
  onAdd(m: maplibregl.Map): HTMLElement {
    const div = document.createElement("div");
    div.className = "maplibregl-ctrl maplibregl-ctrl-group";
    const boton = (contenido: string, titulo: string, accion: () => void) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = titulo;
      b.innerHTML = contenido;
      b.style.font = "18px/1 system-ui, sans-serif";
      b.addEventListener("click", accion);
      div.appendChild(b);
    };
    boton("+", "Acercar", () => m.zoomIn());
    boton("−", "Alejar", () => m.zoomOut());
    boton(ICONO_CASA, "Volver a la vista de Uruguay", () =>
      m.flyTo({ ...VISTA_INICIAL, bearing: 0, pitch: 0 }));
    return div;
  }
  onRemove(): void {}
}
map.addControl(new ControlesMapa(), "top-right");

const tooltip = document.getElementById("tooltip")!;
const fpsEl = document.getElementById("fps")!;
// telemetría de desarrollo: visible solo con ?debug (el texto se sigue
// actualizando porque los scripts de captura lo usan como señal de carga)
if (!new URLSearchParams(location.search).has("debug")) {
  fpsEl.style.display = "none";
}

document.getElementById("hoja-barra")!.addEventListener("click", () => {
  document.getElementById("hoja")!.classList.toggle("abierta");
});

function formatoCaudal(q: number): string {
  if (q >= 100) return `${Math.round(q).toLocaleString("es-UY")} m³/s`;
  if (q >= 1) return `${q.toFixed(1)} m³/s`;
  return `${q.toFixed(2)} m³/s`;
}

function mostrarTooltip(f: MapGeoJSONFeature, x: number, y: number): void {
  const nombre = (f.properties.nombre as string) || "Curso sin nombre";
  const q = Number(f.properties.DIS_AV_CMS) || 0;
  const factor = f.properties.factor as number | undefined;
  const fx = factor && factor >= 20 ? "≥20" : factor?.toFixed(1);
  const linea = factor
    ? `caudal actual ≈ ${formatoCaudal(q)} (${fx}× la media` +
      `, est. ${f.properties.estacion_factor})`
    : `caudal medio ${formatoCaudal(q)} (estimado)`;
  tooltip.innerHTML = `<strong>${nombre}</strong><br><span class="q">${linea}</span>`;
  tooltip.style.display = "block";
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
}

type EstacionPopup = EstacionEstado & {
  alerta?: number | null;
  evacuacion?: number | null;
  fuente?: string;
};

function popupEstacion(e: EstacionPopup): string {
  const filas: string[] = [`<strong>${e.nombre}</strong>`];
  if (e.curso) filas.push(`<span class="q">${e.curso}</span>`);
  if (e.nivel != null) {
    filas.push(`nivel ${e.nivel.toFixed(2)} m · hace ${redondearHoras(e.nivel_horas)}`);
  }
  if (e.caudal != null) {
    filas.push(`caudal ${formatoCaudal(e.caudal)} · hace ${redondearHoras(e.caudal_horas)}`);
  }
  if (e.nivel == null && e.caudal == null) filas.push("sin datos recientes");
  if (e.alerta != null && e.nivel != null) {
    if (e.evacuacion != null && e.nivel >= e.evacuacion) {
      filas.push(`<span class="alerta">⚠ nivel de evacuación superado</span>`);
    } else if (e.nivel >= e.alerta) {
      filas.push(`<span class="alerta">⚠ nivel de alerta superado</span>`);
    } else {
      filas.push(`a ${(e.alerta - e.nivel).toFixed(2)} m del nivel de alerta`);
    }
    filas.push(
      `<span class="q">alerta ${e.alerta} m · evacuación ` +
      `${e.evacuacion ?? "—"} m (escala local)</span>`,
    );
  }
  if (e.fuente) filas.push(`<span class="q">${e.fuente}</span>`);
  return filas.join("<br>");
}

function redondearHoras(h: number | null): string {
  if (h == null) return "—";
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} días`;
}

const REPRESAS = [
  { clave: "salto", nombre: "Salto Grande", rio: "Río Uruguay", operador: "CTM (binacional)", lat: -31.2758, lon: -57.9394 },
  { clave: "bonete", nombre: "Rincón del Bonete", rio: "Río Negro", operador: "UTE", lat: -32.8308, lon: -56.4211 },
  { clave: "baygorria", nombre: "Baygorria", rio: "Río Negro", operador: "UTE", lat: -32.8729, lon: -56.8056 },
  { clave: "palmar", nombre: "Palmar (Constitución)", rio: "Río Negro", operador: "UTE", lat: -33.0556, lon: -57.4507 },
] as const;

function popupRepresa(clave: string, estado: Estado | null): string {
  const r = REPRESAS.find((x) => x.clave === clave)!;
  const filas = [
    `<strong>${r.nombre}</strong>`,
    `<span class="q">${r.rio} · represa · ${r.operador}</span>`,
  ];
  const ute = estado?.ute_rio_negro;
  const hoy = ute?.dias?.[0];
  if (clave === "salto") {
    const est = estado?.estaciones.find((e) => e.id === -1);
    if (est?.caudal != null) {
      filas.push(`erogando ${formatoCaudal(est.caudal)} · hace ${redondearHoras(est.caudal_horas)}`);
      if (est.factor) {
        filas.push(`${est.factor >= 20 ? "≥20" : est.factor.toFixed(1)}× su caudal medio`);
      }
    }
    const sg = estado?.salto_grande;
    if (sg?.turbinado != null && sg.vertido != null) {
      filas.push(
        `<span class="q">turbinado ${formatoCaudal(sg.turbinado)} · ` +
        `vertido ${formatoCaudal(sg.vertido)}</span>`);
    }
  } else if (clave === "bonete" || clave === "palmar") {
    const erogado = clave === "bonete" ? hoy?.erogado_bonete : hoy?.erogado_palmar;
    if (erogado) filas.push(`eroga hoy ${formatoCaudal(erogado)} (previsión UTE)`);
    const patron = clave === "bonete" ? /Rincón del Bonete/ : /Constitución/;
    const max = ute?.maximos?.find((m) => patron.test(m.lugar));
    if (max) {
      filas.push(
        `<span class="q">embalse: máx previsto ${max.nivel.toFixed(2)} m ` +
        `el ${max.fecha.slice(0, 5)}</span>`);
    }
    if (!erogado && !max) filas.push(`<span class="q">sin datos UTE recientes</span>`);
  } else {
    filas.push(`<span class="q">sin datos operativos públicos</span>`);
  }
  return filas.join("<br>");
}

function crearCapaRepresas(map: maplibregl.Map, estado: Estado | null): void {
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d")!;
  g.fillStyle = "#16324a";
  g.strokeStyle = "#cfe0ee";
  g.lineWidth = 4;
  g.fillRect(6, 6, 20, 20);
  g.strokeRect(6, 6, 20, 20);
  map.addImage("icono-represa", g.getImageData(0, 0, 32, 32), { pixelRatio: 2 });

  map.addSource("represas", {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: REPRESAS.map((r) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.lon, r.lat] },
        properties: { clave: r.clave },
      })),
    } as GeoJSON.GeoJSON,
  });
  map.addLayer({
    id: "represas",
    type: "symbol",
    source: "represas",
    layout: {
      "icon-image": "icono-represa",
      "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.75, 12, 1.4],
      "icon-allow-overlap": true,
    },
  });
  map.on("click", "represas", async (ev) => {
    const clave = String(ev.features?.[0]?.properties.clave ?? "");
    if (!clave) return;
    const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "260px" })
      .setLngLat(ev.lngLat)
      .setHTML(popupRepresa(clave, estado))
      .addTo(map);
    if (clave !== "salto") return;
    const series = await cargarSeries(`${BASE}data/series.json`);
    const serie = series?.estaciones["-1"];
    if (!serie || !popup.isOpen()) return;
    const grafico = miniGrafico(serie);
    if (grafico) popup.setHTML(popupRepresa(clave, estado) + grafico);
  });
  map.on("mouseenter", "represas", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "represas", () => {
    map.getCanvas().style.cursor = "";
  });
}

function miniGrafico(serie: { nivel?: SeriePuntos; caudal?: SeriePuntos }): string {
  const puntos = serie.nivel ?? serie.caudal;
  if (!puntos || puntos.length < 3) return "";
  const variable = serie.nivel ? "nivel" : "caudal";

  const W = 220, H = 44, PAD = 3;
  const ts = puntos.map(([t]) => t);
  const vs = puntos.map(([, v]) => v);
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  let v0 = Math.min(...vs), v1 = Math.max(...vs);
  if (v1 - v0 < 1e-9) { v0 -= 0.5; v1 += 0.5; }
  const x = (t: number) => PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - ((v - v0) / (v1 - v0)) * (H - 2 * PAD);
  const linea = puntos.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const [tf, vf] = puntos[puntos.length - 1];

  const horas = (t1 - t0) / 3600;
  const lapso = horas < 48 ? `${Math.round(horas)} h` : `${Math.round(horas / 24)} días`;
  const num = (v: number) =>
    variable === "nivel"
      ? v.toFixed(2)
      : v >= 100 ? Math.round(v).toLocaleString("es-UY") : v.toFixed(1);
  const unidad = variable === "nivel" ? "m" : "m³/s";
  const rango = `${num(Math.min(...vs))}–${num(Math.max(...vs))} ${unidad}`;

  return (
    `<div class="serie"><span class="q">${variable} · ${lapso} · ${rango}</span>` +
    `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">` +
    `<polyline points="${linea}" fill="none" stroke="#4a7096" stroke-width="1.5"/>` +
    `<circle cx="${x(tf).toFixed(1)}" cy="${y(vf).toFixed(1)}" r="2.2" fill="#1d7a68"/>` +
    `</svg></div>`
  );
}

map.on("mousemove", (e) => {
  const feats = map.queryRenderedFeatures(
    [[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]],
    { layers: ["rios"] },
  );
  if (feats.length === 0) {
    tooltip.style.display = "none";
    map.setFilter("rios-hover", ["==", ["get", "codigo5"], -1]);
    map.getCanvas().style.cursor = "";
    return;
  }
  const f = feats.reduce((a, b) =>
    (Number(a.properties.DIS_AV_CMS) || 0) >= (Number(b.properties.DIS_AV_CMS) || 0) ? a : b,
  );
  map.getCanvas().style.cursor = "pointer";
  mostrarTooltip(f, e.point.x, e.point.y);
  const codigo = f.properties.codigo5;
  map.setFilter(
    "rios-hover",
    codigo != null
      ? ["==", ["get", "codigo5"], codigo]
      : ["==", ["get", "HYRIV_ID"], f.properties.HYRIV_ID],
  );
});

// Rampa divergente sobre ln(factor); tramos sin medición fresca quedan
// apagados en vez de fingir un valor.
const COLOR_ANOMALIA: ExpressionSpecification = [
  "case",
  ["!", ["has", "factor"]],
  "#2c4257",
  ["interpolate", ["linear"], ["ln", ["get", "factor"]],
    -1.2, "#e0a45c",
    0, "#8fb0c8",
    1.2, "#7ef0d8"],
];

function setupVistaAnomalia(map: maplibregl.Map, flow: FlowLayer): void {
  document.getElementById("vista-switch")!.style.display = "flex";
  const btnCaudal = document.getElementById("vista-caudal")!;
  const btnAnomalia = document.getElementById("vista-anomalia")!;
  const legCaudal = document.getElementById("leyenda-caudal")!;
  const legAnomalia = document.getElementById("leyenda-anomalia")!;

  function activar(anomalia: boolean): void {
    map.setPaintProperty("rios", "line-color", anomalia ? COLOR_ANOMALIA : COLOR_CAUDAL);
    map.setPaintProperty("rios-glow", "line-opacity", anomalia ? 0 : OPACIDAD_GLOW);
    flow.setVisible(!anomalia);
    btnCaudal.classList.toggle("sel", !anomalia);
    btnAnomalia.classList.toggle("sel", anomalia);
    legCaudal.style.display = anomalia ? "none" : "block";
    legAnomalia.style.display = anomalia ? "block" : "none";
  }
  btnCaudal.addEventListener("click", () => activar(false));
  btnAnomalia.addEventListener("click", () => activar(true));
}

map.on("load", async () => {
  const [fc, estado] = await Promise.all([
    fetch(`${BASE}data/red_uy.geojson`).then((r) => r.json()),
    cargarEstado(`${BASE}data/estado_actual.json`),
  ]);

  document.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");

  const estadoEl = document.querySelector("#titulo p")!;
  if (estado) {
    document.getElementById("envivo")!.style.display = "inline-flex";
    const tocados = aplicarFactores(fc, estado);
    (map.getSource("red") as GeoJSONSource).setData(fc);

    map.addSource("estaciones", {
      type: "geojson",
      data: estacionesComoGeoJSON(estado) as GeoJSON.GeoJSON,
    });
    map.addLayer({
      id: "estaciones",
      type: "circle",
      source: "estaciones",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2.5, 12, 7],
        "circle-color": [
          "step", ["get", "frescura"],
          "#5ad18a", 24, "#e8c95a", 48, "#5c7893",
        ],
        "circle-stroke-color": "#0b141d",
        "circle-stroke-width": 1,
        "circle-opacity": 0.9,
      },
    });
    map.on("click", "estaciones", async (ev) => {
      // si hay una represa bajo el cursor, gana su popup
      if (map.queryRenderedFeatures(ev.point, { layers: ["represas"] }).length) return;
      const f = ev.features?.[0];
      if (!f) return;
      const props = f.properties as unknown as EstacionPopup;
      const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "260px" })
        .setLngLat(ev.lngLat)
        .setHTML(popupEstacion(props))
        .addTo(map);
      const series = await cargarSeries(`${BASE}data/series.json`);
      const serie = series?.estaciones[String(props.id)];
      if (!serie || !popup.isOpen()) return;
      const grafico = miniGrafico(serie);
      if (grafico) popup.setHTML(popupEstacion(props) + grafico);
    });
    map.on("mouseenter", "estaciones", () => {
      map.getCanvas().style.cursor = "pointer";
    });

    const fecha = new Date(estado.generado);
    estadoEl.textContent =
      `Datos en vivo: ${tocados} tramos escalados por ${Object.keys(estado.factores_curso).length} ` +
      `estaciones · actualizado ${fecha.toLocaleString("es-UY", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}`;
  } else {
    estadoEl.textContent =
      "Caudal medio de largo plazo (sin datos en vivo disponibles).";
  }

  const flow = new FlowLayer(fc);
  map.addLayer(flow, "rios-hover");
  crearCapaRepresas(map, estado);
  setupCreciente(map, BASE, estado ?? undefined);
  if (estado) setupVistaAnomalia(map, flow);

  let frames = 0;
  let last = performance.now();
  function tick() {
    frames++;
    const now = performance.now();
    if (now - last >= 1000) {
      fpsEl.textContent =
        `${frames} fps · ${flow.particleCount().toLocaleString("es-UY")} partículas`;
      frames = 0;
      last = now;
    }
    requestAnimationFrame(tick);
  }
  tick();
});
