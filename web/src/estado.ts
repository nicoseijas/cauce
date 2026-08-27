export type ActivacionLocalidad = {
  estacion: string;
  nivel: number;
  nivel_horas: number;
  periodo_activo: number;
  proximo?: { periodo: number; faltan_m: number };
};

export type ClasificacionDato = "observado" | "pronosticado" | "estimado";

export type FuenteDetalle = {
  estado: "ok" | "caida" | "vencida" | "sin_fecha" | "no_implementada";
  ultima_observacion: string | null;
  ultimo_exito: string | null;
};

export type CoberturaActivacion = {
  configuradas: number;
  habilitadas: number;
  evaluadas: number;
  rechazadas_qc?: number;
  con_estacion_superficial?: number;
  con_curso_compatible?: number;
  tipos_inundacion?: Record<string, number>;
  bloqueos?: Record<string, number>;
  fuente_disponible: boolean;
};

export type ResultadoQC = {
  estado: "ok" | "vencido" | "dudoso" | "rechazado" | "sin_dato";
  codigos: string[];
  apto_informativo: boolean;
  apto_derivados: boolean;
  antiguedad_h: number | null;
  controles: string[];
  rango_aplicado?: { min: number; max: number };
  continuidad?: { intervalo_h: number; delta_m: number };
  referencia?: { valor: number; fecha: string } | null;
  vigilancia?: string;
};

export type ControlCalidad = {
  version: string;
  metodo: {
    corrige_valores: boolean;
    rango_nivel_fluvial_m: number[];
    rango_nivel_otro_m: number[];
    rango_caudal_m3_s: number[];
    salto_nivel_dudoso_m: number;
    ventana_continuidad_h: number;
    vigencia_derivados_h: number;
    limitacion: string;
  };
  resumen: Record<"nivel" | "caudal", Partial<Record<ResultadoQC["estado"], number>>>;
  incidencias: {
    id: string | number;
    estacion: string;
    fuente: string;
    variable: "nivel" | "caudal";
    estado: "dudoso" | "rechazado";
    codigos: string[];
    valor: number;
    fecha: string;
  }[];
  vigilancia_reforzada: { id: number; estacion: string; motivo: string }[];
};

export type FactorCurso = {
  factor: number;
  estacion: string;
  clasificacion: "estimado";
  insumo_clasificacion: "observado" | "pronosticado";
  oficial: boolean;
  fecha_insumo: string | null;
  antiguedad_h: number | null;
  valido_para?: string | null;
  horizonte?: string;
  probabilidad?: number | null;
  alcance: string;
  incertidumbre: string;
  qc_version?: string;
};

export type LluviaEstacion = {
  nombre: string;
  lat: number;
  lon: number;
  mm24: number;
  mm72: number;
  fuente?: "INUMET" | "INIA";
  /** solo INIA: fecha del último acumulado diario (09 a 09 h) */
  fecha?: string;
};

export type EstacionINA = {
  id: string;
  nombre: string;
  curso: string;
  lat: number;
  lon: number;
  nivel: number;
  nivel_fecha: string;
  nivel_horas: number;
  alerta: number | null;
  evacuacion: number | null;
  qc_nivel?: ResultadoQC;
  qc_caudal?: ResultadoQC;
};

export type EstacionANA = {
  id: string;
  nombre: string;
  curso: string;
  lat: number;
  lon: number;
  nivel: number | null;
  caudal: number | null;
  fecha: string;
  horas: number;
  mm24: number;
  q_medio: number;
  area_km2: number;
  factor?: number;
  qc_nivel?: ResultadoQC;
  qc_caudal?: ResultadoQC;
};

export type EstacionSOHMA = {
  id: string;
  nombre: string;
  curso: string;
  lat: number;
  lon: number;
  nivel: number;
  fecha: string;
  horas: number;
  qc_nivel?: ResultadoQC;
  qc_caudal?: ResultadoQC;
};

export type UteRioNegro = {
  actualizado: string | null;
  clasificacion?: "pronosticado";
  oficial?: boolean;
  horizonte_dias?: number;
  probabilidad?: number | null;
  incertidumbre?: string;
  dias: {
    fecha: string;
    san_gregorio_local: number | null;
    paso_toros_oficial: number | null;
    mercedes_local: number | null;
    erogado_bonete: number | null;
    erogado_palmar: number | null;
  }[];
  maximos: { lugar: string; nivel: number; fecha: string }[];
};

export type SaltoGrande = {
  turbinado: number | null;
  vertido: number | null;
  total: number;
  fecha_local: string | null;
};

export type Estado = {
  schema_version?: number;
  generado: string;
  fuentes: Record<string, string>;
  fuentes_detalle?: Record<string, FuenteDetalle>;
  estaciones: EstacionEstado[];
  factores_curso: Record<string, FactorCurso>;
  activacion?: Record<string, ActivacionLocalidad>;
  activacion_cobertura?: CoberturaActivacion;
  control_calidad?: ControlCalidad;
  lluvia?: { hasta: string | null; estaciones: LluviaEstacion[] } | null;
  salto_grande?: SaltoGrande | null;
  ina?: { estaciones: EstacionINA[] } | null;
  ute_rio_negro?: UteRioNegro | null;
  ana?: { estaciones: EstacionANA[] } | null;
  sohma?: { estaciones: EstacionSOHMA[] } | null;
};

export type EstacionEstado = {
  id: number;
  nombre: string;
  curso: string | null;
  tipo: string | null;
  clasificacion?: ClasificacionDato;
  oficial?: boolean;
  fuente?: string;
  lat: number;
  lon: number;
  q_medio: number | null;
  codigo5: number | null;
  nivel: number | null;
  nivel_fecha: string | null;
  nivel_horas: number | null;
  caudal: number | null;
  caudal_fecha: string | null;
  caudal_horas: number | null;
  factor: number | null;
  valido_para?: string | null;
  horizonte?: string;
  probabilidad?: number | null;
  incertidumbre?: string;
  qc_nivel?: ResultadoQC;
  qc_caudal?: ResultadoQC;
};

export const FRESCURA_MAX_ESTADO_H = 6;

export function antiguedadEstadoHoras(estado: Estado, ahoraMs = Date.now()): number | null {
  const t = new Date(estado.generado).getTime();
  if (!Number.isFinite(t)) return null;
  return (ahoraMs - t) / 3_600_000;
}

export function estadoVigente(estado: Estado, ahoraMs = Date.now()): boolean {
  const horas = antiguedadEstadoHoras(estado, ahoraMs);
  return horas != null && horas >= -1 && horas <= FRESCURA_MAX_ESTADO_H;
}

export function fuentesConProblemas(estado: Estado): string[] {
  return Object.entries(estado.fuentes)
    .filter(([, valor]) => valor !== "ok" && valor !== "no_implementada")
    .map(([clave]) => clave);
}

export async function cargarEstado(url: string): Promise<Estado | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as Estado;
  } catch {
    return null;
  }
}

/** Pares [epoch_s, valor] ordenados por fecha de observación. */
export type SeriePuntos = [number, number][];

export type Series = {
  generado: string;
  ventana_dias: number;
  estaciones: Record<string, { nivel?: SeriePuntos; caudal?: SeriePuntos }>;
};

let seriesCache: Promise<Series | null> | undefined;

export function cargarSeries(url: string): Promise<Series | null> {
  seriesCache ??= (async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      return (await res.json()) as Series;
    } catch {
      return null;
    }
  })();
  return seriesCache;
}

export type RedFC = {
  features: { properties: Record<string, unknown> & {
    DIS_AV_CMS?: number; DIS_MEDIO?: number; q_medio_uy?: number;
    codigo5?: number | null; factor?: number; estacion_factor?: string;
    factor_clasificacion?: string; insumo_clasificacion?: string;
    factor_horas?: number | null; factor_fecha?: string | null;
    factor_incertidumbre?: string;
  } }[];
};

/** Aplica los factores por curso a la red: reescribe DIS_AV_CMS (lo que se
 * renderiza) y conserva la media en DIS_MEDIO para mostrarla aparte.
 *
 * La media de referencia es `q_medio_uy` (climatología de DINAGUA) donde
 * existe. HydroRIVERS queda para los cursos cuya cuenca entra al país ya
 * formada, que esa climatología no cubre. */
export function aplicarFactores(red: RedFC, estado: Estado): number {
  let tocados = 0;
  for (const f of red.features) {
    const p = f.properties;
    p.DIS_AV_CMS = p.q_medio_uy ?? p.DIS_AV_CMS;
    p.DIS_MEDIO = p.DIS_AV_CMS;
    // factores_curso indexa por nombre de curso (codigo5 es por sección)
    const clave = typeof p.nombre === "string" ? p.nombre : null;
    const fx = clave ? estado.factores_curso[clave] : undefined;
    if (fx) {
      p.DIS_AV_CMS = (p.DIS_AV_CMS ?? 0) * fx.factor;
      p.factor = fx.factor;
      p.estacion_factor = fx.estacion;
      p.factor_clasificacion = fx.clasificacion;
      p.insumo_clasificacion = fx.insumo_clasificacion;
      p.factor_horas = fx.antiguedad_h;
      p.factor_fecha = fx.fecha_insumo;
      p.factor_incertidumbre = fx.incertidumbre;
      tocados++;
    }
  }
  return tocados;
}

export function frescuraHoras(
  e: { nivel_horas?: number | null; caudal_horas?: number | null },
): number | null {
  const c = [e.nivel_horas, e.caudal_horas].filter(
    (h): h is number => h != null,
  );
  return c.length ? Math.min(...c) : null;
}

export function redondearHoras(h: number | null): string {
  if (h == null) return "—";
  if (h < 48) return `${Math.round(h)} h`;
  return `${Math.round(h / 24)} días`;
}

/** Forma publicada de una estación en cualquiera de las cuatro redes:
 * build_estado normaliza ANA y SOHMA a nivel_* y caudal_* antes de escribir. */
type EstacionPublicada = {
  id: number | string;
  nombre: string;
  curso?: string | null;
  fuente?: string;
  clasificacion?: ClasificacionDato;
  lat: number;
  lon: number;
  nivel?: number | null;
  nivel_fecha?: string | null;
  nivel_horas?: number | null;
  caudal?: number | null;
  caudal_fecha?: string | null;
  caudal_horas?: number | null;
  q_medio?: number | null;
  factor?: number | null;
  alerta?: number | null;
  evacuacion?: number | null;
  qc_nivel?: ResultadoQC;
  qc_caudal?: ResultadoQC;
};

/** Fila plana para la vista tabular y las exportaciones CSV. */
export type FilaEstacion = {
  id: string;
  nombre: string;
  curso: string | null;
  fuente: string;
  clasificacion: ClasificacionDato | null;
  lat: number;
  lon: number;
  nivel: number | null;
  nivel_fecha: string | null;
  nivel_horas: number | null;
  caudal: number | null;
  caudal_fecha: string | null;
  caudal_horas: number | null;
  q_medio: number | null;
  factor: number | null;
  /** umbrales operativos de la fuente; hoy solo los publica el INA */
  alerta: number | null;
  evacuacion: number | null;
  qc_nivel: ResultadoQC | null;
  qc_caudal: ResultadoQC | null;
  frescura: number | null;
};

export function filasEstaciones(estado: Estado): FilaEstacion[] {
  const todas: EstacionPublicada[] = [
    ...estado.estaciones,
    ...(estado.ina?.estaciones ?? []),
    ...(estado.ana?.estaciones ?? []),
    ...(estado.sohma?.estaciones ?? []),
  ];
  return todas.map((e) => ({
    id: String(e.id),
    nombre: e.nombre,
    curso: e.curso ?? null,
    fuente: e.fuente ?? "—",
    clasificacion: e.clasificacion ?? null,
    lat: e.lat,
    lon: e.lon,
    nivel: e.nivel ?? null,
    nivel_fecha: e.nivel_fecha ?? null,
    nivel_horas: e.nivel_horas ?? null,
    caudal: e.caudal ?? null,
    caudal_fecha: e.caudal_fecha ?? null,
    caudal_horas: e.caudal_horas ?? null,
    q_medio: e.q_medio ?? null,
    factor: e.factor ?? null,
    alerta: e.alerta ?? null,
    evacuacion: e.evacuacion ?? null,
    qc_nivel: e.qc_nivel ?? null,
    qc_caudal: e.qc_caudal ?? null,
    frescura: frescuraHoras(e),
  }));
}

export function estacionesComoGeoJSON(estado: Estado) {
  const propiedadesQC = (e: {
    qc_nivel?: ResultadoQC;
    qc_caudal?: ResultadoQC;
  }) => {
    const estados = [e.qc_nivel?.estado, e.qc_caudal?.estado];
    const qcEstado = estados.includes("rechazado")
      ? "rechazado"
      : estados.includes("dudoso")
        ? "dudoso"
        : estados.includes("ok")
          ? "ok"
          : estados.includes("vencido")
            ? "vencido"
            : "sin_dato";
    return {
      qc_estado: qcEstado,
      qc_nivel_estado: e.qc_nivel?.estado,
      qc_nivel_codigos: e.qc_nivel?.codigos.join(",") ?? "",
      qc_caudal_estado: e.qc_caudal?.estado,
      qc_caudal_codigos: e.qc_caudal?.codigos.join(",") ?? "",
    };
  };
  // la pseudo-estación Salto Grande (id -1) se muestra como represa, no
  // como estación
  const propias = estado.estaciones.filter((e) => e.id !== -1).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: { ...e, ...propiedadesQC(e), frescura: frescuraHoras(e) ?? 9999 },
  }));
  const ina = (estado.ina?.estaciones ?? []).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: {
      ...e,
      fuente: "INA / Prefectura (Argentina)",
      ...propiedadesQC(e),
      frescura: e.nivel_horas,
    },
  }));
  const ana = (estado.ana?.estaciones ?? []).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: {
      ...e,
      nivel_horas: e.horas,
      caudal_horas: e.horas,
      fuente: "ANA (Brasil)",
      ...propiedadesQC(e),
      frescura: e.horas,
    },
  }));
  const sohma = (estado.sohma?.estaciones ?? []).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: {
      ...e,
      nivel_horas: e.horas,
      fuente: "SOHMA (Armada) · nivel sobre el cero local (Ex Wharton)",
      ...propiedadesQC(e),
      frescura: e.horas,
    },
  }));
  return {
    type: "FeatureCollection",
    features: [...propias, ...ina, ...ana, ...sohma],
  };
}
