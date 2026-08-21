export type ActivacionLocalidad = {
  estacion: string;
  nivel: number;
  nivel_horas: number;
  periodo_activo: number;
  proximo?: { periodo: number; faltan_m: number };
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
};

export type UteRioNegro = {
  actualizado: string | null;
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
  generado: string;
  fuentes: Record<string, string>;
  estaciones: EstacionEstado[];
  factores_curso: Record<string, { factor: number; estacion: string }>;
  activacion?: Record<string, ActivacionLocalidad>;
  lluvia?: { hasta: string; estaciones: LluviaEstacion[] } | null;
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
};

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
      tocados++;
    }
  }
  return tocados;
}

export function frescuraHoras(e: EstacionEstado): number | null {
  const c = [e.nivel_horas, e.caudal_horas].filter(
    (h): h is number => h != null,
  );
  return c.length ? Math.min(...c) : null;
}

export function estacionesComoGeoJSON(estado: Estado) {
  // la pseudo-estación Salto Grande (id -1) se muestra como represa, no
  // como estación
  const propias = estado.estaciones.filter((e) => e.id !== -1).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: { ...e, frescura: frescuraHoras(e) ?? 9999 },
  }));
  const ina = (estado.ina?.estaciones ?? []).map((e) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [e.lon, e.lat] },
    properties: {
      ...e,
      fuente: "INA / Prefectura (Argentina)",
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
      frescura: e.horas,
    },
  }));
  return {
    type: "FeatureCollection",
    features: [...propias, ...ina, ...ana, ...sohma],
  };
}
