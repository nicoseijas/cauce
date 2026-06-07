"""Prepara las capas del modo creciente para la web.

Entrada:  data/raw/curvas_tr.geojson, curvas_cri.geojson,
          problemas_drenaje.geojson, localidades_amenazas.geojson
Salida:   web/public/data/inundacion_tr.geojson   (manchas por período de retorno)
          web/public/data/inundacion_cri.geojson  (inundaciones registradas)
          web/public/data/drenaje.geojson         (conflictos de drenaje + amenazas)

`periodo` es el período de retorno en años parseado de `tipo_curva`;
CMP (crecida máxima probable) se codifica como 9999.
"""

import logging
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from build_red import leer_wfs_geojson

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
WEB = ROOT / "web" / "public" / "data"
CRS_METRICO = "EPSG:32721"

TOLERANCIA_M = 8


def parsear_periodo(tipo: str | None) -> int | None:
    if not tipo:
        return None
    if "CMP" in tipo.upper():
        return 9999
    m = re.search(r"(\d+)", tipo)
    return int(m.group(1)) if m else None


def simplificar(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.to_crs(CRS_METRICO)
    gdf["geometry"] = gdf.geometry.simplify(TOLERANCIA_M, preserve_topology=True)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    return gdf.to_crs("EPSG:4326")


def exportar(gdf: gpd.GeoDataFrame, nombre: str) -> None:
    out = WEB / nombre
    pyogrio.write_dataframe(
        gdf, out, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "5", "RFC7946": "YES"},
    )
    log.info("%s: %d features, %.2f MB", out.name, len(gdf), out.stat().st_size / 1e6)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    tr = leer_wfs_geojson(RAW / "curvas_tr.geojson")
    tr["periodo"] = tr["tipo_curva"].map(parsear_periodo)
    tr["localidad_cod"] = tr["nombre"].str.split("_").str[0]
    tr = tr[tr["periodo"].notna()].copy()
    tr["periodo"] = tr["periodo"].astype(int)
    tr = simplificar(tr[[
        "nombre", "curso", "tipo_curva", "periodo", "localidad_cod",
        "cota_local", "cota_oficial", "fuentes", "geometry",
    ]])
    exportar(tr, "inundacion_tr.geojson")

    cri = leer_wfs_geojson(RAW / "curvas_cri.geojson")
    cri["fecha_evento"] = pd.to_datetime(
        cri["fecha_evento"], errors="coerce", utc=True
    ).dt.strftime("%Y-%m-%d")
    cri = simplificar(cri[[
        "nombre", "curso", "fecha_evento", "cota_local", "cota_oficial",
        "fuentes", "geometry",
    ]])
    exportar(cri, "inundacion_cri.geojson")

    dre = leer_wfs_geojson(RAW / "problemas_drenaje.geojson")
    dre = simplificar(dre[[
        "departamento", "localidad", "tipo_conflicto",
        "descripcion_conflicto", "geometry",
    ]])
    exportar(dre, "drenaje.geojson")

    ame = leer_wfs_geojson(RAW / "localidades_amenazas.geojson")
    ame = ame[[
        "localidad", "departamento", "ribera", "canadas", "drenaje",
        "presas", "accesibilidad", "costas", "total_tipos_amenaza", "geometry",
    ]]
    ame = ame[ame["total_tipos_amenaza"] > 0]
    exportar(ame, "amenazas.geojson")


if __name__ == "__main__":
    main()
