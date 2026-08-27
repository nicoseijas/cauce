/** Resumen de situación: la conclusión antes del mapa.
 *
 * Responde «¿hay algo que mirar hoy?» sin obligar a decodificar la leyenda.
 * Solo enuncia categorías que los datos sostienen: si ningún curso tiene
 * escala vigente, lo dice en vez de mostrar tres ceros.
 */

import {
  categoriaAnomalia,
  fuentesConProblemas,
  CORTE_ANOMALIA,
  estadoVigente,
  redondearHoras,
  type CategoriaAnomalia,
  type Estado,
  type FilaEstacion,
} from "./estado";

/** Una observación deja de describir el presente pasado este plazo. */
const FRESCURA_RECIENTE_H = 24;

export type Conteos = {
  recientes: number;
  total: number;
  porCategoria: Record<CategoriaAnomalia, number>;
  cursosConEscala: number;
};

export function contar(estado: Estado, filas: FilaEstacion[]): Conteos {
  const porCategoria: Record<CategoriaAnomalia, number> = { encima: 0, habitual: 0, debajo: 0 };
  const factores = Object.values(estado.factores_curso ?? {});
  for (const f of factores) porCategoria[categoriaAnomalia(f.factor)]++;
  return {
    recientes: filas.filter((f) => f.frescura != null && f.frescura <= FRESCURA_RECIENTE_H).length,
    total: filas.length,
    porCategoria,
    cursosConEscala: factores.length,
  };
}

const FILAS: { clave: CategoriaAnomalia; signo: string; texto: string }[] = [
  { clave: "encima", signo: "↑", texto: "por encima de lo habitual" },
  { clave: "habitual", signo: "≈", texto: "dentro de lo habitual" },
  { clave: "debajo", signo: "↓", texto: "por debajo de lo habitual" },
];

function escapar(t: string): string {
  return t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

export function pintarResumen(
  contenedor: HTMLElement,
  estado: Estado,
  filas: FilaEstacion[],
): void {
  const c = contar(estado, filas);
  const vigente = estadoVigente(estado);
  const antiguedad = (Date.now() - new Date(estado.generado).getTime()) / 3_600_000;

  const cobertura =
    `<p class="cobertura"><span class="cifra">${c.recientes}</span> de ${c.total} ` +
    `estaciones con dato de las últimas ${FRESCURA_RECIENTE_H} h</p>`;

  const cursos = c.cursosConEscala
    ? `<ul class="categorias">${FILAS.filter((f) => c.porCategoria[f.clave] > 0).map((f) =>
        `<li class="${f.clave}"><span class="signo">${f.signo}</span>` +
        `<span class="cifra">${c.porCategoria[f.clave]}</span> ${escapar(f.texto)}</li>`,
      ).join("")}</ul>` +
      `<p class="aclara">Sobre los ${c.cursosConEscala} cursos con medición vigente asociada. ` +
      `«Habitual» es entre ${(1 / CORTE_ANOMALIA).toFixed(2)}× y ${CORTE_ANOMALIA}× su caudal ` +
      `medio de referencia: una convención de Cauce, no un umbral oficial.</p>`
    : `<p class="aclara">Ningún curso tiene hoy una medición vigente que permita ` +
      `compararlo con su caudal habitual.</p>`;

  // La advertencia vive donde se lee el estado, no como etiqueta junto al
  // título: ahí decía «parcial» sin decir parcial de qué.
  const caidas = fuentesConProblemas(estado);
  const dudosas = estado.control_calidad?.incidencias?.length ?? 0;
  const avisos = [
    caidas.length ? `sin dato reciente de ${caidas.length} fuente${caidas.length > 1 ? "s" : ""}` : "",
    dudosas ? `${dudosas} observación${dudosas > 1 ? "es" : ""} en revisión` : "",
  ].filter(Boolean);

  contenedor.innerHTML =
    `<h2 class="titulo-bloque">Ahora</h2>` +
    cobertura + cursos +
    (avisos.length ? `<p class="avisos">⚠ ${escapar(avisos.join(" · "))}</p>` : "") +
    `<p class="sello ${vigente ? "" : "vencido"}">` +
    (vigente
      ? `Actualizado hace ${escapar(redondearHoras(antiguedad))}`
      : `Sin actualizar desde hace ${escapar(redondearHoras(antiguedad))}: ` +
        `no describe la situación actual`) +
    `</p>`;
}
