import maplibregl, { Map } from "maplibre-gl";

const CAPAS_TR = ["inund-tr-fill", "inund-tr-line"];

let cargado = false;
let escenario = 100;

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

  const popup = (html: string, lngLat: maplibregl.LngLat) =>
    new maplibregl.Popup({ closeButton: false, maxWidth: "280px" })
      .setLngLat(lngLat).setHTML(html).addTo(map);

  map.on("click", "inund-tr-fill", (e) => {
    const p = e.features?.[0]?.properties;
    if (!p) return;
    popup(
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

export function setupCreciente(map: Map, base: string): void {
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
    }
    if (!cargado) return;
    const capas = [...CAPAS_TR];
    if ((document.getElementById("chk-cri") as HTMLInputElement).checked) capas.push("inund-cri");
    if ((document.getElementById("chk-dre") as HTMLInputElement).checked) capas.push("drenaje-fill");
    for (const id of ["inund-tr-fill", "inund-tr-line", "inund-cri", "drenaje-fill"]) {
      if (map.getLayer(id)) visibilidad(map, id, activo && (capas.includes(id) || CAPAS_TR.includes(id)));
    }
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
