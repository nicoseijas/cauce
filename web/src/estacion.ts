/** Panel de estación: el destino al que lleva un enlace permanente.
 *
 * Ordena la información en tres densidades: primero qué está pasando en
 * lenguaje corriente, después las cifras, y al final de dónde salió cada una.
 * Nada se completa con valores inventados: un bloque sin datos se omite o
 * dice qué falta.
 */

import {
  redondearHoras,
  type Estado,
  type FilaEstacion,
  type ResultadoQC,
  type Series,
} from "./estado";
import { formatearValor, montarGrafico, type Punto } from "./grafico";
import { urlAbsoluta } from "./rutas";

/** Clave de la estación en el catálogo de fuentes, según su organismo. */
const FUENTE_DE_ORGANISMO: Record<string, string> = {
  dinagua: "dinagua_wfs",
  ina: "ina",
  ana: "ana",
  sohma: "sohma",
  ctm: "salto_grande",
  ute: "ute",
};

const ROTULO_FRESCURA: Record<string, { texto: string; clase: string }> = {
  ok: { texto: "dato reciente", clase: "ok" },
  vencido: { texto: "dato antiguo", clase: "vencido" },
  dudoso: { texto: "dato en revisión", clase: "dudoso" },
  rechazado: { texto: "dato excluido", clase: "rechazado" },
  sin_dato: { texto: "sin dato", clase: "vencido" },
};

type Fuente = {
  id?: string;
  title?: string;
  authority?: string;
  url?: string;
  license?: string;
  access?: string;
  notes?: string;
};

/** En datapackage.json las fuentes son una lista con `id`, no un diccionario. */
type Catalogo = { sources?: Fuente[]; spatial_conventions?: { vertical_reference?: string } };

function fuenteDe(catalogo: Catalogo | null, organismo: string): Fuente | undefined {
  const clave = FUENTE_DE_ORGANISMO[organismo];
  return clave ? catalogo?.sources?.find((f) => f.id === clave) : undefined;
}

function escapar(t: string): string {
  return t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

function fechaLegible(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("es-UY", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/** Variación en las últimas `horas`, medida entre las observaciones reales más
 * cercanas a los extremos. Devuelve null si la serie no cubre el período. */
export function variacion(puntos: Punto[], horas: number): { delta: number; lapso: number } | null {
  if (puntos.length < 2) return null;
  const ultimo = puntos[puntos.length - 1];
  const objetivo = ultimo[0] - horas * 3600;
  const previos = puntos.filter(([t]) => t <= objetivo);
  // Sin observación anterior al corte, informar el cambio sería atribuirle un
  // período que la serie no cubre.
  if (!previos.length) return null;
  const referencia = previos[previos.length - 1];
  return { delta: ultimo[1] - referencia[1], lapso: (ultimo[0] - referencia[0]) / 3600 };
}

function bloque(titulo: string, cuerpo: string, clase = ""): string {
  if (!cuerpo) return "";
  return `<section class="bloque ${clase}"><h3>${escapar(titulo)}</h3>${cuerpo}</section>`;
}

function dato(rotulo: string, valor: string, nota = ""): string {
  return `<div class="dato"><span class="rot">${escapar(rotulo)}</span>` +
    `<span class="val">${valor}</span>` +
    (nota ? `<span class="nota">${nota}</span>` : "") + `</div>`;
}

function chipQC(qc: ResultadoQC | null | undefined): string {
  const info = ROTULO_FRESCURA[qc?.estado ?? "sin_dato"];
  return `<span class="chip ${info.clase}">${info.texto}</span>`;
}

function bloqueIdentidad(f: FilaEstacion, estado: Estado): string {
  const peor = [f.qc_nivel, f.qc_caudal].find((q) => q?.estado === "rechazado")
    ?? [f.qc_nivel, f.qc_caudal].find((q) => q?.estado === "dudoso")
    ?? f.qc_nivel ?? f.qc_caudal ?? null;
  const [organismo, ...resto] = f.estacion_id.split("-");
  const observacion = fechaLegible(f.nivel_fecha ?? f.caudal_fecha);
  return (
    `<header class="identidad">` +
    `<h2>${escapar(f.nombre)}</h2>` +
    (f.curso ? `<p class="curso">${escapar(f.curso)}</p>` : "") +
    `<p class="origen">${escapar(f.fuente)} · estación ${escapar(resto.join("-"))}` +
    `<span class="q"> (${escapar(organismo)})</span></p>` +
    `<p class="frescura">${chipQC(peor)}` +
    (observacion ? `<span class="q">última observación ${escapar(observacion)}</span>` : "") +
    `</p>` +
    `<p class="coords q">${f.lat.toFixed(5)}, ${f.lon.toFixed(5)}` +
    (estado.generado ? ` · estado generado ${escapar(fechaLegible(estado.generado) ?? "")}` : "") +
    `</p></header>`
  );
}

function bloqueAhora(f: FilaEstacion, serieNivel: Punto[]): string {
  const filas: string[] = [];
  if (f.nivel != null) {
    filas.push(dato("Nivel", `${formatearValor(f.nivel, "m")} <em>m</em>`,
      f.nivel_horas != null ? `hace ${redondearHoras(f.nivel_horas)}` : ""));
  }
  const cambio = variacion(serieNivel, 24);
  if (cambio) {
    const cm = cambio.delta * 100;
    const flecha = Math.abs(cm) < 1 ? "→" : cm > 0 ? "↑" : "↓";
    filas.push(dato("Cambio de nivel", `${flecha} ${cm > 0 ? "+" : ""}${cm.toFixed(0)} <em>cm</em>`,
      `en ${cambio.lapso.toFixed(0)} h`));
  }
  if (f.caudal != null) {
    filas.push(dato("Caudal", `${formatearValor(f.caudal, "m³/s")} <em>m³/s</em>`,
      f.caudal_horas != null ? `hace ${redondearHoras(f.caudal_horas)}` : ""));
  }
  if (f.factor != null && f.q_medio) {
    filas.push(dato("Respecto a su referencia", `${f.factor.toFixed(2)}×`,
      `media ${formatearValor(f.q_medio, "m³/s")} m³/s`));
  }
  if (!filas.length) return bloque("Ahora", `<p class="vacio">Esta estación no publica observaciones vigentes.</p>`);
  return bloque("Ahora", `<div class="datos">${filas.join("")}</div>`);
}

function bloqueInterpretacion(f: FilaEstacion, serieNivel: Punto[]): string {
  const cambio = variacion(serieNivel, 24);
  const observado: string[] = [];
  const interpretacion: string[] = [];

  if (cambio) {
    const cm = cambio.delta * 100;
    observado.push(`Nivel ${cm > 0 ? "+" : ""}${cm.toFixed(0)} cm en ${cambio.lapso.toFixed(0)} h`);
    interpretacion.push(
      Math.abs(cm) < 1
        ? "Sin variación apreciable durante el período observado."
        : `Tendencia ${cm > 0 ? "ascendente" : "descendente"} durante el período observado.`,
    );
  }
  if (f.factor != null) {
    observado.push(`Caudal ${f.factor.toFixed(2)}× su caudal medio de referencia`);
    interpretacion.push(
      f.factor >= 1.5 ? "El caudal está por encima de lo habitual para esta estación."
      : f.factor <= 0.6 ? "El caudal está por debajo de lo habitual para esta estación."
      : "El caudal está dentro de valores habituales para esta estación.",
    );
  }
  if (!observado.length) return "";
  return bloque("Interpretación",
    `<div class="par"><p class="etq">Observado</p><ul>${
      observado.map((o) => `<li>${escapar(o)}</li>`).join("")}</ul></div>` +
    `<div class="par"><p class="etq">Interpretación</p><ul>${
      interpretacion.map((i) => `<li>${escapar(i)}</li>`).join("")}</ul></div>` +
    `<p class="aclara">La referencia es la climatología regionalizada de DINAGUA ` +
    `(1980–2010), no una media medida en esta estación.</p>`);
}

function bloqueUmbrales(f: FilaEstacion): string {
  if (f.alerta == null || f.nivel == null) return "";
  const filas = [dato("Nivel observado", `${formatearValor(f.nivel, "m")} <em>m</em>`)];
  for (const [rotulo, valor] of [["Alerta", f.alerta], ["Evacuación", f.evacuacion]] as const) {
    if (valor == null) continue;
    const falta = valor - f.nivel;
    filas.push(dato(rotulo, `${formatearValor(valor, "m")} <em>m</em>`,
      falta > 0 ? `faltan ${falta.toFixed(2)} m` : `superado por ${(-falta).toFixed(2)} m`));
  }
  return bloque("Umbrales publicados por la fuente",
    `<div class="datos">${filas.join("")}</div>` +
    `<p class="aclara">Umbrales del organismo que opera la estación, en su escala local. ` +
    `No son altura sobre el mar ni se comparan con los de otra estación.</p>`);
}

function bloqueCalidad(f: FilaEstacion, estado: Estado, puntos: number, ventana: number): string {
  const filas: string[] = [];
  for (const [rotulo, qc] of [["Nivel", f.qc_nivel], ["Caudal", f.qc_caudal]] as const) {
    if (!qc) continue;
    filas.push(dato(rotulo, chipQC(qc),
      qc.codigos.length ? escapar(qc.codigos.join(", "))
        : `apto para derivados: ${qc.apto_derivados ? "sí" : "no"}`));
  }
  const controles = f.qc_nivel?.controles ?? f.qc_caudal?.controles ?? [];
  const vigilancia = f.qc_nivel?.vigilancia ?? f.qc_caudal?.vigilancia;
  return bloque("Calidad y cobertura",
    `<div class="datos">${filas.join("")}</div>` +
    `<div class="datos">` +
    dato("Observaciones acumuladas", String(puntos), `ventana de ${ventana} días`) +
    (controles.length ? dato("Controles aplicados", String(controles.length),
      escapar(controles.join(", "))) : "") +
    `</div>` +
    (vigilancia ? `<p class="aviso">⚠ ${escapar(vigilancia)}</p>` : "") +
    `<p class="aclara">Cauce no corrige, interpola ni cambia el datum de ninguna lectura: ` +
    `marca su aptitud y conserva el valor de origen. ` +
    escapar(estado.control_calidad?.metodo.limitacion ?? "") + `.</p>`);
}

function bloqueHistorico(puntos: number, ventana: number): string {
  return bloque("Contexto histórico",
    `<p class="vacio">Todavía no se puede decir si este valor es habitual para la época del año. ` +
    `Cauce acumula ${puntos} observación${puntos === 1 ? "" : "es"} de esta estación, pero en una ` +
    `ventana de ${ventana} días: para comparar un agosto con otros agostos hacen falta años, ` +
    `no semanas.</p>` +
    `<p class="aclara">Las mediciones históricas 2017–2019 de DINAGUA están identificadas ` +
    `y verificadas, pero aún no publicadas como serie.</p>`, "pendiente");
}

function bloqueProcedencia(f: FilaEstacion, catalogo: Catalogo | null): string {
  const fuente = fuenteDe(catalogo, f.estacion_id.split("-")[0]);
  const filas = [
    dato("Organismo", escapar(fuente?.authority ?? f.fuente)),
    dato("Identificador de origen", escapar(f.estacion_id.split("-").slice(1).join("-"))),
    dato("Identificador en Cauce", escapar(f.estacion_id)),
    dato("Clasificación del dato", escapar(f.clasificacion ?? "observado")),
  ];
  if (fuente?.access) filas.push(dato("Acceso", escapar(fuente.access)));
  filas.push(dato("Licencia", escapar(fuente?.license ?? "no declarada por la fuente")));
  const vertical = catalogo?.spatial_conventions?.vertical_reference;
  return bloque("Procedencia",
    `<div class="datos">${filas.join("")}</div>` +
    (fuente?.url ? `<p><a href="${escapar(fuente.url)}" target="_blank" rel="noopener">` +
      `Servicio de origen ↗</a></p>` : "") +
    (vertical ? `<p class="aclara">Referencia vertical: ${escapar(vertical)}</p>` : "") +
    `<p class="aclara">El detalle completo de fuentes, licencias y transformaciones está en ` +
    `<a href="data/datapackage.json" target="_blank" rel="noopener">datapackage.json</a>.</p>`);
}

function csvDeSerie(f: FilaEstacion, serie: { nivel?: Punto[]; caudal?: Punto[] }): string {
  const filas: string[] = [
    "estacion_id,slug,estacion,curso,variable,timestamp_utc,valor,unidad,fuente",
  ];
  const agregar = (variable: string, unidad: string, puntos: Punto[] | undefined) => {
    for (const [t, v] of puntos ?? []) {
      filas.push([
        f.estacion_id, f.slug, `"${f.nombre.replace(/"/g, '""')}"`,
        `"${(f.curso ?? "").replace(/"/g, '""')}"`, variable,
        new Date(t * 1000).toISOString(), String(v), unidad,
        `"${f.fuente.replace(/"/g, '""')}"`,
      ].join(","));
    }
  };
  agregar("nivel", "m", serie.nivel);
  agregar("caudal", "m3/s", serie.caudal);
  return filas.join("\n");
}

export type OpcionesPanel = {
  contenedor: HTMLElement;
  fila: FilaEstacion;
  estado: Estado;
  series: Series | null;
  catalogo: Catalogo | null;
  alCerrar: () => void;
};

export function montarPanelEstacion(opciones: OpcionesPanel): void {
  const { contenedor, fila, estado, series, catalogo, alCerrar } = opciones;
  const serie = series?.estaciones[fila.id] ?? {};
  const nivel = (serie.nivel ?? []) as Punto[];
  const caudal = (serie.caudal ?? []) as Punto[];
  const ventana = series?.ventana_dias ?? 45;
  const total = nivel.length + caudal.length;

  const variables = [
    { clave: "nivel", rotulo: "Nivel", unidad: "m", puntos: nivel },
    { clave: "caudal", rotulo: "Caudal", unidad: "m³/s", puntos: caudal },
  ].filter((v) => v.puntos.length > 0);

  const selector = variables.length > 1
    ? `<div class="variables">${variables.map((v, i) =>
        `<button type="button" data-variable="${v.clave}"${i ? "" : ' class="sel"'}>${v.rotulo}</button>`,
      ).join("")}</div>`
    : "";

  contenedor.innerHTML =
    `<div class="cabecera-panel">` +
    `<button type="button" class="volver">← Mapa</button>` +
    `<button type="button" class="copiar-enlace" data-enlace="${
      urlAbsoluta({ vista: "estacion", slug: fila.slug })}">Copiar enlace</button>` +
    `</div>` +
    bloqueIdentidad(fila, estado) +
    bloqueAhora(fila, nivel) +
    bloqueInterpretacion(fila, nivel) +
    bloque("Evolución registrada",
      selector + `<div class="lienzo"></div>` +
      `<p class="aclara">Serie construida con los registros que Cauce guarda cada 2 h. ` +
      `Los tramos sin observaciones quedan en blanco: no se unen con una línea.</p>` +
      (total ? `<button type="button" class="descargar">Descargar CSV de la serie</button>` : "")) +
    bloqueUmbrales(fila) +
    bloqueHistorico(total, ventana) +
    bloqueCalidad(fila, estado, total, ventana) +
    bloqueProcedencia(fila, catalogo);

  const lienzo = contenedor.querySelector<HTMLElement>(".lienzo")!;
  const dibujar = (clave: string) => {
    const v = variables.find((x) => x.clave === clave) ?? variables[0];
    if (!v) {
      montarGrafico(lienzo, { puntos: [], unidad: "" });
      return;
    }
    const marcas = [];
    if (v.clave === "nivel" && fila.alerta != null) {
      marcas.push({ valor: fila.alerta, rotulo: "alerta", clase: "alerta" });
      if (fila.evacuacion != null) {
        marcas.push({ valor: fila.evacuacion, rotulo: "evacuación", clase: "alerta" });
      }
    }
    if (v.clave === "caudal" && fila.q_medio) {
      marcas.push({ valor: fila.q_medio, rotulo: "media de referencia", clase: "referencia" });
    }
    montarGrafico(lienzo, { puntos: v.puntos, unidad: v.unidad, marcas });
  };
  dibujar(variables[0]?.clave ?? "nivel");

  contenedor.querySelector(".variables")?.addEventListener("click", (ev) => {
    const boton = (ev.target as HTMLElement).closest<HTMLButtonElement>("[data-variable]");
    if (!boton) return;
    contenedor.querySelectorAll(".variables button").forEach((b) => b.classList.remove("sel"));
    boton.classList.add("sel");
    dibujar(boton.dataset.variable!);
  });

  contenedor.querySelector(".volver")?.addEventListener("click", alCerrar);

  contenedor.querySelector(".descargar")?.addEventListener("click", () => {
    const blob = new Blob(["﻿" + csvDeSerie(fila, { nivel, caudal })],
      { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cauce-${fila.slug}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  });

  contenedor.scrollTop = 0;
}
