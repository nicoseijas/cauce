"""Recorta HydroRIVERS a Uruguay y genera la red base del mapa.

Entrada:  data/raw/HydroRIVERS_v10_sa_shp/ + data/raw/departamentos.geojson
Salida:   data/processed/red_uy.geojson

El recorte incluye una franja limítrofe (buffer) para que el río Uruguay y la
Laguna Merín queden completos aunque el eje corra fuera del territorio.
"""

import logging
from pathlib import Path

import geopandas as gpd
import pyogrio

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

BBOX_UY = (-59.2, -35.5, -52.8, -29.8)
UMBRAL_UPLAND_SKM = 100
BUFFER_LIMITROFE_DEG = 0.15
TOLERANCIA_SIMPLIFICACION_DEG = 0.0005

CRS_WFS_DINAGUA = "EPSG:32721"


def cargar_uruguay_buffer() -> gpd.GeoSeries:
    deptos = gpd.read_file(RAW / "departamentos.geojson")
    # El WFS de DINAGUA emite coordenadas UTM 21S pero el GeoJSON se lee como
    # 4326 por defecto: detectar por magnitud y corregir la declaración.
    minx, miny, maxx, maxy = deptos.total_bounds
    if abs(minx) > 180 or abs(maxy) > 90:
        deptos = deptos.set_crs(CRS_WFS_DINAGUA, allow_override=True)
    elif deptos.crs is None:
        deptos = deptos.set_crs("EPSG:4326")
    deptos = deptos.to_crs("EPSG:4326")
    return gpd.GeoSeries([deptos.union_all().buffer(BUFFER_LIMITROFE_DEG)], crs="EPSG:4326")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    log.info("leyendo HydroRIVERS (bbox %s)...", BBOX_UY)
    rios = gpd.read_file(
        RAW / "HydroRIVERS_v10_sa_shp" / "HydroRIVERS_v10_sa.shp",
        bbox=BBOX_UY,
        engine="pyogrio",
    )
    log.info("en bbox: %d tramos", len(rios))

    uy = cargar_uruguay_buffer()
    rios = rios[rios.geometry.intersects(uy.iloc[0])]
    log.info("dentro de Uruguay+buffer: %d tramos", len(rios))

    for umbral in (0, 50, 100, 250, 500):
        n = (rios["UPLAND_SKM"] >= umbral).sum()
        log.info("  UPLAND_SKM >= %4d: %5d tramos", umbral, n)

    rios = rios[rios["UPLAND_SKM"] >= UMBRAL_UPLAND_SKM].copy()

    rios = rios[[
        "HYRIV_ID", "NEXT_DOWN", "MAIN_RIV", "LENGTH_KM",
        "UPLAND_SKM", "DIS_AV_CMS", "ORD_STRA", "geometry",
    ]]
    rios["geometry"] = rios.geometry.simplify(
        TOLERANCIA_SIMPLIFICACION_DEG, preserve_topology=True
    )

    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / "red_uy.geojson"
    pyogrio.write_dataframe(
        rios, out, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "5", "RFC7946": "YES"},
    )
    log.info("guardado %s: %d tramos, %.1f MB",
             out, len(rios), out.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
