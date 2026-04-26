"""Recorta HydroRIVERS a Uruguay y genera la red base del mapa.

Entrada:  data/raw/HydroRIVERS_v10_sa_shp/ + data/raw/departamentos.geojson
          + data/raw/cursos.geojson (nombres DINAGUA)
Salida:   data/processed/red_uy.geojson

El recorte incluye una franja limítrofe (buffer) para que el río Uruguay y la
Laguna Merín queden completos aunque el eje corra fuera del territorio, más el
eje principal completo del río Uruguay (MAIN_RIV) dentro del bbox.
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
DIST_MAX_NOMBRE_M = 300

CRS_WFS_DINAGUA = "EPSG:32721"
CRS_METRICO = "EPSG:32721"


def leer_wfs_geojson(path: Path) -> gpd.GeoDataFrame:
    """Lee un GeoJSON del WFS de DINAGUA corrigiendo el CRS: el servidor emite
    UTM 21S pero lo declara como 4326; se detecta por magnitud de coordenadas."""
    gdf = gpd.read_file(path)
    minx, _, _, maxy = gdf.total_bounds
    if abs(minx) > 180 or abs(maxy) > 90:
        gdf = gdf.set_crs(CRS_WFS_DINAGUA, allow_override=True)
    elif gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs("EPSG:4326")


def cargar_uruguay_buffer() -> gpd.GeoSeries:
    deptos = leer_wfs_geojson(RAW / "departamentos.geojson")
    return gpd.GeoSeries([deptos.union_all().buffer(BUFFER_LIMITROFE_DEG)], crs="EPSG:4326")


def asignar_nombres(rios: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Join espacial con la red de cursos de DINAGUA para nombre y codigo5."""
    cursos = leer_wfs_geojson(RAW / "cursos.geojson")
    cursos = cursos[["nombre_2", "codigo5", "clase", "geometry"]].to_crs(CRS_METRICO)
    join = gpd.sjoin_nearest(
        rios.to_crs(CRS_METRICO),
        cursos,
        max_distance=DIST_MAX_NOMBRE_M,
        distance_col="dist_nombre_m",
        how="left",
    )
    join = join[~join.index.duplicated(keep="first")]
    rios = rios.copy()
    rios["nombre"] = join["nombre_2"]
    rios["codigo5"] = join["codigo5"].astype("Int64")
    con_nombre = rios["nombre"].notna().sum()
    log.info("nombres asignados: %d/%d tramos", con_nombre, len(rios))
    return rios


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
    en_buffer = rios.geometry.intersects(uy.iloc[0])
    # El eje del bajo río Uruguay corre lejos de la costa (islas del lado
    # argentino) y queda fuera del buffer; se lo recupera por área drenada.
    # El techo excluye los tramos del eje Paraná/Río de la Plata (>2.5M km²)
    # que entran por la esquina SO del bbox: el estuario no se dibuja como río.
    eje_uruguay = rios["UPLAND_SKM"].between(150_000, 1_000_000)
    rios = rios[en_buffer | eje_uruguay]
    log.info("dentro de Uruguay+buffer: %d tramos (+%d del eje del río Uruguay)",
             en_buffer.sum(), (eje_uruguay & ~en_buffer).sum())

    rios = rios[rios["UPLAND_SKM"] >= UMBRAL_UPLAND_SKM].copy()
    log.info("tras umbral UPLAND_SKM >= %d: %d tramos", UMBRAL_UPLAND_SKM, len(rios))

    rios = rios[[
        "HYRIV_ID", "NEXT_DOWN", "MAIN_RIV", "LENGTH_KM",
        "UPLAND_SKM", "DIS_AV_CMS", "ORD_STRA", "geometry",
    ]]
    rios = asignar_nombres(rios)
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
