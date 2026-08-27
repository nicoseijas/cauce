import {
  cargarSeries,
  redondearHoras,
  type Estado,
  type FilaEstacion,
  type LluviaEstacion,
  type ResultadoQC,
  type Series,
} from "./estado";

/** Tope de filas dibujadas: el histórico crece hasta decenas de miles y el
 * CSV siempre exporta la selección completa. */
const MAX_FILAS_VISIBLES = 2000;

type Filtro = { texto: string; opcion: string };

type Columna<T> = {
  clave: string;
  rotulo: string;
  titulo?: string;
  num?: boolean;
  /** primer clic descendente; por defecto lo hacen las columnas numéricas */
  descPrimero?: boolean;
  /** clave de ordenamiento; null va siempre al final */
  orden: (f: T) => string | number | null;
  celda: (f: T) => string;
};

type HojaCfg<T> = {
  filas: T[];
  columnas: Columna<T>[];
  /** valor de la lista desplegable y el texto de su opción vacía */
  opcionDe: (f: T) => string;
  opcionVacia: string;
  textoDe: (f: T) => string;
  inicial: { clave: string; asc: boolean };
  nota: string;
  cabecerasCsv: string[];
  filaCsv: (f: T) => (string | number | null)[];
  nombreCsv: string;
  alSeleccionar?: (f: T) => void;
};

type Hoja = {
  opciones: string[];
  opcionVacia: string;
  nota: string;
  total: number;
  nombreCsv: string;
  dibujar: (
    tabla: HTMLTableElement,
    filtro: Filtro,
    alOrdenar: () => void,
  ) => { visibles: number; dibujadas: number };
  csv: (filtro: Filtro) => string;
};

function escapar(v: string): string {
  return v.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

function sinAcentos(v: string): string {
  return v.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
}

const VACIO = '<span class="vacio">—</span>';

function numero(v: number | null, decimales: number): string {
  if (v == null) return VACIO;
  return v.toLocaleString("es-UY", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

function caudal(v: number | null): string {
  if (v == null) return VACIO;
  return numero(v, v >= 100 ? 0 : v >= 1 ? 1 : 2);
}

function chipQC(qc: ResultadoQC | null): string {
  if (!qc) return VACIO;
  const codigos = qc.codigos.join(", ");
  return `<span class="qc ${qc.estado}" title="${escapar(codigos || "sin observaciones")}">` +
    `${qc.estado.replace("_", " ")}</span>`;
}

/** Peor de las dos banderas: manda lo que más limita el uso del dato. */
function qcPeor(f: FilaEstacion): ResultadoQC | null {
  const orden: ResultadoQC["estado"][] = ["rechazado", "dudoso", "vencido", "ok", "sin_dato"];
  const banderas = [f.qc_nivel, f.qc_caudal].filter((q): q is ResultadoQC => q != null);
  banderas.sort((a, b) => orden.indexOf(a.estado) - orden.indexOf(b.estado));
  return banderas[0] ?? null;
}

function celdaMedicion(valor: string, qc: ResultadoQC | null): string {
  const marca = qc && qc.estado !== "ok" && qc.estado !== "sin_dato" ? ` qc-${qc.estado}` : "";
  return `<span class="medida${marca}">${valor}</span>`;
}

function puntoFrescura(h: number | null): string {
  const clase = h == null || h < 0 ? "gris" : h < 24 ? "verde" : h < 48 ? "ambar" : "gris";
  return `<span class="dot ${clase}"></span>`;
}

function antiguedad(h: number | null): string {
  if (h == null) return "sin dato";
  // una fecha por delante del reloj la rechaza el QC; no es una antigüedad
  if (h < 0) return "fecha futura";
  return `hace ${redondearHoras(h)}`;
}

function fechaCorta(epoch: number): string {
  return new Date(epoch * 1000).toLocaleString("es-UY", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function campoCsv(v: string | number | null): string {
  if (v == null) return "";
  const s = String(v);
  return /[",;\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

function armarCsv(cabeceras: string[], filas: (string | number | null)[][]): string {
  return [cabeceras, ...filas].map((f) => f.map(campoCsv).join(",")).join("\r\n");
}

function descargarCsv(nombre: string, contenido: string): void {
  // el BOM evita que Excel lea el UTF-8 como Latin-1
  const url = URL.createObjectURL(
    new Blob(["﻿", contenido], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  // el ancla debe estar en el documento: Chrome ignora el clic si está suelta,
  // y revocar el blob en el mismo turno cancela la descarga
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function sello(iso: string): string {
  const t = new Date(iso);
  if (!Number.isFinite(t.getTime())) return "sin-fecha";
  return t.toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
}

function crearHoja<T>(cfg: HojaCfg<T>): Hoja {
  let orden = { ...cfg.inicial };

  const visibles = (filtro: Filtro): T[] => {
    const busca = sinAcentos(filtro.texto.trim());
    const filas = cfg.filas.filter((f) =>
      (!filtro.opcion || cfg.opcionDe(f) === filtro.opcion) &&
      (!busca || sinAcentos(cfg.textoDe(f)).includes(busca)));
    const col = cfg.columnas.find((c) => c.clave === orden.clave) ?? cfg.columnas[0]!;
    return filas.sort((a, b) => {
      const va = col.orden(a);
      const vb = col.orden(b);
      if (va == null || vb == null) return va == null ? (vb == null ? 0 : 1) : -1;
      const cmp = typeof va === "number" && typeof vb === "number"
        ? va - vb
        : String(va).localeCompare(String(vb), "es-UY");
      return orden.asc ? cmp : -cmp;
    });
  };

  const ordenarPor = (clave: string): void => {
    const col = cfg.columnas.find((c) => c.clave === clave);
    orden = clave === orden.clave
      ? { clave, asc: !orden.asc }
      : { clave, asc: !(col?.descPrimero ?? col?.num === true) };
  };

  return {
    opciones: [...new Set(cfg.filas.map(cfg.opcionDe))]
      .sort((a, b) => a.localeCompare(b, "es-UY")),
    opcionVacia: cfg.opcionVacia,
    nota: cfg.nota,
    total: cfg.filas.length,
    nombreCsv: cfg.nombreCsv,
    csv: (filtro) => armarCsv(cfg.cabecerasCsv, visibles(filtro).map(cfg.filaCsv)),
    dibujar: (tabla, filtro, alOrdenar) => {
      const filas = visibles(filtro);
      const dibujadas = filas.slice(0, MAX_FILAS_VISIBLES);
      const flecha = (c: Columna<T>) =>
        c.clave === orden.clave ? (orden.asc ? " ↑" : " ↓") : "";
      tabla.innerHTML =
        `<thead><tr>${cfg.columnas.map((c) =>
          `<th data-clave="${c.clave}" class="${c.num ? "num" : ""}` +
          `${c.clave === orden.clave ? " orden" : ""}"` +
          `${c.titulo ? ` title="${escapar(c.titulo)}"` : ""}>` +
          `${escapar(c.rotulo)}${flecha(c)}</th>`).join("")}</tr></thead>` +
        `<tbody>${dibujadas.map((f, i) =>
          `<tr data-i="${i}">${cfg.columnas.map((c) =>
            `<td class="${c.num ? "num" : ""}">${c.celda(f)}</td>`).join("")}</tr>`).join("")}</tbody>`;
      for (const th of tabla.querySelectorAll<HTMLTableCellElement>("thead th")) {
        th.addEventListener("click", () => {
          if (!th.dataset.clave) return;
          ordenarPor(th.dataset.clave);
          alOrdenar();
        });
      }
      if (cfg.alSeleccionar) {
        const seleccionar = cfg.alSeleccionar;
        for (const tr of tabla.querySelectorAll<HTMLTableRowElement>("tbody tr")) {
          tr.classList.add("clicable");
          tr.addEventListener("click", () => {
            const fila = dibujadas[Number(tr.dataset.i)];
            if (fila) seleccionar(fila);
          });
        }
      }
      return { visibles: filas.length, dibujadas: dibujadas.length };
    },
  };
}

function hojaEstaciones(
  filas: FilaEstacion[],
  marca: string,
  alSeleccionar: (f: FilaEstacion) => void,
): Hoja {
  const columnas: Columna<FilaEstacion>[] = [
    {
      clave: "nombre",
      rotulo: "Estación",
      orden: (f) => sinAcentos(f.nombre),
      celda: (f) => escapar(f.nombre) +
        (f.clasificacion && f.clasificacion !== "observado"
          ? ` <span class="etiqueta">${f.clasificacion}</span>`
          : ""),
    },
    {
      clave: "curso",
      rotulo: "Curso",
      orden: (f) => f.curso && sinAcentos(f.curso),
      celda: (f) => f.curso ? escapar(f.curso) : VACIO,
    },
    { clave: "fuente", rotulo: "Fuente", orden: (f) => f.fuente, celda: (f) => escapar(f.fuente) },
    {
      clave: "nivel",
      rotulo: "Nivel (m)",
      titulo: "Cada estación mide sobre su propio cero: los niveles no se comparan entre estaciones",
      num: true,
      orden: (f) => f.nivel,
      celda: (f) => celdaMedicion(numero(f.nivel, 2), f.qc_nivel),
    },
    {
      clave: "caudal",
      rotulo: "Caudal (m³/s)",
      num: true,
      orden: (f) => f.caudal,
      celda: (f) => celdaMedicion(caudal(f.caudal), f.qc_caudal),
    },
    {
      clave: "q_medio",
      rotulo: "Media (m³/s)",
      titulo: "Caudal medio de referencia de la estación (climatología DINAGUA 1980–2010)",
      num: true,
      orden: (f) => f.q_medio,
      celda: (f) => caudal(f.q_medio),
    },
    {
      clave: "frescura",
      rotulo: "Actualizado",
      titulo: "Antigüedad de la observación más reciente de la estación",
      orden: (f) => f.frescura,
      celda: (f) => `${puntoFrescura(f.frescura)} ${antiguedad(f.frescura)}`,
    },
    {
      clave: "qc",
      rotulo: "QC",
      titulo: "Peor bandera de control de calidad entre nivel y caudal",
      orden: (f) => qcPeor(f)?.estado ?? null,
      celda: (f) => chipQC(qcPeor(f)),
    },
  ];
  return crearHoja<FilaEstacion>({
    filas,
    columnas,
    opcionDe: (f) => f.fuente,
    opcionVacia: "Todas las fuentes",
    textoDe: (f) => `${f.nombre} ${f.curso ?? ""} ${f.fuente}`,
    inicial: { clave: "frescura", asc: true },
    alSeleccionar,
    nota: "Última observación conocida de cada estación. Cada una mide sobre su " +
      "propio cero: los niveles no se comparan entre estaciones. Clic en una fila " +
      "para verla en el mapa; clic en un encabezado para ordenar.",
    nombreCsv: `cauce-estaciones-${marca}.csv`,
    cabecerasCsv: [
      "id", "estacion", "curso", "fuente", "clasificacion", "lat", "lon",
      "nivel_m", "nivel_fecha", "nivel_horas", "qc_nivel", "qc_nivel_codigos",
      "caudal_m3s", "caudal_fecha", "caudal_horas", "qc_caudal", "qc_caudal_codigos",
      "caudal_medio_m3s", "factor_vs_media", "nivel_alerta_m", "nivel_evacuacion_m",
    ],
    filaCsv: (f) => [
      f.id, f.nombre, f.curso, f.fuente, f.clasificacion, f.lat, f.lon,
      f.nivel, f.nivel_fecha, f.nivel_horas, f.qc_nivel?.estado ?? null,
      f.qc_nivel?.codigos.join(" ") ?? null,
      f.caudal, f.caudal_fecha, f.caudal_horas, f.qc_caudal?.estado ?? null,
      f.qc_caudal?.codigos.join(" ") ?? null,
      f.q_medio, f.factor, f.alerta, f.evacuacion,
    ],
  });
}

function hojaLluvia(estado: Estado, marca: string): Hoja {
  const columnas: Columna<LluviaEstacion>[] = [
    {
      clave: "nombre",
      rotulo: "Estación",
      orden: (f) => sinAcentos(f.nombre),
      celda: (f) => escapar(f.nombre),
    },
    {
      clave: "fuente",
      rotulo: "Fuente",
      orden: (f) => f.fuente ?? "",
      celda: (f) => escapar(f.fuente ?? "—"),
    },
    { clave: "mm24", rotulo: "24 h (mm)", num: true, orden: (f) => f.mm24, celda: (f) => numero(f.mm24, 1) },
    { clave: "mm72", rotulo: "72 h (mm)", num: true, orden: (f) => f.mm72, celda: (f) => numero(f.mm72, 1) },
    {
      clave: "fecha",
      rotulo: "Corte",
      titulo: "INIA acumula de 09 a 09 h; INUMET publica acumulados horarios",
      orden: (f) => f.fecha ?? null,
      celda: (f) => f.fecha ? escapar(f.fecha) : '<span class="vacio">horario</span>',
    },
  ];
  return crearHoja<LluviaEstacion>({
    filas: estado.lluvia?.estaciones ?? [],
    columnas,
    opcionDe: (f) => f.fuente ?? "—",
    opcionVacia: "Todas las fuentes",
    textoDe: (f) => f.nombre,
    inicial: { clave: "mm24", asc: false },
    nota: "Acumulados de lluvia del último estado. Los umbrales del mapa " +
      "(50 mm en 24 h, 100 mm en 72 h) son fijos: no consideran humedad previa " +
      "ni tamaño de cuenca.",
    nombreCsv: `cauce-lluvia-${marca}.csv`,
    cabecerasCsv: ["estacion", "fuente", "lat", "lon", "mm_24h", "mm_72h", "fecha_corte"],
    filaCsv: (f) => [f.nombre, f.fuente ?? null, f.lat, f.lon, f.mm24, f.mm72, f.fecha ?? null],
  });
}

type Observacion = {
  estacion: FilaEstacion;
  epoch: number;
  nivel: number | null;
  caudal: number | null;
};

/** Une nivel y caudal por fecha de observación: una fila por instante medido. */
function observaciones(series: Series, estaciones: FilaEstacion[]): Observacion[] {
  const porId = new Map(estaciones.map((e) => [e.id, e]));
  const filas: Observacion[] = [];
  for (const [id, variables] of Object.entries(series.estaciones)) {
    const estacion = porId.get(id);
    if (!estacion) continue;
    const instantes = new Map<number, Observacion>();
    for (const variable of ["nivel", "caudal"] as const) {
      for (const [epoch, valor] of variables[variable] ?? []) {
        let fila = instantes.get(epoch);
        if (!fila) {
          fila = { estacion, epoch, nivel: null, caudal: null };
          instantes.set(epoch, fila);
        }
        fila[variable] = valor;
      }
    }
    filas.push(...instantes.values());
  }
  return filas;
}

function hojaHistorico(
  series: Series | null,
  estaciones: FilaEstacion[],
  marca: string,
  alSeleccionar: (f: FilaEstacion) => void,
): Hoja {
  const columnas: Columna<Observacion>[] = [
    {
      clave: "nombre",
      rotulo: "Estación",
      orden: (f) => sinAcentos(f.estacion.nombre),
      celda: (f) => escapar(f.estacion.nombre),
    },
    {
      clave: "curso",
      rotulo: "Curso",
      orden: (f) => f.estacion.curso && sinAcentos(f.estacion.curso),
      celda: (f) => f.estacion.curso ? escapar(f.estacion.curso) : VACIO,
    },
    {
      clave: "fecha",
      rotulo: "Observación",
      titulo: "Fecha y hora de la medición según la fuente, en hora local",
      descPrimero: true,
      orden: (f) => f.epoch,
      celda: (f) =>
        `<span title="${new Date(f.epoch * 1000).toISOString()}">${fechaCorta(f.epoch)}</span>`,
    },
    {
      clave: "nivel",
      rotulo: "Nivel (m)",
      num: true,
      orden: (f) => f.nivel,
      celda: (f) => numero(f.nivel, 2),
    },
    {
      clave: "caudal",
      rotulo: "Caudal (m³/s)",
      num: true,
      orden: (f) => f.caudal,
      celda: (f) => caudal(f.caudal),
    },
  ];
  return crearHoja<Observacion>({
    filas: series ? observaciones(series, estaciones) : [],
    columnas,
    opcionDe: (f) => f.estacion.fuente,
    opcionVacia: "Todas las fuentes",
    textoDe: (f) => `${f.estacion.nombre} ${f.estacion.curso ?? ""} ${f.estacion.fuente}`,
    inicial: { clave: "fecha", asc: false },
    alSeleccionar: (f) => alSeleccionar(f.estacion),
    nota: series
      ? `Serie reconstruida con los snapshots de los últimos ${series.ventana_dias} días, ` +
        "deduplicada por fecha de observación. No incluye los valores que el control " +
        "de calidad rechazó o dejó en duda: esos quedan en el archivo del repositorio " +
        "con su bandera. Clic en una fila para ver esa estación en el mapa."
      : "No se pudo cargar la serie acumulada (data/series.json).",
    nombreCsv: `cauce-historico-${marca}.csv`,
    cabecerasCsv: ["id", "estacion", "curso", "fuente", "fecha_utc", "nivel_m", "caudal_m3s"],
    filaCsv: (f) => [
      f.estacion.id, f.estacion.nombre, f.estacion.curso, f.estacion.fuente,
      new Date(f.epoch * 1000).toISOString(), f.nivel, f.caudal,
    ],
  });
}

export function setupTabla(
  estado: Estado,
  base: string,
  vigente: boolean,
  estaciones: FilaEstacion[],
  alSeleccionar: (f: FilaEstacion) => void,
): void {
  const dialogo = document.getElementById("tabla") as HTMLDialogElement;
  const tabla = document.getElementById("tabla-datos") as HTMLTableElement;
  const buscar = document.getElementById("tabla-buscar") as HTMLInputElement;
  const selOpcion = document.getElementById("tabla-fuente") as HTMLSelectElement;
  const conteo = document.getElementById("tabla-conteo")!;
  const nota = document.getElementById("tabla-nota")!;

  const marca = sello(estado.generado);
  const enfocar = (f: FilaEstacion) => {
    dialogo.close();
    alSeleccionar(f);
  };
  const hojas: Record<string, Hoja | undefined> = {
    estaciones: hojaEstaciones(estaciones, marca, enfocar),
    lluvia: hojaLluvia(estado, marca),
  };
  let hoja = hojas.estaciones!;

  const filtro = (): Filtro => ({ texto: buscar.value, opcion: selOpcion.value });

  function pintar(): void {
    const { visibles, dibujadas } = hoja.dibujar(tabla, filtro(), pintar);
    conteo.textContent = dibujadas < visibles
      ? `${dibujadas} de ${visibles} filas (afiná el filtro o descargá el CSV)`
      : visibles === hoja.total
        ? `${hoja.total} filas`
        : `${visibles} de ${hoja.total} filas`;
  }

  async function cambiarHoja(clave: string): Promise<void> {
    if (clave === "historico" && !hojas.historico) {
      conteo.textContent = "cargando la serie…";
      const series = await cargarSeries(`${base}data/series.json`);
      hojas.historico = hojaHistorico(series, estaciones, marca, enfocar);
    }
    hoja = hojas[clave] ?? hojas.estaciones!;
    selOpcion.innerHTML = `<option value="">${escapar(hoja.opcionVacia)}</option>` +
      hoja.opciones.map((f) => `<option value="${escapar(f)}">${escapar(f)}</option>`).join("");
    nota.textContent = hoja.nota;
    pintar();
  }

  for (const boton of document.querySelectorAll<HTMLButtonElement>("#tabla-pestanas button")) {
    boton.addEventListener("click", () => {
      for (const otro of document.querySelectorAll("#tabla-pestanas button")) {
        otro.classList.toggle("sel", otro === boton);
      }
      void cambiarHoja(boton.dataset.hoja ?? "estaciones");
    });
  }
  buscar.addEventListener("input", pintar);
  selOpcion.addEventListener("change", pintar);

  document.getElementById("tabla-csv")!.addEventListener("click", () => {
    descargarCsv(hoja.nombreCsv, hoja.csv(filtro()));
  });

  const fecha = new Date(estado.generado);
  document.getElementById("tabla-sub")!.textContent =
    `${hojas.estaciones!.total} estaciones y ${hojas.lluvia!.total} pluviómetros · ` +
    `estado generado ${fecha.toLocaleString("es-UY", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    })}${vigente ? "" : " · sin actualizar: los valores pueden estar vencidos"}`;

  const boton = document.getElementById("btn-tabla") as HTMLButtonElement;
  boton.style.display = "";
  boton.addEventListener("click", () => {
    dialogo.showModal();
    buscar.focus();
  });
  document.getElementById("tabla-cerrar")!.addEventListener("click", () => dialogo.close());
  dialogo.addEventListener("click", (e) => {
    if (e.target === dialogo) dialogo.close();
  });

  void cambiarHoja("estaciones");
}
