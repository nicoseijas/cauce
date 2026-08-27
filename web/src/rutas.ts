/** Enrutado por History API sobre GitHub Pages.
 *
 * Pages no reescribe rutas: sirve `404.html` ante cualquier ruta que no sea un
 * archivo. Ese 404 devuelve el control al índice conservando la ruta pedida,
 * de modo que aquí siempre se lee una ruta completa y no un parámetro.
 */

export type Ruta = { vista: "mapa" } | { vista: "estacion"; slug: string };

/** Prefijo bajo el que se sirve la aplicación, con barras a ambos lados. */
export function raizDelSitio(): string {
  const base = import.meta.env.BASE_URL || "/";
  return base.endsWith("/") ? base : `${base}/`;
}

function rutaRelativa(url: URL): string {
  const raiz = raizDelSitio();
  const camino = url.pathname.startsWith(raiz)
    ? url.pathname.slice(raiz.length)
    : url.pathname.replace(/^\//, "");
  return camino.replace(/\/+$/, "");
}

const CLAVE_RUTA_DIFERIDA = "cauce:ruta";

/** Recupera la ruta que `404.html` guardó antes de devolver el control al índice.
 *
 * Devuelve la URL restaurada, o null si se entró directamente al índice. */
export function recuperarRutaDiferida(): URL | null {
  let guardada: string | null = null;
  try {
    guardada = sessionStorage.getItem(CLAVE_RUTA_DIFERIDA);
    sessionStorage.removeItem(CLAVE_RUTA_DIFERIDA);
  } catch {
    return null;
  }
  if (!guardada) return null;
  const destino = new URL(raizDelSitio() + guardada.replace(/^\//, ""), location.origin);
  history.replaceState(null, "", destino.href);
  return destino;
}

export function interpretar(url: URL = new URL(location.href)): Ruta {
  const partes = rutaRelativa(url).split("/").filter(Boolean).map(decodeURIComponent);
  if (partes.length === 2 && partes[0] === "estaciones") {
    return { vista: "estacion", slug: partes[1].toLowerCase() };
  }
  return { vista: "mapa" };
}

export function urlDeEstacion(slug: string): string {
  return `${raizDelSitio()}estaciones/${encodeURIComponent(slug)}`;
}

export function urlAbsoluta(ruta: Ruta): string {
  const camino = ruta.vista === "estacion" ? urlDeEstacion(ruta.slug) : raizDelSitio();
  return new URL(camino, location.origin).href;
}

type Indice = {
  /** slug canónico de cada estación */
  slugs: Set<string>;
  /** identificador canónico a slug, para no romper enlaces publicados */
  alias: Map<string, string>;
};

export function construirIndice(
  estaciones: { estacion_id: string; slug: string }[],
): Indice {
  return {
    slugs: new Set(estaciones.map((e) => e.slug)),
    alias: new Map(estaciones.map((e) => [e.estacion_id.toLowerCase(), e.slug])),
  };
}

/** Resuelve un slug pedido al canónico, o null si no identifica una estación. */
export function resolver(indice: Indice, slug: string): string | null {
  if (indice.slugs.has(slug)) return slug;
  return indice.alias.get(slug) ?? null;
}

export type Enrutador = {
  /** navega y deja entrada en el historial */
  ir: (ruta: Ruta) => void;
  /** corrige la URL actual sin ensuciar el historial */
  sustituir: (ruta: Ruta) => void;
  actual: () => Ruta;
};

export function crearEnrutador(alCambiar: (ruta: Ruta) => void): Enrutador {
  const aplicar = (ruta: Ruta, reemplazar: boolean) => {
    const destino = urlAbsoluta(ruta);
    if (destino !== location.href) {
      if (reemplazar) history.replaceState(null, "", destino);
      else history.pushState(null, "", destino);
    }
    alCambiar(ruta);
  };
  addEventListener("popstate", () => alCambiar(interpretar()));
  return {
    ir: (ruta) => aplicar(ruta, false),
    sustituir: (ruta) => aplicar(ruta, true),
    actual: () => interpretar(),
  };
}
