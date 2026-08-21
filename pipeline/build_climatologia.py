"""Caudal medio de largo plazo por tramo, según la climatología de DINAGUA.

Reemplaza la referencia de "caudal normal" del mapa. Hasta ahora era el
`DIS_AV_CMS` de HydroRIVERS, que sale del modelo global WaterGAP con clima
1971–2000 y resulta casi uniforme sobre Uruguay. DINAGUA publica el caudal
específico medio (L/s/km²) de cada subcuenca de nivel 2 en la Tabla 1 de
«Regionalización de estadísticas de caudales» (actualización octubre 2025),
período 1980–2010:
https://www.gub.uy/ministerio-ambiente/politicas-y-gestion/publicaciones-hidrologia

El estudio advierte que los valores son del interior de cada subcuenca
incremental y que una sección aguas abajo de varias subcuencas exige ponderar
por área. Eso es lo que hace este script: asigna a cada tramo la subcuenca que
lo contiene, deriva el área incremental desde la topología de HydroRIVERS y
acumula aguas abajo, de modo que

    Q(tramo) = Σ (área incremental aguas arriba × q de su subcuenca)

Los tramos cuya cuenca de aporte entra al país desde Brasil o Argentina quedan
sin valor: la Tabla 1 solo cubre territorio uruguayo y aplicarla al área total
subestimaría el caudal. Esos tramos conservan el valor de HydroRIVERS.

Salidas:
- data/processed/climatologia.json — por HYRIV_ID, el caudal medio en m³/s, el
  valor de HydroRIVERS para comparar y la cobertura nacional de la cuenca.
- la propiedad `q_medio_uy` en red_uy.geojson (processed y web/public), que es
  la referencia que usan el ancho del río y el factor "× la media".
"""

import argparse
import collections
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import geopandas as gpd

from build_red import leer_wfs_geojson

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
PROCESADO = ROOT / "data" / "processed"
REFERENCIA = ROOT / "data" / "referencia" / "caudal_especifico_dinagua.csv"
RED = PROCESADO / "red_uy.geojson"

CRS_METRICO = "EPSG:32721"
# Debajo de esta fracción del área de HydroRIVERS, la cuenca de aporte entra
# desde fuera del país y la climatología nacional no la representa.
COBERTURA_MINIMA = 0.80
# La red está recortada a Uruguay y filtrada en 100 km², así que una cabecera
# real ronda esa área (p95 = 213 km²). Un tramo sin nada aguas arriba y con
# mucha más área drena territorio extranjero: entra ya formado desde Brasil o
# Argentina y su aporte no lo describe la Tabla 1.
AREA_CABECERA_MAX_KM2 = 400.0
# La Tabla 1 describe solo territorio uruguayo: sus 48 filas suman 177.168 km²
# y los polígonos URU de la capa de cuencas suman 176.031. El resto de la capa
# (porciones brasileñas y argentinas de las cuencas compartidas, y un polígono
# "A_B" de 209.288 km² rotulado Cuareim que desbordaría el join) queda fuera.
PAIS_TABLA1 = "URU"


def leer_caudal_especifico() -> dict[int, float]:
    with REFERENCIA.open(encoding="utf-8") as f:
        return {int(r["cuenca_n2"]): float(r["anual"]) for r in csv.DictReader(f)}


def asignar_subcuenca(red: gpd.GeoDataFrame, cuencas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Subcuenca de nivel 2 de cada tramo, por el punto medio de su geometría."""
    puntos = red.copy()
    puntos["geometry"] = red.geometry.interpolate(0.5, normalized=True)
    unido = gpd.sjoin(puntos, cuencas[["c2", "geometry"]], how="left", predicate="within")
    # un punto sobre un límite puede caer en dos polígonos
    unido = unido[~unido.index.duplicated(keep="first")]
    return unido["c2"]


def areas_incrementales(red: gpd.GeoDataFrame) -> dict[int, float]:
    """Área propia de cada tramo: la suya menos la de los tramos que le entran.

    Un tramo que entra al país ya formado no tiene aguas arriba dentro de la
    red recortada, así que la resta le dejaría toda su cuenca extranjera como
    área propia. Esos aportan cero: la cobertura resultante avisa río abajo.
    """
    aguas_arriba = collections.defaultdict(list)
    for hid, siguiente in zip(red["HYRIV_ID"], red["NEXT_DOWN"]):
        if siguiente:
            aguas_arriba[siguiente].append(hid)
    area = dict(zip(red["HYRIV_ID"], red["UPLAND_SKM"]))
    incremental = {}
    for hid, a in area.items():
        arriba = aguas_arriba.get(hid, ())
        if not arriba and a > AREA_CABECERA_MAX_KM2:
            incremental[hid] = 0.0
        else:
            incremental[hid] = max(0.0, a - sum(area.get(h, 0.0) for h in arriba))
    return incremental


def acumular(red: gpd.GeoDataFrame, incremental: dict[int, float],
             q_local: dict[int, float]) -> tuple[dict[int, float], dict[int, float]]:
    """Recorre la red de cabecera a desembocadura sumando aporte y área.

    Devuelve, por tramo, el caudal acumulado en L/s y el área acumulada en km².
    """
    hijos = collections.defaultdict(list)
    ids = list(red["HYRIV_ID"])
    siguiente = dict(zip(red["HYRIV_ID"], red["NEXT_DOWN"]))
    for hid, sig in siguiente.items():
        if sig in incremental:
            hijos[sig].append(hid)

    grado = {hid: len(hijos.get(hid, ())) for hid in ids}
    cola = collections.deque(hid for hid in ids if grado[hid] == 0)
    aporte: dict[int, float] = {}
    area: dict[int, float] = {}
    while cola:
        hid = cola.popleft()
        propio = incremental[hid]
        q = q_local.get(hid)
        aporte[hid] = (propio * q if q is not None else 0.0) + sum(
            aporte[h] for h in hijos.get(hid, ()))
        area[hid] = (propio if q is not None else 0.0) + sum(
            area[h] for h in hijos.get(hid, ()))
        sig = siguiente.get(hid)
        if sig in grado:
            grado[sig] -= 1
            if grado[sig] == 0:
                cola.append(sig)
    faltantes = [hid for hid in ids if hid not in aporte]
    if faltantes:
        log.warning("%d tramos en ciclo topológico, sin acumular", len(faltantes))
    return aporte, area


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--salida", type=Path, default=PROCESADO / "climatologia.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    q_subcuenca = leer_caudal_especifico()
    red = gpd.read_file(RED)
    cuencas = leer_wfs_geojson(RAW / "cuencas_nivel2.geojson")
    # el WFS trae 44 de 277 polígonos con anillos autointersectados
    invalidas = int((~cuencas.geometry.is_valid).sum())
    if invalidas:
        log.info("reparando %d polígonos inválidos del WFS", invalidas)
        cuencas["geometry"] = cuencas.geometry.make_valid()
    log.info("red: %d tramos | cuencas nivel 2: %d polígonos | Tabla 1: %d subcuencas",
             len(red), len(cuencas), len(q_subcuenca))

    nacionales = cuencas[cuencas["cod_pais"] == PAIS_TABLA1]
    log.info("cuencas en territorio uruguayo: %d de %d polígonos",
             len(nacionales), len(cuencas))
    red_m = red.to_crs(CRS_METRICO)
    c2 = asignar_subcuenca(red_m, nacionales.to_crs(CRS_METRICO))
    red["c2"] = c2.values
    sin_c2 = int(red["c2"].isna().sum())
    fuera_tabla = sorted({int(v) for v in red["c2"].dropna().unique()} - set(q_subcuenca))
    log.info("tramos sin subcuenca: %d | subcuencas sin valor en Tabla 1: %s",
             sin_c2, fuera_tabla or "ninguna")

    q_local = {
        hid: q_subcuenca[int(v)]
        for hid, v in zip(red["HYRIV_ID"], red["c2"])
        if v == v and int(v) in q_subcuenca
    }
    incremental = areas_incrementales(red)
    aporte, area_acum = acumular(red, incremental, q_local)

    salida, incompletos = {}, 0
    for hid, upland, dis in zip(red["HYRIV_ID"], red["UPLAND_SKM"], red["DIS_AV_CMS"]):
        a = area_acum.get(hid, 0.0)
        if not upland or a / upland < COBERTURA_MINIMA:
            incompletos += 1
            continue
        salida[str(int(hid))] = {
            "q_dinagua": round(aporte[hid] / 1000.0, 3),
            "q_hydrorivers": round(float(dis or 0.0), 3),
            "area_km2": round(a, 1),
            "cobertura": round(a / upland, 3),
        }
    log.info("tramos con climatología DINAGUA: %d | sin cobertura nacional: %d",
             len(salida), incompletos)

    razones = sorted(v["q_hydrorivers"] / v["q_dinagua"]
                     for v in salida.values() if v["q_dinagua"] > 0.01)
    if razones:
        n = len(razones)
        log.info("HydroRIVERS / DINAGUA: p10 %.2f  mediana %.2f  p90 %.2f  (n=%d)",
                 razones[n // 10], razones[n // 2], razones[9 * n // 10], n)

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(salida), encoding="utf-8")
    log.info("guardado %s", args.salida)

    escribir_en_red(salida)


def escribir_en_red(climatologia: dict[str, dict]) -> None:
    """Agrega `q_medio_uy` a la red, sin tocar el resto del GeoJSON."""
    fuente = json.loads(RED.read_text(encoding="utf-8"))
    tocados = 0
    for f in fuente["features"]:
        p = f["properties"]
        p.pop("q_medio_uy", None)
        v = climatologia.get(str(int(p["HYRIV_ID"])))
        if v:
            p["q_medio_uy"] = v["q_dinagua"]
            tocados += 1
    texto = json.dumps(fuente, separators=(",", ":"))
    for destino in (RED, ROOT / "web" / "public" / "data" / "red_uy.geojson"):
        destino.write_text(texto, encoding="utf-8")
    log.info("red actualizada: %d de %d tramos con q_medio_uy",
             tocados, len(fuente["features"]))


if __name__ == "__main__":
    main()
