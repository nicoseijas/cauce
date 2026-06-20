"""Genera el contexto geográfico de países vecinos (Argentina, Brasil).

Fuente: Natural Earth 1:10m admin_0 (dominio público). La escala 1:50m no
sirve: reparte el Río de la Plata como territorio de los países y el estuario
desaparece; la 1:10m lo traza como agua.
Salida: web/public/data/vecinos.geojson (recortado al entorno de Uruguay).
"""

import io
import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import pyogrio
import requests
from shapely.geometry import box

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
BBOX_CONTEXTO = box(-63.5, -38.5, -47.5, -25.5)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    shp_dir = RAW / "ne_10m_admin_0_countries"
    if not shp_dir.exists():
        log.info("descargando Natural Earth 10m...")
        r = requests.get(NE_URL, timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(shp_dir)

    paises = gpd.read_file(shp_dir / "ne_10m_admin_0_countries.shp")
    vecinos = paises[paises["ADMIN"].isin(["Argentina", "Brazil"])]
    vecinos = gpd.clip(vecinos, BBOX_CONTEXTO)
    vecinos = vecinos[["ADMIN", "geometry"]].rename(columns={"ADMIN": "pais"})
    vecinos["geometry"] = vecinos.geometry.simplify(0.01, preserve_topology=True)

    out = ROOT / "web" / "public" / "data" / "vecinos.geojson"
    pyogrio.write_dataframe(
        vecinos, out, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "3", "RFC7946": "YES"},
    )
    log.info("guardado %s (%.0f KB)", out, out.stat().st_size / 1024)


if __name__ == "__main__":
    main()
