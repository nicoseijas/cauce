"""Audita la fidelidad geométrica de la red del mapa (HydroRIVERS) contra la
cartografía oficial de DINAGUA (shp_cursos), que proviene de un relevamiento
independiente.

Para cada río con nombre compartido: muestrea puntos cada 500 m sobre nuestra
geometría y mide la distancia al curso oficial homónimo (y a la inversa, para
detectar tramos oficiales que nos faltan).

Salida: tabla por consola + data/processed/fidelidad.png (superposición).
"""

import logging
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from build_red import leer_wfs_geojson

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CRS_METRICO = "EPSG:32721"
PASO_MUESTREO_M = 500

RIOS_AUDITADOS = [
    "Río Negro", "Río Santa Lucía", "Río Cebollatí", "Río Cuareim",
    "Río Yí", "Río Tacuarembó", "Río Queguay Grande", "Río Arapey Grande",
    "Río Olimar Grande", "Río San José", "Río Daymán", "Río San Salvador",
    "Río Rosario", "Río Yaguarón", "Río Tacuarí",
]


def puntos_a_lo_largo(geom, paso: float) -> np.ndarray:
    lineas = geom.geoms if geom.geom_type in ("MultiLineString",) else [geom]
    puntos = []
    for ln in lineas:
        for d in np.arange(0, ln.length, paso):
            p = ln.interpolate(d)
            puntos.append((p.x, p.y))
    return np.array(puntos)


def distancias(puntos: np.ndarray, objetivo) -> np.ndarray:
    from shapely.geometry import Point
    return np.array([objetivo.distance(Point(x, y)) for x, y in puntos])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    red = gpd.read_file(ROOT / "data" / "processed" / "red_uy.geojson").to_crs(CRS_METRICO)
    cursos = leer_wfs_geojson(ROOT / "data" / "raw" / "cursos.geojson").to_crs(CRS_METRICO)

    log.info("%-22s %8s %8s %8s %8s  %s", "Río", "med_m", "p90_m", "max_m",
             ">500m%", "cobertura oficial->mapa")
    resultados = []
    for nombre in RIOS_AUDITADOS:
        nuestro = red[red["nombre"] == nombre]
        oficial = cursos[cursos["nombre_2"] == nombre]
        if nuestro.empty or oficial.empty:
            log.info("%-22s  sin datos (mapa: %d, oficial: %d)",
                     nombre, len(nuestro), len(oficial))
            continue
        u_nuestro = nuestro.union_all()
        u_oficial = oficial.union_all()

        pts = puntos_a_lo_largo(u_nuestro, PASO_MUESTREO_M)
        d = distancias(pts, u_oficial)

        pts_of = puntos_a_lo_largo(u_oficial, PASO_MUESTREO_M)
        d_cob = distancias(pts_of, u_nuestro)
        cobertura = float((d_cob < 1000).mean() * 100)

        resultados.append((nombre, d, cobertura))
        log.info("%-22s %8.0f %8.0f %8.0f %7.1f%%  %5.1f%% a <1 km",
                 nombre, d.mean(), np.percentile(d, 90), d.max(),
                 (d > 500).mean() * 100, cobertura)

    todas = np.concatenate([d for _, d, _ in resultados])
    log.info("")
    log.info("POR NOMBRE (%d ríos, %d puntos): media %.0f m · p90 %.0f m · %.1f%% >500 m",
             len(resultados), len(todas), todas.mean(),
             np.percentile(todas, 90), (todas > 500).mean() * 100)

    # Métrica limpia: toda nuestra red (cuenca >= 250 km²) contra toda la red
    # oficial, solo en territorio uruguayo (la cartografía DINAGUA no cubre
    # los afluentes extranjeros del buffer limítrofe).
    from shapely.geometry import Point
    deptos = leer_wfs_geojson(ROOT / "data" / "raw" / "departamentos.geojson")
    deptos = deptos.to_crs(CRS_METRICO).union_all()
    u_oficial_total = cursos.union_all()
    grande = red[red["UPLAND_SKM"] >= 250]
    pts = puntos_a_lo_largo(grande.union_all(), 1000)
    dentro = np.array([deptos.contains(Point(x, y)) for x, y in pts])
    d = distancias(pts[dentro], u_oficial_total)
    log.info("GEOMÉTRICA (red >=250 km² en territorio UY, %d puntos): "
             "media %.0f m · p50 %.0f · p90 %.0f · >1 km: %.1f%%",
             int(dentro.sum()), d.mean(), np.percentile(d, 50),
             np.percentile(d, 90), (d > 1000).mean() * 100)

    fig, ax = plt.subplots(figsize=(11, 13), facecolor="#0b141d")
    ax.set_facecolor("#0b141d")
    cursos[cursos["clase"] <= 4].plot(ax=ax, color="#e05c5c", linewidth=0.5, alpha=0.8)
    red.plot(ax=ax, color="#57a8d8", linewidth=0.7, alpha=0.9)
    ax.set_xlim(280000, 880000)
    ax.set_ylim(6070000, 6720000)
    ax.axis("off")
    ax.set_title("Fidelidad: mapa (azul, HydroRIVERS) vs oficial DINAGUA (rojo)",
                 color="#cfe0ee", fontsize=12)
    out = ROOT / "data" / "processed" / "fidelidad.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="#0b141d")
    log.info("superposición guardada en %s", out)


if __name__ == "__main__":
    main()
