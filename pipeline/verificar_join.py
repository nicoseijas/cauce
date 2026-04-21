"""Verificación Fase 0: ¿las estaciones DINAGUA caen sobre tramos HydroRIVERS
coherentes?

Para cada estación busca el tramo más cercano de red_uy.geojson y compara el
área de cuenca declarada por DINAGUA contra UPLAND_SKM del tramo. Ratios
cercanos a 1 => el join espacial es viable.
"""

import logging
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CRS_METRICO = "EPSG:32721"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    est = gpd.read_file(ROOT / "data" / "raw" / "catalogo_estaciones.geojson")
    est = est.set_geometry(
        gpd.points_from_xy(est["LONG"], est["LAT"]), crs="EPSG:4326"
    )
    red = gpd.read_file(ROOT / "data" / "processed" / "red_uy.geojson")

    est_m = est.to_crs(CRS_METRICO)
    red_m = red.to_crs(CRS_METRICO)

    join = gpd.sjoin_nearest(est_m, red_m, distance_col="dist_m")

    con_area = join[join["Area (km2)"].notna() & (join["Area (km2)"] > 0)].copy()
    con_area["ratio"] = con_area["UPLAND_SKM"] / con_area["Area (km2)"]

    log.info("%-38s %-22s %8s %10s %10s %6s", "Estación", "Curso",
             "dist_m", "A_DINAGUA", "A_HydroR", "ratio")
    for _, r in con_area.sort_values("Area (km2)", ascending=False).head(20).iterrows():
        log.info("%-38s %-22s %8.0f %10.0f %10.0f %6.2f",
                 r["Nombre"][:38], str(r["Curso"])[:22], r["dist_m"],
                 r["Area (km2)"], r["UPLAND_SKM"], r["ratio"])

    ok = con_area[(con_area["dist_m"] < 1000) & con_area["ratio"].between(0.5, 2)]
    log.info("")
    log.info("estaciones con área: %d | join aceptable (dist<1km, ratio 0.5-2): %d",
             len(con_area), len(ok))
    lejos = con_area[con_area["dist_m"] >= 1000]
    if len(lejos):
        log.info("a más de 1 km del tramo más cercano: %d (revisar umbral de red)",
                 len(lejos))


if __name__ == "__main__":
    main()
