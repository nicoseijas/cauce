import maplibregl, {
  ExpressionSpecification,
  GeoJSONSource,
  MapGeoJSONFeature,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { FlowLayer } from "./flow-layer";
import {
  aplicarFactores,
  antiguedadEstadoHoras,
  cargarEstado,
  cargarSeries,
  estadoVigente,
  estacionesComoGeoJSON,
  filasEstaciones,
  fuentesConProblemas,
  redondearHoras,
  type Estado,
  type FilaEstacion,
  type SeriePuntos,
} from "./estado";
import { setupCreciente } from "./creciente";
import { setupTabla } from "./tabla";
import { setupBuscador, type Entidad } from "./buscador";
import { montarPanelEstacion } from "./estacion";
import { pintarResumen } from "./resumen";
import {
  construirIndice,
  crearEnrutador,
  interpretar,
  recuperarRutaDiferida,
  resolver,
  urlAbsoluta,
} from "./rutas";

const BASE = import.meta.env.BASE_URL;

const NOMBRE_FUENTE: Record<string, string> = {
  dinagua_wfs: "DINAGUA",
  salto_grande: "Salto Grande",
  inumet_lluvia: "INUMET",
  inia_lluvia: "INIA",
  ina: "INA",
  ute_rio_negro: "UTE",
  ana: "ANA",
  sohma: "SOHMA",
};

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
    "HydroSHEDS/HydroRIVERS · DINAGUA e INUMET (Uruguay) · INIA · UTE · " +
    "Salto Grande (CTM) · SOHMA (Armada) · INA (Argentina) · ANA (Brasil)",
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

const acerca = document.getElementById("acerca") as HTMLDialogElement;
document.getElementById("btn-acerca")!.addEventListener("click", () => acerca.showModal());
document.getElementById("acerca-cerrar")!.addEventListener("click", () => acerca.close());
acerca.addEventListener("click", (e) => {
  if (e.target === acerca) acerca.close();
});

function formatoCaudal(q: number): string {
  if (q >= 100) return `${Math.round(q).toLocaleString("es-UY")} m³/s`;
  if (q >= 1) return `${q.toFixed(1)} m³/s`;
  return `${q.toFixed(2)} m³/s`;
}

function mostrarTooltip(f: MapGeoJSONFeature, x: number, y: number): void {
  const nombre = (f.properties.nombre as string) || "Curso sin nombre";
  const q = Number(f.properties.DIS_AV_CMS) || 0;
  // DIS_AV_CMS ya viene multiplicado por el factor del curso; el caudal de
  // referencia sin escalar es el que se puede citar como dato.
  const qMedio = Number(f.properties.DIS_MEDIO) || q;
  const factor = f.properties.factor as number | undefined;
  const fx = factor && factor >= 20 ? "≥20" : factor?.toFixed(1);
  const nacional = f.properties.q_medio_uy != null;
  const referencia = nacional ? "climatología DINAGUA" : "modelo HydroRIVERS";
  const tipoInsumo = String(f.properties.insumo_clasificacion ?? "sin clasificar");
  const horas = Number(f.properties.factor_horas);
  const edad = Number.isFinite(horas) ? ` · hace ${redondearHoras(horas)}` : "";
  const linea = factor
    ? `${fx}× su caudal de referencia<br>` +
      `<span class="q">referencia ${formatoCaudal(qMedio)} · ${referencia}</span>` +
      `<br><span class="aclara">Escala visual derivada de ${f.properties.estacion_factor}` +
      `${edad} (insumo ${tipoInsumo}). No es un caudal medido en este tramo.</span>`
    : `caudal medio de referencia ${formatoCaudal(q)} · ${referencia}`;
  tooltip.innerHTML = `<strong>${nombre}</strong><br><span class="q">${linea}</span>`;
  tooltip.style.display = "block";
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
}

/** Lo que el popup necesita, ya aplanado: llega de las propiedades del
 * feature del mapa o de una fila de la tabla. */
type EstacionPopup = {
  id?: number | string;
  slug?: string;
  nombre: string;
  curso?: string | null;
  clasificacion?: string | null;
  oficial?: boolean;
  nivel?: number | null;
  nivel_horas?: number | null;
  caudal?: number | null;
  caudal_horas?: number | null;
  alerta?: number | null;
  evacuacion?: number | null;
  fuente?: string;
  incertidumbre?: string;
  qc_estado?: string;
  qc_nivel_estado?: string;
  qc_nivel_codigos?: string;
  qc_caudal_estado?: string;
  qc_caudal_codigos?: string;
};

const ROTULO_QC: Record<string, string> = {
  fecha_futura: "fecha futura",
  fecha_retrocede: "la fecha retrocede respecto de la última referencia aceptada",
  fecha_ausente: "fecha ausente",
  fecha_invalida: "fecha inválida",
  valor_no_finito: "valor no numérico",
  fuera_rango_fisico: "fuera del rango físico operativo",
  cambio_brusco_no_verificado: "cambio brusco aún no verificado",
  revision_misma_fecha: "la fuente revisó el valor para la misma fecha",
  dato_vencido: "dato vencido",
};

function rotulosQC(codigos?: string): string {
  return (codigos ?? "").split(",").filter(Boolean)
    .map((c) => ROTULO_QC[c] ?? c.replaceAll("_", " ")).join("; ");
}

function lineaMedicion(
  variable: "nivel" | "caudal",
  valor: number,
  horas: number | null,
  estado?: string,
  codigos?: string,
): string {
  const medida = variable === "nivel"
    ? `nivel ${valor.toFixed(2)} m`
    : `caudal ${formatoCaudal(valor)}`;
  if (estado === "rechazado") {
    return `<span class="alerta">${medida} informado por la fuente — rechazado QC</span>` +
      `<span class="aclara">${rotulosQC(codigos)}. Se conserva para auditoría, ` +
      `pero no se usa en cálculos ni alertas.</span>`;
  }
  if (estado === "dudoso") {
    return `<span style="color:#e8c95a">${medida} — en revisión QC</span>` +
      `<span class="aclara">${rotulosQC(codigos)}. No se usa en resultados derivados.</span>`;
  }
  if (estado === "vencido") {
    return `${medida} · <span class="q">vencido, hace ${redondearHoras(horas)}</span>`;
  }
  return `${medida} · hace ${redondearHoras(horas)}`;
}

/** El popup decide si vale la pena profundizar, no resuelve la estación.
 * Todo lo que quedaba fuera —umbrales, procedencia, escala local, calidad—
 * vive en la ficha, que tiene sitio para explicarlo. */
function popupEstacion(e: EstacionPopup): string {
  const filas: string[] = [`<strong>${e.nombre}</strong>`];
  if (e.curso) filas.push(`<span class="q">${e.curso}</span>`);

  if (e.nivel != null) {
    filas.push(lineaMedicion(
      "nivel", Number(e.nivel), e.nivel_horas ?? null,
      e.qc_nivel_estado, e.qc_nivel_codigos,
    ));
  } else if (e.caudal != null) {
    filas.push(lineaMedicion(
      "caudal", Number(e.caudal), e.caudal_horas ?? null,
      e.qc_caudal_estado, e.qc_caudal_codigos,
    ));
  } else {
    filas.push("sin datos recientes");
  }

  const nivelApto = e.qc_nivel_estado == null || e.qc_nivel_estado === "ok";
  if (e.alerta != null && e.nivel != null && nivelApto) {
    if (e.evacuacion != null && e.nivel >= e.evacuacion) {
      filas.push(`<span class="alerta">⚠ nivel de evacuación superado</span>`);
    } else if (e.nivel >= e.alerta) {
      filas.push(`<span class="alerta">⚠ nivel de alerta superado</span>`);
    }
  }

  if (e.slug) {
    filas.push(
      `<button type="button" class="ver-estacion" data-slug="${e.slug}">Ver estación →</button>` +
      `<button type="button" class="copiar-enlace" ` +
      `data-enlace="${urlAbsoluta({ vista: "estacion", slug: e.slug })}">Copiar enlace</button>`,
    );
  }
  return filas.join("<br>");
}

// El popup reescribe su HTML cuando llega el minigráfico, así que el clic se
// atiende por delegación en lugar de sobre el botón concreto.
addEventListener("click", (ev) => {
  const verEstacion = (ev.target as HTMLElement | null)?.closest<HTMLElement>(".ver-estacion");
  if (verEstacion?.dataset.slug) {
    irAEstacion(verEstacion.dataset.slug);
    return;
  }
  const boton = (ev.target as HTMLElement | null)?.closest<HTMLButtonElement>(
    ".copiar-enlace",
  );
  const enlace = boton?.dataset.enlace;
  if (!boton || !enlace) return;
  const original = boton.textContent;
  navigator.clipboard.writeText(enlace).then(
    () => { boton.textContent = "Enlace copiado"; },
    () => { boton.textContent = enlace; },
  ).finally(() => {
    setTimeout(() => { boton.textContent = original; }, 2500);
  });
});

/** Navega a una estación por su slug. Queda definida cuando hay estado
 * cargado; sin él el mapa sigue funcionando sin rutas por estación. */
let irAEstacion: (slug: string) => void = () => {};

/** Popup de estación abierto, para no apilar uno sobre otro al navegar. */
let popupAbierto: maplibregl.Popup | null = null;

/** Abre el popup y, cuando la serie llega, le agrega el minigráfico. */
async function abrirPopupEstacion(
  donde: maplibregl.LngLatLike,
  props: EstacionPopup,
  alCerrar?: () => void,
): Promise<void> {
  popupAbierto?.remove();
  const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "260px" })
    .setLngLat(donde)
    .setHTML(popupEstacion(props))
    .addTo(map);
  popupAbierto = popup;
  popup.on("close", () => {
    if (popupAbierto === popup) popupAbierto = null;
    alCerrar?.();
  });
  const series = await cargarSeries(`${BASE}data/series.json`);
  const serie = series?.estaciones[String(props.id)];
  if (!serie || !popup.isOpen()) return;
  const grafico = miniGrafico(serie);
  if (grafico) popup.setHTML(popupEstacion(props) + grafico);
}

function popupDesdeFila(f: FilaEstacion): EstacionPopup {
  return {
    id: f.id,
    slug: f.slug,
    nombre: f.nombre,
    curso: f.curso,
    clasificacion: f.clasificacion,
    nivel: f.nivel,
    nivel_horas: f.nivel_horas,
    caudal: f.caudal,
    caudal_horas: f.caudal_horas,
    alerta: f.alerta,
    evacuacion: f.evacuacion,
    fuente: f.fuente,
    qc_nivel_estado: f.qc_nivel?.estado,
    qc_nivel_codigos: f.qc_nivel?.codigos.join(","),
    qc_caudal_estado: f.qc_caudal?.estado,
    qc_caudal_codigos: f.qc_caudal?.codigos.join(","),
  };
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
      filas.push(
        `suelta al río ${formatoCaudal(est.caudal)} · hace ` +
        `${redondearHoras(est.caudal_horas)}`);
      if (est.factor) {
        filas.push(`${est.factor >= 20 ? "≥20" : est.factor.toFixed(1)}× su caudal medio`);
      }
    }
    const sg = estado?.salto_grande;
    if (sg?.turbinado != null && sg.vertido != null) {
      filas.push(
        `<span class="q">turbinado ${formatoCaudal(sg.turbinado)} · ` +
        `vertido ${formatoCaudal(sg.vertido)}</span>` +
        `<span class="aclara">El turbinado pasa por las turbinas y genera ` +
        `energía; el vertido pasa por el vertedero.</span>`);
    }
  } else if (clave === "bonete" || clave === "palmar") {
    const erogado = clave === "bonete" ? hoy?.erogado_bonete : hoy?.erogado_palmar;
    if (erogado) {
      filas.push(
        `suelta prevista para hoy ${formatoCaudal(erogado)} ` +
        `<span class="q">(pronóstico oficial UTE)</span>` +
        `<span class="aclara">Pronóstico determinista dentro de un horizonte ` +
        `de 7 días; UTE no publica probabilidad ni incertidumbre.</span>`,
      );
    }
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
    `<polyline points="${linea}" fill="none" stroke="#6ea8d8" stroke-width="1.5"/>` +
    `<circle cx="${x(tf).toFixed(1)}" cy="${y(vf).toFixed(1)}" r="2.2" fill="#7ef0d8"/>` +
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
    const titulo = document.getElementById("leyenda-titulo");
    if (titulo) titulo.textContent = anomalia ? "Respecto a lo habitual" : "Caudal de referencia";
  }
  btnCaudal.addEventListener("click", () => activar(false));
  btnAnomalia.addEventListener("click", () => activar(true));
}

map.on("load", async () => {
  const [fc, estadoCargado] = await Promise.all([
    fetch(`${BASE}data/red_uy.geojson`).then((r) => r.json()),
    cargarEstado(`${BASE}data/estado_actual.json`),
  ]);

  document.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");

  const estadoEl = document.getElementById("titulo-estado")!;
  const vigente = estadoCargado ? estadoVigente(estadoCargado) : false;
  const estado = vigente ? estadoCargado : null;
  if (estado) {
    const problemas = fuentesConProblemas(estado);
    const incidenciasQc = estado.control_calidad?.incidencias ?? [];

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
        // El color del mapa comunica estado del río. La antigüedad del dato se
        // distingue por relleno y opacidad para no leerse como «precaución».
        "circle-color": [
          "case",
          ["==", ["get", "qc_estado"], "rechazado"], "#ff4d4d",
          ["==", ["get", "qc_estado"], "dudoso"], "#e8c95a",
          ["step", ["get", "frescura"], "#cfe0ee", 24, "#16324a"],
        ],
        "circle-stroke-opacity": ["step", ["get", "frescura"], 1, 24, 0.75],
        "circle-stroke-color": ["step", ["get", "frescura"], "#0b141d", 24, "#8fa8bd"],
        "circle-stroke-width": ["step", ["get", "frescura"], 1, 24, 1.4],
        "circle-opacity": 0.9,
      },
    });
    map.on("click", "estaciones", (ev) => {
      // si hay una represa bajo el cursor, gana su popup
      if (map.queryRenderedFeatures(ev.point, { layers: ["represas"] }).length) return;
      const f = ev.features?.[0];
      if (!f) return;
      void abrirPopupEstacion(ev.lngLat, f.properties as unknown as EstacionPopup);
    });
    map.on("mouseenter", "estaciones", () => {
      map.getCanvas().style.cursor = "pointer";
    });

    const fecha = new Date(estado.generado);
    const factores = Object.values(estado.factores_curso);
    const observados = factores.filter((f) => f.insumo_clasificacion === "observado").length;
    const pronosticados = factores.filter((f) => f.insumo_clasificacion === "pronosticado").length;
    const mezcla = [
      observados ? `${observados} desde observación` : "",
      pronosticados ? `${pronosticados} desde pronóstico` : "",
    ].filter(Boolean).join("; ");
    const caidas = problemas.map((k) => NOMBRE_FUENTE[k] ?? k).join(", ");
    const mensajeQc = incidenciasQc.length
      ? `QC: ${incidenciasQc.length} observación${incidenciasQc.length > 1 ? "es" : ""} ` +
        `${incidenciasQc.length > 1 ? "dudosas/rechazadas" : "dudosa o rechazada"}. `
      : "";
    const diagnostico = document.getElementById("diagnostico");
    if (diagnostico) {
      diagnostico.textContent =
        `${problemas.length ? `Sin dato apto de ${caidas}. ` : ""}` +
        mensajeQc +
        `${tocados} tramos con escala estimada (${mezcla || "sin insumos aptos"}) · ` +
        `generado ${fecha.toLocaleString("es-UY", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}`;
    }
  } else if (estadoCargado) {
    const fecha = new Date(estadoCargado.generado);
    const horas = antiguedadEstadoHoras(estadoCargado);
    estadoEl.textContent =
      `Estado sin actualizar${horas == null ? "" : ` desde hace ${redondearHoras(horas)}`}` +
      ` (${fecha.toLocaleString("es-UY")}). Se muestra solo la climatología; ` +
      `no se evalúa inundación actual.`;
    estadoEl.className = "advertencia";
  } else {
    estadoEl.textContent =
      "Sin archivo de estado disponible. Se muestra solo la climatología; no se evalúa inundación actual.";
    estadoEl.className = "advertencia";
  }

  const flow = new FlowLayer(fc);
  map.addLayer(flow, "rios-hover");
  crearCapaRepresas(map, estado);
  setupCreciente(map, BASE, estadoCargado ?? undefined, vigente);
  if (estadoCargado) {
    const filas = filasEstaciones(estadoCargado);
    const resumen = document.getElementById("resumen");
    if (resumen) pintarResumen(resumen, estadoCargado, filas);
    const indice = construirIndice(filas);
    const porSlug = new Map(filas.map((f) => [f.slug, f]));

    const panel = document.getElementById("estacion")!;
    let slugAbierto: string | null = null;
    // El catálogo alimenta el bloque de procedencia; llega diferido porque solo
    // hace falta al abrir una estación.
    let catalogo: Promise<Record<string, unknown> | null> | null = null;

    const mostrar = (fila: FilaEstacion) => {
      slugAbierto = fila.slug;
      popupAbierto?.remove();
      map.flyTo({
        center: [fila.lon, fila.lat],
        zoom: Math.max(map.getZoom(), 9),
        padding: { left: panel.offsetWidth, top: 0, right: 0, bottom: 0 },
      });
      catalogo ??= fetch(`${BASE}data/datapackage.json`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      void Promise.all([cargarSeries(`${BASE}data/series.json`), catalogo])
        .then(([series, cat]) => {
          if (slugAbierto !== fila.slug) return;
          panel.hidden = false;
          montarPanelEstacion({
            contenedor: panel,
            fila,
            estado: estadoCargado,
            series,
            catalogo: cat as never,
            alCerrar: () => enrutador.ir({ vista: "mapa" }),
          });
        });
    };

    const ocultarPanel = () => {
      slugAbierto = null;
      panel.hidden = true;
      panel.innerHTML = "";
    };

    const enrutador = crearEnrutador((ruta) => {
      if (ruta.vista === "mapa") {
        ocultarPanel();
        return;
      }
      const canonico = resolver(indice, ruta.slug);
      const fila = canonico ? porSlug.get(canonico) : undefined;
      if (!fila) {
        enrutador.sustituir({ vista: "mapa" });
        return;
      }
      if (canonico !== ruta.slug) enrutador.sustituir({ vista: "estacion", slug: canonico! });
      if (slugAbierto !== fila.slug) mostrar(fila);
    });
    irAEstacion = (slug) => enrutador.ir({ vista: "estacion", slug });

    setupTabla(estadoCargado, BASE, vigente, filas, (fila) => irAEstacion(fila.slug));

    // Una estación tiene URL propia; el resto de las entidades todavía no,
    // así que el buscador las resuelve encuadrando el mapa.
    const buscar = document.getElementById("buscar") as HTMLInputElement | null;
    const resultados = document.getElementById("buscar-resultados");
    if (buscar && resultados) {
      setupBuscador({
        entrada: buscar,
        panel: resultados,
        urlIndice: `${BASE}data/buscador.json`,
        alElegir: (entidad: Entidad) => {
          if (entidad.tipo === "estacion" && entidad.slug) {
            irAEstacion(entidad.slug);
            return;
          }
          if (entidad.bbox) {
            const [oeste, sur, este, norte] = entidad.bbox;
            map.fitBounds([[oeste, sur], [este, norte]], { padding: 60, maxZoom: 11 });
            return;
          }
          const zoom = entidad.tipo === "departamento" ? 8 : 11;
          map.flyTo({ center: [entidad.lon, entidad.lat], zoom });
        },
      });
    }

    recuperarRutaDiferida();
    const inicial = interpretar();
    if (inicial.vista === "estacion") enrutador.sustituir(inicial);
  }
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
