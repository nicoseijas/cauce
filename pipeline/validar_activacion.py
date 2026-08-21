"""Valida la regla de activación de manchas contra eventos históricos.

Verdad de terreno: `curvas_cri`, el registro oficial de inundaciones ocurridas
(una fecha por evento). Observaciones: los CSV anuales de nivel que DINAGUA
publica en CKAN (2017–2019), única serie histórica disponible de las estaciones
uruguayas — el WFS solo sirve el último valor.

Para cada localidad con umbral en `activacion.json` reproduce la regla del sitio
día a día sobre el año elegido y la contrasta con los eventos registrados. Emite
control de calidad de la serie, aciertos y fallos por evento, y días con
activación sin evento registrado.

Sobre esto último: la ausencia de un polígono CRI no prueba que no hubo
inundación — el registro tiene 82 polígonos para todo el país desde 1941. Esos
días son una cota superior de la tasa de falsa alarma, no falsas alarmas
confirmadas.
"""

import argparse
import collections
import csv
import datetime as dt
import io
import json
import logging
import statistics as st
import urllib.request
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger(__name__)

Lectura = tuple[str, float, dt.datetime]
Serie = list[tuple[dt.datetime, float]]

ROOT = Path(__file__).parent.parent
DATOS = ROOT / "web" / "public" / "data"

# Recursos CKAN "DINAGUA - Mediciones de nivel de agua" (licencia odc-uy).
CSV_CKAN = {
    2017: "https://catalogodatos.gub.uy/dataset/03d936f2-5dc8-4e66-b936-5da8f2a7fdd1/"
          "resource/4a048882-ef6c-4fa7-b0ce-87207aa7741a/download/lecturas_anuales_nivel_2017.csv",
    2018: "https://catalogodatos.gub.uy/dataset/4ba2cad8-adc3-4e60-82d5-8183ce23717f/"
          "resource/155d7cf9-7744-4ecc-a097-7f5fb776d175/download/lecturas_anuales_nivel_2018.csv",
    2019: "https://catalogodatos.gub.uy/dataset/11b9f183-bbc4-4e5d-8047-b5647cf041cc/"
          "resource/3f035e36-da7e-4f3f-a707-d5c54a83e022/download/lecturas_anuales_nivel_2019.csv",
}

# El nombre de estación difiere entre `activacion.json` (WFS) y el CSV de CKAN.
EQUIV_ESTACION = {
    "Santa Lucia R-11": "Santa Lucia (Ruta 11)",
    "Florida - Puente R.5": "Florida (Puente Ruta 5)",
    "Carmelo - Atracadero": "Carmelo (Atracadero)",
    "Dársena Higueritas": "Dársena Higueritas",
    "Mercedes (Puerto)": "Mercedes (Puerto)",
    "Paysandú": "Paysandú",
    "La Charqueada": "La Charqueada",
    "Dolores": "Dolores",
    "Constitución": "Constitución",
    "Juan Lacaze": "Juan Lacaze",
    "Peaje Solís": "Peaje Solís",
    "Paso de los Toros": "Paso de los Toros",
}

SALTO_MIN_M = 1.0
VENTANA_ESCALON = 48
DESVIO_MAX_M = 3.0
NIVEL_IMPOSIBLE_M = (-2.0, 30.0)
# El registro CRI data el evento, no el instante del pico.
VENTANA_EVENTO_DIAS = 3


def leer_csv_nivel(path: Path) -> Iterator[Lectura]:
    """Lecturas (estación, valor, fecha) del CSV anual de DINAGUA.

    Los archivos vienen en latin-1 y con el escapado roto de dos maneras
    distintas: en 2019 ~2,4 % de las filas traen los tres primeros campos
    colapsados en uno ("0180,Dolores,nivel"); en 2018 la fila entera viene
    envuelta en comillas con las internas duplicadas. En ambos casos alcanza
    con volver a parsear el campo colapsado como CSV.
    """
    with io.open(path, encoding="latin-1", newline="") as f:
        for fila in csv.reader(f):
            if not fila or fila[0].startswith("Estacion"):
                continue
            if "," in fila[0]:
                fila = next(csv.reader([fila[0]])) + fila[1:]
            if len(fila) < 6:
                continue
            _, estacion, sensor, valor, unidad, fecha = fila[:6]
            if sensor != "nivel" or unidad != "metros":
                continue
            try:
                yield estacion, float(valor), dt.datetime.strptime(fecha, "%Y-%m-%d %H:%M")
            except ValueError:
                continue


def detectar_escalones(serie: Serie) -> list[tuple[dt.datetime, float]]:
    """Escalones persistentes: un salto brusco cuya mediana no vuelve."""
    escalones = []
    for i in range(1, len(serie)):
        if (serie[i][0] - serie[i - 1][0]).total_seconds() > 7200:
            continue
        if abs(serie[i][1] - serie[i - 1][1]) <= SALTO_MIN_M:
            continue
        antes = [v for _, v in serie[max(0, i - VENTANA_ESCALON):i]]
        despues = [v for _, v in serie[i:i + VENTANA_ESCALON]]
        if len(antes) < 5 or len(despues) < 5:
            continue
        d = st.median(despues) - st.median(antes)
        reciente = escalones and serie[i][0] - escalones[-1][0] <= dt.timedelta(days=1)
        if abs(d) > SALTO_MIN_M and not reciente:
            escalones.append((serie[i][0], d))
    return escalones


def segmentos_confiables(
    serie: Serie, escalones: list[tuple[dt.datetime, float]],
) -> tuple[Serie, list[tuple[dt.datetime, dt.datetime, int]]]:
    """Descarta los tramos cuyo marco de referencia no es el de la estación.

    Un escalón persistente significa que el cero de la regla cambió, y un
    desplazamiento estimado a partir del propio salto no es verificable: si se
    aplica como corrección, el tramo movido genera activaciones inventadas.
    Se toma como referencia la mediana del tramo más largo y se descartan los
    tramos que se apartan de ella más que DESVIO_MAX_M.

    Limitación: una deriva lenta del sensor no produce escalón y sobrevive a
    este filtro.
    """
    if not escalones:
        return serie, []
    cortes = [f for f, _ in escalones]
    tramos, i = [], 0
    for corte in cortes + [None]:
        j = len(serie) if corte is None else next(
            (k for k in range(i, len(serie)) if serie[k][0] >= corte), len(serie))
        if j > i:
            tramos.append(serie[i:j])
        i = j
    referencia = st.median([v for _, v in max(tramos, key=len)])
    buenos, descartados = [], []
    for t in tramos:
        if abs(st.median([v for _, v in t]) - referencia) <= DESVIO_MAX_M:
            buenos.extend(t)
        else:
            descartados.append((t[0][0], t[-1][0], len(t)))
    return buenos, descartados


def cargar_series(path: Path, nombres: set[str]) -> dict[str, Serie]:
    series = collections.defaultdict(list)
    descartados = collections.Counter()
    for estacion, valor, fecha in leer_csv_nivel(path):
        if estacion not in nombres:
            continue
        if not NIVEL_IMPOSIBLE_M[0] <= valor <= NIVEL_IMPOSIBLE_M[1]:
            descartados[estacion] += 1
            continue
        series[estacion].append((fecha, valor))
    for estacion, n in descartados.items():
        log.warning("  %-30s %d lecturas fuera de rango físico descartadas", estacion[:30], n)
    for s in series.values():
        s.sort()
    return series


def maximo_diario(serie: Serie) -> dict[dt.date, float]:
    por_dia = collections.defaultdict(list)
    for fecha, valor in serie:
        por_dia[fecha.date()].append(valor)
    return {d: max(v) for d, v in por_dia.items()}


def periodo_disparado(nivel: float, umbrales: list[dict]) -> int:
    for u in sorted(umbrales, key=lambda x: -x["nivel"]):
        if nivel >= u["nivel"]:
            return u["periodo"]
    return 0


def eventos_cri(anio: int) -> dict[str, set[dt.date]]:
    cri = json.loads((DATOS / "inundacion_cri.geojson").read_text(encoding="utf-8"))
    por_localidad = collections.defaultdict(set)
    for f in cri["features"]:
        fecha = f["properties"].get("fecha_evento")
        nombre = f["properties"].get("nombre") or ""
        if fecha and fecha.startswith(str(anio)):
            por_localidad[nombre.split("_")[0]].add(dt.date.fromisoformat(fecha))
    return por_localidad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anio", type=int, default=2019, choices=sorted(CSV_CKAN))
    ap.add_argument("--csv", type=Path, help="CSV ya descargado; si falta, se baja de CKAN")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    path = args.csv
    if path is None:
        path = ROOT / "data" / "raw" / f"lecturas_anuales_nivel_{args.anio}.csv"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            log.info("descargando %s", CSV_CKAN[args.anio])
            urllib.request.urlretrieve(CSV_CKAN[args.anio], path)

    activacion = json.loads((DATOS / "activacion.json").read_text(encoding="utf-8"))
    eventos = eventos_cri(args.anio)
    nombres = {EQUIV_ESTACION[a["estacion"]] for a in activacion.values()
               if a["estacion"] in EQUIV_ESTACION}

    log.info("== control de calidad ==")
    series = cargar_series(path, nombres)
    for nombre, serie in sorted(series.items()):
        escalones = detectar_escalones(serie)
        if not escalones:
            log.info("  %-30s sin escalones (n=%d)", nombre[:30], len(serie))
            continue
        for fecha, salto in escalones:
            log.info("  %-30s escalón %+.2f m el %s", nombre[:30], salto, fecha)
        series[nombre], descartados = segmentos_confiables(serie, escalones)
        for ini, fin, n in descartados:
            log.info("  %-30s   descartado %s .. %s (%d lecturas)",
                     "", ini.date(), fin.date(), n)

    log.info("\n== eventos registrados ==")
    aciertos = fallos = 0
    for cod in sorted(activacion):
        a = activacion[cod]
        nombre = EQUIV_ESTACION.get(a["estacion"])
        if nombre not in series:
            log.info("  %-8s sin serie %d para %s", cod, args.anio, a["estacion"])
            continue
        diario = maximo_diario(series[nombre])
        for evento in sorted(eventos.get(cod, ())):
            ventana = [v for d, v in diario.items()
                       if abs((d - evento).days) <= VENTANA_EVENTO_DIAS]
            if not ventana:
                log.info("  %-8s %s  sin cobertura en la ventana", cod, evento)
                continue
            pico = max(ventana)
            tr = periodo_disparado(pico, a["umbrales"])
            if tr:
                aciertos += 1
            else:
                fallos += 1
            log.info("  %-8s %s  pico %.2f m  ->  %s", cod, evento, pico,
                     "activa TR%d" % tr if tr else "NO activa (fallo)")
    log.info("  aciertos %d / fallos %d", aciertos, fallos)

    log.info("\n== días con activación sin evento registrado ==")
    log.info("  (cota superior de falsa alarma: el registro CRI es incompleto)")
    for cod in sorted(activacion):
        a = activacion[cod]
        nombre = EQUIV_ESTACION.get(a["estacion"])
        if nombre not in series or eventos.get(cod):
            continue
        diario = maximo_diario(series[nombre])
        activos = [d for d, v in diario.items() if periodo_disparado(v, a["umbrales"])]
        if activos:
            log.info("  %-8s %-26s %3d de %3d días (%.0f %%)", cod, nombre[:26],
                     len(activos), len(diario), 100 * len(activos) / len(diario))

    log.info("\n== separación entre umbrales consecutivos ==")
    log.info("  (la incertidumbre declarada del umbral es ±1 m)")
    for cod in sorted(activacion):
        us = sorted(activacion[cod]["umbrales"], key=lambda u: u["nivel"])
        for a, b in zip(us, us[1:]):
            sep = b["nivel"] - a["nivel"]
            if sep < 2.0:
                log.info("  %-8s TR%-5d %.2f m  vs  TR%-5d %.2f m  ->  %.2f m",
                         cod, a["periodo"], a["nivel"], b["periodo"], b["nivel"], sep)


if __name__ == "__main__":
    main()
