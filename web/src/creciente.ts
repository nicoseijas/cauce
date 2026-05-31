import maplibregl, { ExpressionSpecification, Map } from "maplibre-gl";
import type { ActivacionLocalidad } from "./estado";

const CAPAS_TR = ["inund-tr-fill", "inund-tr-line"];

let cargado = false;
let escenario = 100;
let activacion: Record<string, ActivacionLocalidad> = {};

function nombrePeriodo(p: number): string {
  return p >= 9999 ? "CMP" : `${p} años`;
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

function resumenActivacion(): string {
  const activas = Object.entries(activacion).filter(([, a]) => a.periodo_activo > 0);
  if (activas.length) {
    return activas
      .map(([, a]) =>
        `<span class="alerta">⚠ ${a.estacion}: superada la mancha de ` +
        `${nombrePeriodo(a.periodo_activo)} (nivel ${a.nivel.toFixed(2)} m)</span>`)
      .join("<br>");
  }
  const proximos = Object.values(activacion)
    .filter((a) => a.proximo)
    .sort((x, y) => x.proximo!.faltan_m - y.proximo!.faltan_m)
    .slice(0, 2);
  if (!proximos.length) return "Sin niveles frescos para evaluar activación.";
  const lineas = proximos.map((a) =>
    `${a.estacion}: a ${a.proximo!.faltan_m.toFixed(2).replace(".", ",")} m de su ` +
    `mancha de ${nombrePeriodo(a.proximo!.periodo)}`);
  return `Ninguna mancha superada ahora.<br>${lineas.join("<br>")}`;
}

async function cargarCapas(map: Map, base: string): Promise<void> {
  const [tr, cri, dre] = await Promise.all([
    fetch(`${base}data/inundacion_tr.geojson`).then((r) => r.json()),
    fetch(`${base}data/inundacion_cri.geojson`).then((r) => r.json()),
    fetch(`${base}data/drenaje.geojson`).then((r) => r.json()),
  ]);
  map.addSource("inund-tr", { type: "geojson", data: tr });
  map.addSource("inund-cri", { type: "geojson", data: cri });
  map.addSource("drenaje", { type: "geojson", data: dre });

  map.addLayer({
    id: "inund-tr-fill",
    type: "fill",
    source: "inund-tr",
    paint: {
      "fill-color": [
        "step", ["get", "periodo"],
        "#e05c5c", 11, "#e08a5c", 101, "#e0b95c",
      ],
      "fill-opacity": 0.3,
    },
  }, "rios-glow");
  map.addLayer({
    id: "inund-tr-line",
    type: "line",
    source: "inund-tr",
    paint: { "line-color": "#e05c5c", "line-width": 0.8, "line-opacity": 0.7 },
  }, "rios-glow");
  map.addLayer({
    id: "inund-cri",
    type: "line",
    source: "inund-cri",
    layout: { visibility: "none" },
    paint: {
      "line-color": "#c08bf0",
      "line-width": 1.6,
      "line-dasharray": [2, 1.5],
      "line-opacity": 0.9,
    },
  }, "rios-glow");
  map.addLayer({
    id: "drenaje-fill",
    type: "fill",
    source: "drenaje",
    layout: { visibility: "none" },
    paint: { "fill-color": "#e0a45c", "fill-opacity": 0.25 },
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

  map.on("click", "inund-tr-fill", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    const a = activacion[p.localidad_cod as string];
    const activa = a && a.periodo_activo >= Number(p.periodo);
    const cabecera = activa
      ? `<span class="alerta">⚠ ACTIVA AHORA</span> — nivel ${a.nivel.toFixed(2)} m en ${a.estacion}<br>`
      : "";
    popup(
      cabecera +
      `<strong>Mancha de inundación · ${p.tipo_curva}</strong><br>` +
      `${p.curso ?? ""}${p.cota_oficial ? ` · cota ${p.cota_oficial} m` : ""}<br>` +
      `<span style="color:#8fa8bd">${String(p.fuentes ?? "").slice(0, 120)}</span>`,
      e.lngLat,
    );
  });
  map.on("click", "inund-cri", (e) => {
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
  const visibles: Record<string, boolean> = {
    "inund-tr-fill": activo,
    "inund-tr-line": activo,
    "inund-activa": activo,
    "inund-activa-line": activo,
    "inund-cri": activo && conCri,
    "drenaje-fill": activo && conDre,
  };
  for (const [id, on] of Object.entries(visibles)) {
    if (map.getLayer(id)) visibilidad(map, id, on);
  }
}

export function setupCreciente(
  map: Map,
  base: string,
  act?: Record<string, ActivacionLocalidad>,
): void {
  activacion = act ?? {};
  const panel = document.getElementById("creciente")!;
  const toggle = document.getElementById("creciente-toggle")!;
  const opciones = document.getElementById("creciente-opciones")!;

  toggle.addEventListener("click", async () => {
    const activo = panel.classList.toggle("activo");
    opciones.style.display = activo ? "block" : "none";
    if (activo && !cargado) {
      cargado = true;
      toggle.textContent = "Cargando…";
      await cargarCapas(map, base);
      toggle.textContent = "Modo creciente";
      aplicarEscenario(map);
      document.getElementById("creciente-estado")!.innerHTML = resumenActivacion();
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
  (document.getElementById("chk-cri") as HTMLInputElement).addEventListener("change", (ev) => {
    if (cargado) visibilidad(map, "inund-cri", (ev.target as HTMLInputElement).checked);
  });
  (document.getElementById("chk-dre") as HTMLInputElement).addEventListener("change", (ev) => {
    if (cargado) visibilidad(map, "drenaje-fill", (ev.target as HTMLInputElement).checked);
  });
}
