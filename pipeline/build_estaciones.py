"""Genera el mapping estático estación -> tramo HydroRIVERS.

Entrada:  data/raw/catalogo_estaciones.geojson + data/processed/red_uy.geojson
Salida:   data/processed/estaciones.geojson (también copiado a web/public/data/)

Corre junto con build_red.py y build_climatologia.py (no en el cron):
build_estado.py usa este archivo para no depender de geopandas en CI.

El caudal medio de referencia (`q_medio`), con el que se calcula el factor
"× la media", sale de la climatología de DINAGUA cuando el tramo la tiene; si
no, del `DIS_AV_CMS` de HydroRIVERS. El campo `q_medio_fuente` lo declara.

Incluye una pseudo-estación para la represa de Salto Grande: su caudal
(turbinado + vertido) se scrapea en build_estado.py y el join aquí le asigna
el tramo y caudal medio del río Uruguay en ese punto.
"""

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CRS_METRICO = "EPSG:32721"

DIST_MAX_M = 1500
RATIO_AREA_OK = (0.5, 2.0)

SALTO_GRANDE = {
    "id": -1,
    "Código": "SG",
    "Nombre": "Represa Salto Grande",
    "Curso": "Río Uruguay",
    "Tipo": "Represa",
    "LAT": -31.2758,
    "LONG": -57.9394,
    "Area (km2)": 244000.0,
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    est = gpd.read_file(ROOT / "data" / "raw" / "catalogo_estaciones.geojson")
    est = pd.concat([est, pd.DataFrame([SALTO_GRANDE])], ignore_index=True)
    est = gpd.GeoDataFrame(
        est, geometry=gpd.points_from_xy(est["LONG"], est["LAT"]), crs="EPSG:4326"
    )

    red = gpd.read_file(ROOT / "data" / "processed" / "red_uy.geojson")

    join = gpd.sjoin_nearest(
        est.to_crs(CRS_METRICO),
        red.to_crs(CRS_METRICO)[["HYRIV_ID", "DIS_AV_CMS", "UPLAND_SKM", "codigo5", "geometry"]],
        distance_col="dist_m",
        how="left",
    )
    join = join[~join.index.duplicated(keep="first")]

    climatologia = ROOT / "data" / "processed" / "climatologia.json"
    if climatologia.exists():
        q_dinagua = {int(k): v["q_dinagua"]
                     for k, v in json.loads(climatologia.read_text(encoding="utf-8")).items()}
        propio = join["HYRIV_ID"].map(lambda h: q_dinagua.get(int(h)) if h == h else None)
        join["q_medio_fuente"] = propio.notna().map({True: "DINAGUA", False: "HydroRIVERS"})
        join["DIS_AV_CMS"] = propio.fillna(join["DIS_AV_CMS"])
        log.info("caudal medio de DINAGUA en %d de %d estaciones",
                 int(propio.notna().sum()), len(join))
    else:
        join["q_medio_fuente"] = "HydroRIVERS"
        log.warning("sin %s: el caudal medio queda en HydroRIVERS", climatologia)

    ratio = join["UPLAND_SKM"] / join["Area (km2)"]
    join["join_ok"] = (
        (join["dist_m"] < DIST_MAX_M)
        & ratio.between(*RATIO_AREA_OK).fillna(False)
    )

    out = join[[
        "id", "Código", "Nombre", "Curso", "Tipo", "Area (km2)", "Cota Cero (Wh)",
        "HYRIV_ID", "DIS_AV_CMS", "q_medio_fuente", "codigo5", "dist_m", "join_ok",
        "geometry",
    ]].rename(columns={
        "Código": "codigo", "Nombre": "nombre", "Curso": "curso", "Tipo": "tipo",
        "Area (km2)": "area_km2", "Cota Cero (Wh)": "cota_cero",
        "DIS_AV_CMS": "q_medio",
    })
    out = out.to_crs("EPSG:4326")
    out["codigo5"] = out["codigo5"].astype("Int64")

    dest = ROOT / "data" / "processed" / "estaciones.geojson"
    pyogrio.write_dataframe(
        out, dest, driver="GeoJSON",
        layer_options={"COORDINATE_PRECISION": "5", "RFC7946": "YES"},
    )
    web_dest = ROOT / "web" / "public" / "data" / "estaciones.geojson"
    web_dest.write_bytes(dest.read_bytes())
    log.info("guardado %s: %d estaciones (%d con join_ok)",
             dest, len(out), int(out["join_ok"].sum()))


if __name__ == "__main__":
    main()
