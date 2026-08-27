/** Buscador global de entidades del mapa.
 *
 * El índice se descarga al primer uso, no al abrir el sitio: pesa más que el
 * estado y nadie lo necesita hasta que escribe algo.
 */

export type TipoEntidad = "estacion" | "curso" | "localidad" | "departamento" | "represa";

export type Entidad = {
  tipo: TipoEntidad;
  nombre: string;
  contexto: string | null;
  slug?: string;
  /** [oeste, sur, este, norte]; solo los cursos, que no se ven en un punto */
  bbox?: [number, number, number, number];
  lat: number;
  lon: number;
};

export type IndiceBusqueda = { generado: string; entidades: Entidad[] };

export const ROTULO_TIPO: Record<TipoEntidad, string> = {
  estacion: "Estaciones",
  curso: "Cursos de agua",
  localidad: "Localidades",
  departamento: "Departamentos",
  represa: "Represas",
};

// Una estación responde «qué se midió», que es la pregunta que trae a alguien
// al buscador; el departamento es el contexto más amplio y por eso va último.
const ORDEN_TIPOS: TipoEntidad[] = ["estacion", "curso", "localidad", "represa", "departamento"];

/** Coincidir solo en el contexto vale menos que coincidir en el nombre. */
const PUNTAJE_CONTEXTO = 3;
const MAX_RESULTADOS = 24;
const MAX_POR_TIPO = 6;

export function normalizar(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

type Puntuada = { entidad: Entidad; puntaje: number };

/** Ordena por dónde cae la coincidencia: al principio del nombre, al principio
 * de una palabra, y por último en cualquier posición. */
function puntuar(entidad: Entidad, consulta: string): number | null {
  const nombre = normalizar(entidad.nombre);
  const posicion = nombre.indexOf(consulta);
  if (posicion === 0) return 0;
  if (posicion > 0) {
    const anterior = nombre[posicion - 1];
    return anterior === " " || anterior === "." ? 1 : 2;
  }
  const contexto = entidad.contexto ? normalizar(entidad.contexto) : "";
  return contexto.includes(consulta) ? PUNTAJE_CONTEXTO : null;
}

export function buscar(entidades: Entidad[], texto: string): Entidad[] {
  const consulta = normalizar(texto);
  if (consulta.length < 2) return [];

  const porTipo = new Map<TipoEntidad, Puntuada[]>();
  for (const entidad of entidades) {
    const puntaje = puntuar(entidad, consulta);
    if (puntaje === null) continue;
    const grupo = porTipo.get(entidad.tipo) ?? [];
    grupo.push({ entidad, puntaje });
    porTipo.set(entidad.tipo, grupo);
  }

  const salida: Entidad[] = [];
  for (const tipo of ORDEN_TIPOS) {
    let grupo = porTipo.get(tipo);
    if (!grupo) continue;
    // Coincidir por contexto sirve para encontrar las estaciones de un río,
    // pero si el tipo ya tiene coincidencias por nombre esas son las buscadas:
    // «durazno» no debe llenarse con las localidades del departamento Durazno.
    const porNombre = grupo.filter((p) => p.puntaje < PUNTAJE_CONTEXTO);
    if (porNombre.length) grupo = porNombre;
    grupo.sort((a, b) =>
      a.puntaje - b.puntaje ||
      a.entidad.nombre.length - b.entidad.nombre.length ||
      a.entidad.nombre.localeCompare(b.entidad.nombre, "es"),
    );
    salida.push(...grupo.slice(0, MAX_POR_TIPO).map((p) => p.entidad));
  }
  return salida.slice(0, MAX_RESULTADOS);
}

export async function cargarIndice(url: string): Promise<IndiceBusqueda | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as IndiceBusqueda;
  } catch {
    return null;
  }
}

function escapar(texto: string): string {
  return texto.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

/** Resalta el tramo coincidente sobre el texto original. Quitar los
 * diacríticos no cambia la longitud, así que la posición sigue sirviendo. */
function resaltar(nombre: string, consulta: string): string {
  const posicion = normalizar(nombre).indexOf(consulta);
  if (posicion < 0 || !consulta) return escapar(nombre);
  return (
    escapar(nombre.slice(0, posicion)) +
    "<mark>" + escapar(nombre.slice(posicion, posicion + consulta.length)) + "</mark>" +
    escapar(nombre.slice(posicion + consulta.length))
  );
}

export type OpcionesBuscador = {
  entrada: HTMLInputElement;
  panel: HTMLElement;
  urlIndice: string;
  alElegir: (entidad: Entidad) => void;
};

export function setupBuscador(opciones: OpcionesBuscador): void {
  const { entrada, panel, urlIndice, alElegir } = opciones;
  let entidades: Entidad[] = [];
  let cargando: Promise<void> | null = null;
  let visibles: Entidad[] = [];
  let activo = -1;

  const asegurarIndice = (): Promise<void> => {
    cargando ??= cargarIndice(urlIndice).then((indice) => {
      entidades = indice?.entidades ?? [];
    });
    return cargando;
  };

  const cerrar = () => {
    panel.innerHTML = "";
    panel.hidden = true;
    visibles = [];
    activo = -1;
    entrada.setAttribute("aria-expanded", "false");
  };

  const marcarActivo = () => {
    panel.querySelectorAll<HTMLElement>("[data-indice]").forEach((el) => {
      const suyo = Number(el.dataset.indice) === activo;
      el.classList.toggle("activo", suyo);
      if (suyo) el.scrollIntoView({ block: "nearest" });
    });
  };

  const pintar = () => {
    const consulta = normalizar(entrada.value);
    visibles = buscar(entidades, entrada.value);
    activo = -1;
    if (!consulta || consulta.length < 2) return cerrar();

    if (!visibles.length) {
      panel.innerHTML = `<p class="vacio">Sin resultados para «${escapar(entrada.value.trim())}»</p>`;
      panel.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
      return;
    }

    const partes: string[] = [];
    let tipoActual: TipoEntidad | null = null;
    visibles.forEach((e, i) => {
      if (e.tipo !== tipoActual) {
        tipoActual = e.tipo;
        partes.push(`<p class="grupo">${ROTULO_TIPO[e.tipo]}</p>`);
      }
      const contexto = e.contexto ? `<span class="ctx">${escapar(e.contexto)}</span>` : "";
      partes.push(
        `<button type="button" role="option" data-indice="${i}">` +
        `<span class="nom">${resaltar(e.nombre, consulta)}</span>${contexto}</button>`,
      );
    });
    panel.innerHTML = partes.join("");
    panel.hidden = false;
    entrada.setAttribute("aria-expanded", "true");
  };

  const elegir = (i: number) => {
    const entidad = visibles[i];
    if (!entidad) return;
    entrada.value = entidad.nombre;
    entrada.blur();
    cerrar();
    alElegir(entidad);
  };

  entrada.addEventListener("input", () => {
    void asegurarIndice().then(pintar);
  });
  entrada.addEventListener("focus", () => {
    void asegurarIndice();
  });

  entrada.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      cerrar();
      entrada.blur();
      return;
    }
    if (!visibles.length) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const paso = ev.key === "ArrowDown" ? 1 : -1;
      const desde = activo < 0 ? (paso > 0 ? -1 : 0) : activo;
      activo = (desde + paso + visibles.length) % visibles.length;
      marcarActivo();
      return;
    }
    if (ev.key === "Enter") {
      ev.preventDefault();
      elegir(activo >= 0 ? activo : 0);
    }
  });

  panel.addEventListener("mousedown", (ev) => {
    const boton = (ev.target as HTMLElement).closest<HTMLElement>("[data-indice]");
    if (!boton) return;
    ev.preventDefault();
    elegir(Number(boton.dataset.indice));
  });

  document.addEventListener("click", (ev) => {
    const dentro = entrada.contains(ev.target as Node) || panel.contains(ev.target as Node);
    if (!dentro) cerrar();
  });
}
