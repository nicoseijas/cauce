"""Puntos de referencia del mapa: nombres de departamentos y capitales.

Departamentos: capa WFS de DINAGUA (data/raw/departamentos.geojson),
un punto interior representativo por polígono con el nombre en tipo título.
Capitales: Natural Earth 1:10m populated places (dominio público),
capitales Admin-0 y Admin-1 de Uruguay.
Salidas: web/public/data/departamentos_nombres.geojson y capitales.geojson
"""

import io
import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import pyogrio
import requests

from build_red import leer_wfs_geojson

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "web" / "public" / "data"
NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip"


def nombre_titulo(mayusculas: str) -> str:
    return mayusculas.title().replace(" Y ", " y ").replace(" De ", " de ")


def exportar_departamentos() -> None:
    deptos = leer_wfs_geojson(RAW / "departamentos.geojson")
    puntos = gpd.GeoDataFrame(
        {"nombre": deptos["departamento"].map(nombre_titulo)},
        geometry=deptos.representative_point(),
        crs=deptos.crs,
    )
    out = OUT / "departamentos_nombres.geojson"
    pyogrio.write_dataframe(
        puntos, out, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "3", "RFC7946": "YES"},
    )
    log.info("guardado %s: %d departamentos", out, len(puntos))


def exportar_capitales() -> None:
    shp_dir = RAW / "ne_10m_populated_places"
    if not shp_dir.exists():
        log.info("descargando Natural Earth populated places...")
        r = requests.get(NE_URL, timeout=180)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(shp_dir)

    lugares = gpd.read_file(shp_dir / "ne_10m_populated_places.shp")
    cap = lugares[
        (lugares["ADM0NAME"] == "Uruguay")
        & lugares["FEATURECLA"].str.startswith(("Admin-0 capital", "Admin-1 capital"))
        # Natural Earth etiqueta Punta del Este como capital Admin-1;
        # la capital de Maldonado es Maldonado.
        & (lugares["NAME"] != "Punta del Este")
    ]
    cap = gpd.GeoDataFrame(
        {
            "nombre": cap["NAME"],
            "capital_pais": (cap["FEATURECLA"].str.startswith("Admin-0")).astype(int),
            "pob": cap["POP_MAX"].astype(int),
        },
        geometry=cap.geometry,
        crs=cap.crs,
    ).sort_values("pob", ascending=False)
    if len(cap) < 19:
        log.warning("solo %d capitales en Natural Earth (se esperaban 19): %s",
                    len(cap), sorted(cap["nombre"]))
    out = OUT / "capitales.geojson"
    pyogrio.write_dataframe(
        cap, out, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "3", "RFC7946": "YES"},
    )
    log.info("guardado %s: %d capitales", out, len(cap))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    exportar_departamentos()
    exportar_capitales()


if __name__ == "__main__":
    main()
