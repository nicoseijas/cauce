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
  estacionesComoGeoJSON,
  type EstacionEstado,
} from "./estado";
import { setupCreciente } from "./creciente";

const BASE = import.meta.env.BASE_URL;

const ESCALA_LOG_Q: ExpressionSpecification = [
  "ln", ["+", 1, ["coalesce", ["get", "DIS_AV_CMS"], 0]],
];

const map = new maplibregl.Map({
  container: "map",
  hash: true,
  center: [-56.0, -32.7],
  zoom: 6.3,
  minZoom: 5,
  maxZoom: 13,
  attributionControl: false,
  style: {
    version: 8,
    sources: {
      departamentos: { type: "geojson", data: `${BASE}data/departamentos_uy.geojson` },
      red: { type: "geojson", data: `${BASE}data/red_uy.geojson` },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b141d" } },
      {
        id: "tierra",
        type: "fill",
        source: "departamentos",
        paint: { "fill-color": "#16222e" },
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
          "line-opacity": [
            "interpolate", ["linear"], ESCALA_LOG_Q,
            3.5, 0, 5.5, 0.10, 8, 0.28,
          ],
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
          "line-color": [
            "interpolate", ["linear"], ESCALA_LOG_Q,
            0, "#1d4460",
            4, "#2e6f9e",
            8, "#57a8d8",
          ],
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
    ],
  },
});

map.addControl(new maplibregl.AttributionControl({
  compact: true,
  customAttribution:
    "HydroSHEDS/HydroRIVERS · DINAGUA (Min. Ambiente, Uruguay)",
}), "bottom-right");

const tooltip = document.getElementById("tooltip")!;
const fpsEl = document.getElementById("fps")!;

function formatoCaudal(q: number): string {
  if (q >= 100) return `${Math.round(q).toLocaleString("es-UY")} m³/s`;
  if (q >= 1) return `${q.toFixed(1)} m³/s`;
  return `${q.toFixed(2)} m³/s`;
}

function mostrarTooltip(f: MapGeoJSONFeature, x: number, y: number): void {
  const nombre = (f.properties.nombre as string) || "Curso sin nombre";
  const q = Number(f.properties.DIS_AV_CMS) || 0;
  const factor = f.properties.factor as number | undefined;
  const linea = factor
    ? `caudal actual ≈ ${formatoCaudal(q)} (${factor.toFixed(1)}× la media` +
      `, est. ${f.properties.estacion_factor})`
    : `caudal medio ${formatoCaudal(q)} (estimado)`;
  tooltip.innerHTML = `<strong>${nombre}</strong><br><span class="q">${linea}</span>`;
  tooltip.style.display = "block";
  tooltip.style.left = `${x + 14}px`;
  tooltip.style.top = `${y + 14}px`;
}

function popupEstacion(e: EstacionEstado): string {
  const filas: string[] = [`<strong>${e.nombre}</strong>`];
  if (e.curso) filas.push(`<span class="q">${e.curso}</span>`);
  if (e.nivel != null) {
    filas.push(`nivel ${e.nivel.toFixed(2)} m · hace ${redondearHoras(e.nivel_horas)}`);
  }
  if (e.caudal != null) {
    filas.push(`caudal ${formatoCaudal(e.caudal)} · hace ${redondearHoras(e.caudal_horas)}`);
  }
  if (e.nivel == null && e.caudal == null) filas.push("sin datos recientes");
  return filas.join("<br>");
}

function redondearHoras(h: number | null): string {
  if (h == null) return "—";
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} días`;
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

map.on("load", async () => {
  const [fc, estado] = await Promise.all([
    fetch(`${BASE}data/red_uy.geojson`).then((r) => r.json()),
    cargarEstado(`${BASE}data/estado_actual.json`),
  ]);

  const estadoEl = document.querySelector("#titulo p")!;
  if (estado) {
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
    map.on("click", "estaciones", (ev) => {
      const f = ev.features?.[0];
      if (!f) return;
      new maplibregl.Popup({ closeButton: false, maxWidth: "260px" })
        .setLngLat(ev.lngLat)
        .setHTML(popupEstacion(f.properties as unknown as EstacionEstado))
        .addTo(map);
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
  setupCreciente(map, BASE);

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
