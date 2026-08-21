"""Cuencas nivel 2 (DINAGUA) que contienen una estación de lluvia.

El cruce lluvia→creciente resalta la subcuenca (dissolve por `scp2`) de cada
estación con acumulados extremos como aviso de atención — nunca como mancha
inferida (AGENTS.md). Solo se exportan las cuencas con estación: fuera de
ellas no hay dato de lluvia y no puede haber aviso.

Correr localmente cuando cambie la lista de estaciones de lluvia; la salida
va commiteada (el cron no tiene geopandas).
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "raw" / "cuencas_nivel2.geojson"
SALIDA = RAIZ / "web" / "public" / "data" / "cuencas_lluvia.geojson"

# clave = como identifica la estación el estado_actual.json:
# INUMET usa `nombre` sin el sufijo " G3"; ANA usa el `id`.
ESTACIONES = {
    "Aeropuerto Melilla": (-34.7892, -56.2647),
    "Artigas": (-30.3990, -56.5120),
    "Colonia": (-34.4564, -57.8456),
    "Mercedes": (-33.2524, -58.0672),
    "Paso de los Toros": (-32.8043, -56.5320),
    "Rocha": (-34.4884, -54.3122),
    "Salto": (-31.4382, -57.9836),
    "ana-77500000": (-30.3844, -56.4656),
    "ana-88260000": (-32.5194, -53.3494),
    "INIA La Estanzuela": (-34.3372, -57.6922),
    "INIA Las Brujas": (-34.67, -56.34),
    "INIA Tacuarembó": (-31.7089, -55.8267),
    "INIA Salto Grande": (-31.2728, -57.8908),
    "INIA Treinta y Tres": (-33.2750, -54.1722),
}


def main() -> None:
    # la capa WFS declara EPSG:4326 pero las coordenadas son UTM 21S
    g = (
        gpd.read_file(ENTRADA)
        .set_crs(32721, allow_override=True)
        .to_crs(4326)
    )
    # primero el polígono puntual que contiene cada estación y recién después
    # el dissolve por nombre: la capa trae polígonos gigantes mal etiquetados
    # (id 32, 210.000 km² como "RÍO CUAREIM") que un dissolve global absorbería
    puntos = {clave: Point(lon, lat) for clave, (lat, lon) in ESTACIONES.items()}
    elegidos = g[g.geometry.apply(lambda geo: any(geo.contains(p) for p in puntos.values()))]
    cuencas = elegidos.dissolve(by="scp2").reset_index()

    features = []
    for _, c in cuencas.iterrows():
        dentro = [
            clave for clave, p in puntos.items() if c.geometry.contains(p)
        ]
        km2 = gpd.GeoSeries([c.geometry], crs=4326).to_crs(32721).area.iloc[0] / 1e6
        geom = c.geometry.simplify(0.003)
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(gpd.GeoSeries([geom]).to_json())[
                    "features"
                ][0]["geometry"],
                "properties": {
                    "cuenca": c.scp2,
                    "area_km2": round(km2),
                    "estaciones": dentro,
                },
            }
        )

    SALIDA.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    for f in features:
        p = f["properties"]
        print(f"{p['cuenca']}  {p['area_km2']:,} km²  <- {p['estaciones']}")
    print(f"{len(features)} cuencas, {SALIDA.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
