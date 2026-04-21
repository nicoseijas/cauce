import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { FlowLayer } from "./flow-layer";

const BASE = import.meta.env.BASE_URL;

const map = new maplibregl.Map({
  container: "map",
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
        id: "rios",
        type: "line",
        source: "red",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": [
            "interpolate", ["linear"],
            ["ln", ["+", 1, ["coalesce", ["get", "DIS_AV_CMS"], 0]]],
            0, "#1d4460",
            4, "#2e6f9e",
            8, "#57a8d8",
          ],
          "line-width": [
            "interpolate", ["exponential", 1.6], ["zoom"],
            5, ["interpolate", ["linear"],
              ["ln", ["+", 1, ["coalesce", ["get", "DIS_AV_CMS"], 0]]],
              0, 0.3, 4, 1.2, 8, 3.5],
            12, ["interpolate", ["linear"],
              ["ln", ["+", 1, ["coalesce", ["get", "DIS_AV_CMS"], 0]]],
              0, 1.5, 4, 6, 8, 18],
          ],
          "line-opacity": 0.9,
        },
      },
    ],
  },
});

map.addControl(new maplibregl.AttributionControl({
  customAttribution:
    "HydroSHEDS/HydroRIVERS · DINAGUA (Min. Ambiente, Uruguay)",
}), "bottom-right");

const hud = document.getElementById("hud")!;

map.on("load", async () => {
  const res = await fetch(`${BASE}data/red_uy.geojson`);
  const fc = await res.json();
  const flow = new FlowLayer(fc);
  map.addLayer(flow);

  let frames = 0;
  let last = performance.now();
  function tick() {
    frames++;
    const now = performance.now();
    if (now - last >= 1000) {
      hud.textContent =
        `${frames} fps · ${flow.particleCount().toLocaleString("es-UY")} partículas · ` +
        `${fc.features.length.toLocaleString("es-UY")} tramos`;
      frames = 0;
      last = now;
    }
    requestAnimationFrame(tick);
  }
  tick();
});
