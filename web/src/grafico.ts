/** Gráfico de serie temporal.
 *
 * Un hueco es un hueco: la línea se corta donde no hubo observaciones en vez
 * de unir los extremos, que insinuaría una medición que nadie hizo.
 */

export type Punto = [epoch: number, valor: number];

export type Marca = { valor: number; rotulo: string; clase?: string };

export type OpcionesGrafico = {
  puntos: Punto[];
  unidad: string;
  /** líneas horizontales de referencia: umbrales, caudal medio */
  marcas?: Marca[];
  ancho?: number;
  alto?: number;
};

/** Un hueco es un intervalo desproporcionado frente al ritmo de la propia
 * serie. Se compara contra su mediana para no depender de la frecuencia
 * nominal, que varía entre organismos, con un piso para series muy ralas. */
const FACTOR_HUECO = 4;
const HUECO_MINIMO_H = 6;

export function separarTramos(puntos: Punto[]): Punto[][] {
  if (puntos.length < 2) return puntos.length ? [puntos] : [];
  const intervalos = puntos.slice(1).map(([t], i) => t - puntos[i][0]);
  const ordenados = [...intervalos].sort((a, b) => a - b);
  const mediana = ordenados[Math.floor(ordenados.length / 2)];
  const limite = Math.max(mediana * FACTOR_HUECO, HUECO_MINIMO_H * 3600);

  const tramos: Punto[][] = [[puntos[0]]];
  puntos.slice(1).forEach((punto, i) => {
    if (intervalos[i] > limite) tramos.push([punto]);
    else tramos[tramos.length - 1].push(punto);
  });
  return tramos;
}

export function formatearValor(valor: number, unidad: string): string {
  if (unidad === "m") return valor.toFixed(2);
  return valor >= 100 ? Math.round(valor).toLocaleString("es-UY") : valor.toFixed(1);
}

const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function fechaCorta(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${d.getDate()} ${MES[d.getMonth()]}`;
}

function fechaLarga(epoch: number): string {
  const d = new Date(epoch * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MES[d.getMonth()]} ${d.getFullYear()} · ${hh}:${mm}`;
}

/** Elige hasta `maximo` valores redondos dentro del rango. */
function escalaValores(min: number, max: number, maximo = 4): number[] {
  const bruto = (max - min) / maximo;
  if (!(bruto > 0)) return [min];
  const magnitud = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * magnitud).find((p) => p >= bruto) ?? magnitud * 10;
  const salida: number[] = [];
  for (let v = Math.ceil(min / paso) * paso; v <= max + 1e-9; v += paso) salida.push(v);
  return salida;
}

function escapar(t: string): string {
  return t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

type Geometria = {
  x: (t: number) => number;
  y: (v: number) => number;
  izq: number; der: number; arriba: number; abajo: number;
};

const MARGEN = { izq: 46, der: 10, arriba: 10, abajo: 22 };

export function montarGrafico(contenedor: HTMLElement, opciones: OpcionesGrafico): void {
  const { puntos, unidad, marcas = [] } = opciones;
  const ancho = opciones.ancho ?? (contenedor.clientWidth || 320);
  const alto = opciones.alto ?? 170;

  if (puntos.length < 2) {
    contenedor.innerHTML = `<p class="sin-serie">${
      puntos.length ? "Una sola observación: no alcanza para dibujar una evolución."
                    : "Sin observaciones en la ventana disponible."
    }</p>`;
    return;
  }

  const ts = puntos.map(([t]) => t);
  const vs = puntos.map(([, v]) => v);
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const valoresMarcas = marcas.map((m) => m.valor);
  let v0 = Math.min(...vs, ...valoresMarcas);
  let v1 = Math.max(...vs, ...valoresMarcas);
  if (v1 - v0 < 1e-9) { v0 -= 0.5; v1 += 0.5; }
  const holgura = (v1 - v0) * 0.08;
  v0 -= holgura; v1 += holgura;

  const g: Geometria = {
    izq: MARGEN.izq, der: ancho - MARGEN.der,
    arriba: MARGEN.arriba, abajo: alto - MARGEN.abajo,
    x: (t) => MARGEN.izq + ((t - t0) / (t1 - t0 || 1)) * (ancho - MARGEN.izq - MARGEN.der),
    y: (v) => alto - MARGEN.abajo - ((v - v0) / (v1 - v0)) * (alto - MARGEN.arriba - MARGEN.abajo),
  };

  const tramos = separarTramos(puntos);
  const partes: string[] = [];

  for (const valor of escalaValores(v0, v1)) {
    const y = g.y(valor).toFixed(1);
    partes.push(
      `<line class="rejilla" x1="${g.izq}" y1="${y}" x2="${g.der}" y2="${y}"/>`,
      `<text class="rotulo-y" x="${g.izq - 6}" y="${y}" dy="3">${formatearValor(valor, unidad)}</text>`,
    );
  }

  // Dos marcas próximas pisarían sus rótulos; se separan lo mínimo para leerse
  // sin mover las líneas, que sí deben quedar donde corresponde.
  const SEPARACION_ROTULOS = 11;
  let ultimoRotulo = -Infinity;
  for (const marca of [...marcas].sort((a, b) => b.valor - a.valor)) {
    const y = g.y(marca.valor);
    const yRotulo = Math.max(y - 4, ultimoRotulo + SEPARACION_ROTULOS);
    ultimoRotulo = yRotulo;
    partes.push(
      `<line class="marca ${marca.clase ?? ""}" x1="${g.izq}" y1="${y.toFixed(1)}" ` +
      `x2="${g.der}" y2="${y.toFixed(1)}"/>`,
      `<text class="rotulo-marca ${marca.clase ?? ""}" x="${g.der}" ` +
      `y="${yRotulo.toFixed(1)}">${escapar(marca.rotulo)}</text>`,
    );
  }

  for (const [i, extremo] of [t0, t1].entries()) {
    partes.push(
      `<text class="rotulo-x" x="${g.x(extremo).toFixed(1)}" y="${alto - 6}" ` +
      `text-anchor="${i ? "end" : "start"}">${fechaCorta(extremo)}</text>`,
    );
  }

  // Los huecos se señalan; unir sus extremos sugeriría una continuidad medida.
  tramos.forEach((tramo, i) => {
    if (i > 0) {
      const desde = g.x(tramos[i - 1][tramos[i - 1].length - 1][0]);
      const hasta = g.x(tramo[0][0]);
      partes.push(
        `<rect class="hueco" x="${desde.toFixed(1)}" y="${g.arriba}" ` +
        `width="${(hasta - desde).toFixed(1)}" height="${(g.abajo - g.arriba).toFixed(1)}"/>`,
        `<line class="borde-hueco" x1="${desde.toFixed(1)}" y1="${g.arriba}" ` +
        `x2="${desde.toFixed(1)}" y2="${g.abajo}"/>`,
        `<line class="borde-hueco" x1="${hasta.toFixed(1)}" y1="${g.arriba}" ` +
        `x2="${hasta.toFixed(1)}" y2="${g.abajo}"/>`,
      );
    }
    if (tramo.length === 1) {
      partes.push(`<circle class="suelto" cx="${g.x(tramo[0][0]).toFixed(1)}" cy="${g.y(tramo[0][1]).toFixed(1)}" r="2.4"/>`);
      return;
    }
    const d = tramo.map(([t, v]) => `${g.x(t).toFixed(1)},${g.y(v).toFixed(1)}`).join(" ");
    partes.push(`<polyline class="linea" points="${d}"/>`);
  });

  for (const [t, v] of puntos) {
    partes.push(`<circle class="punto" cx="${g.x(t).toFixed(1)}" cy="${g.y(v).toFixed(1)}" r="1.9"/>`);
  }

  partes.push(
    `<line class="cursor" x1="0" y1="${g.arriba}" x2="0" y2="${g.abajo}" style="display:none"/>`,
    `<circle class="cursor-punto" r="3.4" style="display:none"/>`,
  );

  contenedor.innerHTML =
    `<svg class="grafico" viewBox="0 0 ${ancho} ${alto}" width="${ancho}" height="${alto}" ` +
    `role="img" aria-label="Serie temporal de ${escapar(unidad)}">${partes.join("")}</svg>` +
    `<p class="lectura" aria-live="polite"></p>`;

  const svg = contenedor.querySelector("svg")!;
  const cursor = svg.querySelector<SVGLineElement>(".cursor")!;
  const marcador = svg.querySelector<SVGCircleElement>(".cursor-punto")!;
  const lectura = contenedor.querySelector<HTMLElement>(".lectura")!;

  const mostrar = (ev: PointerEvent) => {
    const caja = svg.getBoundingClientRect();
    const px = ((ev.clientX - caja.left) / caja.width) * ancho;
    let cercano = puntos[0];
    for (const punto of puntos) {
      if (Math.abs(g.x(punto[0]) - px) < Math.abs(g.x(cercano[0]) - px)) cercano = punto;
    }
    const [t, v] = cercano;
    cursor.setAttribute("x1", String(g.x(t)));
    cursor.setAttribute("x2", String(g.x(t)));
    cursor.style.display = "";
    marcador.setAttribute("cx", String(g.x(t)));
    marcador.setAttribute("cy", String(g.y(v)));
    marcador.style.display = "";
    lectura.textContent = `${formatearValor(v, unidad)} ${unidad} · ${fechaLarga(t)}`;
  };

  const ocultar = () => {
    cursor.style.display = "none";
    marcador.style.display = "none";
    lectura.textContent = "";
  };

  svg.addEventListener("pointermove", mostrar);
  svg.addEventListener("pointerleave", ocultar);
}
