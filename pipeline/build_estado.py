"""Genera web/public/data/estado_actual.json con el estado hídrico actual.

Pensado para correr en cron (GitHub Actions): depende solo de requests +
stdlib. El mapping estación->tramo viene precalculado por build_estaciones.py.

Fuentes (cada una tolera fallos de forma independiente):
- WFS DINAGUA V_Catalogo_publica: último nivel y último caudal por estación.
- saltogrande.org/datos_horarios.php: caudal turbinado + vertido (horario).
- INA alerta.ina.gob.ar: alturas del río Uruguay con niveles oficiales de
  alerta/evacuación de Prefectura (escala local de cada estación).
- UTE CUPubNivCau: niveles observados y previsión a 7 días de niveles y
  caudales a erogar en la cuenca del río Negro (publicación diaria ~12:00).
- ANA (Brasil) telemetría: nivel/caudal cada 15 min en cuencas compartidas
  (Cuareim/Quaraí y Yaguarón/Jaguarão).
- SOHMA (Armada) meteo.armada.mil.uy: mareógrafos de Punta Lobos (bahía de
  Montevideo) y La Paloma, cada 5 min, cero local Ex Wharton.
"""

import csv
import io
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wfs

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ESTACIONES = ROOT / "web" / "public" / "data" / "estaciones.geojson"
ACTIVACION = ROOT / "web" / "public" / "data" / "activacion.json"
SALIDA = ROOT / "web" / "public" / "data" / "estado_actual.json"
HISTORICO = ROOT / "data" / "historico"
FRESCURA_MAX_ACTIVACION_H = 48

FRESCURA_MAX_CAUDAL_H = 24 * 7
FRESCURA_MAX_NIVEL_H = 24 * 7
FACTOR_CLAMP = (0.05, 20.0)
SALTO_GRANDE_URL = "https://www.saltogrande.org/datos_horarios.php"
ID_SALTO_GRANDE = -1

LLUVIA_URL = ("https://catalogodatos.gub.uy/dataset/fd896b11-4c04-4807-bae4-5373d65beea2"
              "/resource/cc785e9e-d9c8-4706-b013-9a6a5b0f7d01/download"
              "/inumet_precipitacion_acumulada_horaria.csv")
# Coordenadas aproximadas (sitio de la estación/aeropuerto); INUMET no publica
# las coordenadas exactas junto con el CSV.
ESTACIONES_INUMET = {
    "Aeropuerto Melilla G3": (-34.7892, -56.2647),
    "Artigas G3": (-30.3990, -56.5120),
    "Colonia G3": (-34.4564, -57.8456),
    "Mercedes G3": (-33.2524, -58.0672),
    "Paso de los Toros G3": (-32.8043, -56.5320),
    "Rocha G3": (-34.4884, -54.3122),
    "Salto G3": (-31.4382, -57.9836),
}

# INIA GRAS vía CKAN: acumulado diario de pluviómetro (09 a 09 h), un CSV por
# año; el recurso vigente se resuelve por package_show para sobrevivir al
# cambio de año. Coordenadas del JSON de metadatos de cada dataset.
CKAN_PACKAGE_URL = "https://catalogodatos.gub.uy/api/3/action/package_show?id="
ESTACIONES_INIA = {
    "inia-precipitacion-temps-extremas-le": ("INIA La Estanzuela", -34.3372, -57.6922),
    "inia-precipitacion-temps-extremas-lb": ("INIA Las Brujas", -34.67, -56.34),
    "inia-precipitacion-temps-extremas-tb": ("INIA Tacuarembó", -31.7089, -55.8267),
    "inia-precipitacion-temps-extremas-sg": ("INIA Salto Grande", -31.2728, -57.8908),
    "inia-precipitacion-temps-extremas-tyt": ("INIA Treinta y Tres", -33.2750, -54.1722),
}


INA_URL = "https://alerta.ina.gob.ar/pub/datos/datos"
# El INA emite hora local argentina (UTC-3) sin offset explícito.
INA_TZ = timezone(timedelta(hours=-3))
# Niveles de alerta/evacuación oficiales de Prefectura según los metadatos de
# /pub/datos/estaciones (2026-08), en la escala local de cada estación: solo
# son comparables con lecturas de la misma escala, nunca con cotas DINAGUA.
ESTACIONES_INA = [
    (78, "Salto Grande Abajo", "Río Uruguay", -31.2755, -57.9369, 17.3, 17.8),
    (79, "Concordia", "Río Uruguay", -31.4000, -58.0167, 11.0, 12.5),
    (80, "Colón", "Río Uruguay", -32.2333, -58.1167, 7.1, 7.9),
    (81, "Concepción del Uruguay", "Río Uruguay", -32.4833, -58.2333, 5.3, 6.3),
    (1699, "Nueva Palmira", "Río Uruguay", -33.8785, -58.4220, None, None),
    # isla frente a Carmelo: único mareógrafo público del alto estuario
    (47, "Martín García", "Río de la Plata", -34.1903, -58.2530, 2.5, 5.0),
]


# La página pública exige la cookie de sesión anónima que reparte el portal;
# visitar el portal primero y luego la página de datos con la misma sesión.
UTE_PORTAL_URL = ("https://apps.ute.com.uy/sge/portal/nucleo/paginas/"
                  "portal_utei.aspx?c=GerGdeE_CUPubNivCau")
UTE_NIVELES_URL = ("https://apps.ute.com.uy/sge/portal/GestionEmbalseWeb/"
                   "Paginas/GdeE/Previsiones/CUPubNivCau.aspx")
ID_PALMAR = -2
COORDS_PALMAR = (-33.067, -57.459)
# Media de largo plazo del tramo más cercano a Palmar (HYRIV_ID 61495605),
# según la climatología de DINAGUA: el factor debe ser consistente con la
# referencia con la que se escala la red (ver build_climatologia.py).
Q_MEDIO_PALMAR = 922.7
AREA_PALMAR_KM2 = 62_000


# Coordenadas aproximadas del sitio del mareógrafo; la página no las publica.
ESTACIONES_SOHMA = [
    (5, "sohma-puntalobos", "Punta Lobos — bahía de Montevideo",
     "Río de la Plata", -34.9011, -56.2470),
    (4, "sohma-lapaloma", "La Paloma", "Océano Atlántico", -34.6486, -54.1453),
]


def leer_sohma(ahora: datetime) -> dict | None:
    import requests

    estaciones = []
    for n, sid, nombre, curso, lat, lon in ESTACIONES_SOHMA:
        try:
            r = requests.get(f"https://meteo.armada.mil.uy/Est{n}Armada.php",
                             timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        except Exception as exc:
            log.warning("SOHMA %s inaccesible: %s", nombre, exc)
            continue
        texto = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto)
        # primera fila de la tabla = lectura más reciente
        m = re.search(r"(\d{2})-(\d{2})-(\d{4}) (\d{2}):(\d{2}):\d{2} ([\d.]+)", texto)
        if not m:
            log.warning("SOHMA %s: página sin tabla de lecturas", nombre)
            continue
        d, mes, anio, hh, mi, valor = m.groups()
        # hora oficial de Uruguay (UTC-3, sin horario de verano)
        fecha = datetime(int(anio), int(mes), int(d), int(hh), int(mi), tzinfo=INA_TZ)
        estaciones.append({
            "id": sid,
            "nombre": nombre,
            "curso": curso,
            "lat": lat,
            "lon": lon,
            "nivel": float(valor),
            "fecha": fecha.isoformat(timespec="minutes"),
            "horas": round((ahora - fecha).total_seconds() / 3600, 1),
        })
    return {"estaciones": estaciones} if estaciones else None


def leer_ute_rio_negro(ahora: datetime) -> dict | None:
    import requests

    def limpiar(c: str) -> str:
        return re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()

    def num(x: str) -> float | None:
        x = x.strip()
        # "< 55,5" = por debajo de la escala: sin lectura
        if not x or not re.fullmatch(r"[\d.,]+", x):
            return None
        return float(x.replace(".", "").replace(",", "."))

    try:
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        s.get(UTE_PORTAL_URL, timeout=60)
        r = s.get(UTE_NIVELES_URL, timeout=60)
        r.raise_for_status()
    except Exception as exc:
        log.warning("UTE río Negro inaccesible: %s", exc)
        return None
    html = r.text

    m = re.search(r"actualizada el d[íi]a (\d{2})/(\d{2})/(\d{4}) a la hora "
                  r"(\d{1,2}):(\d{2})", html)
    actualizado = None
    if m:
        d, mes, anio, hh, mm = (int(g) for g in m.groups())
        actualizado = datetime(anio, mes, d, hh, mm, tzinfo=INA_TZ).isoformat(timespec="minutes")

    dias, maximos = [], []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        celdas = [limpiar(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if celdas and re.fullmatch(r"\d{2}/\d{2}/\d{4}", celdas[0]) and len(celdas) == 9:
            d, mes, anio = celdas[0].split("/")
            dias.append({
                "fecha": f"{anio}-{mes}-{d}",
                "san_gregorio_local": num(celdas[2]),
                "paso_toros_oficial": num(celdas[4]),
                "mercedes_local": num(celdas[6]),
                "erogado_bonete": num(celdas[7]),
                "erogado_palmar": num(celdas[8]),
            })
        elif (len(celdas) == 3 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", celdas[2] or "")
              and num(celdas[1]) is not None):
            maximos.append({"lugar": re.sub(r"\*+\s*$", "", celdas[0]).strip(),
                            "nivel": num(celdas[1]), "fecha": celdas[2]})
    if not dias:
        log.warning("UTE río Negro: página sin tabla de previsión")
        return None
    return {"actualizado": actualizado, "dias": dias, "maximos": maximos}


ANA_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
# q_medio = DIS_AV_CMS del tramo HydroRIVERS más cercano (consistencia con la
# escala de la red); area_km2 solo ordena prioridad entre estaciones del curso.
# Jaguarão ciudad (88300040) y Laguna Merín (88045010) están sin transmitir.
ESTACIONES_ANA = [
    ("77500000", "Quaraí — río Cuareim", "Río Cuareim",
     -30.3844, -56.4656, 101.4, 4574),
    ("88260000", "Passo das Pedras — río Yaguarón", "Río Yaguarón",
     -32.5194, -53.4558, 139.5, 7038),
]


def leer_ana(ahora: datetime) -> dict | None:
    import xml.etree.ElementTree as ET

    import requests

    d0 = (ahora - timedelta(days=3)).strftime("%d/%m/%Y")
    d1 = (ahora + timedelta(days=1)).strftime("%d/%m/%Y")
    estaciones = []
    for cod, nombre, curso, lat, lon, q_medio, area in ESTACIONES_ANA:
        root = None
        for intento in range(2):
            try:
                r = requests.get(ANA_URL, timeout=90, params={
                    "codEstacao": cod, "dataInicio": d0, "dataFim": d1})
                r.raise_for_status()
                root = ET.fromstring(r.content)
                break
            except Exception as exc:
                log.warning("ANA %s intento %d: %s", nombre, intento + 1, exc)
        if root is None:
            continue
        filas = []
        for f in root.iter("DadosHidrometereologicos"):
            d = {c.tag: (c.text or "").strip() for c in f}
            if d.get("DataHora"):
                filas.append(d)
        if not filas:
            log.warning("ANA %s sin datos en la ventana", nombre)
            continue
        filas.sort(key=lambda d: d["DataHora"])

        def num(fila: dict, k: str) -> float | None:
            try:
                return float(fila[k]) if fila.get(k) else None
            except ValueError:
                return None

        ult = filas[-1]
        # la telemetría emite hora de Brasilia (UTC-3, sin DST desde 2019)
        fecha = datetime.fromisoformat(ult["DataHora"]).replace(tzinfo=INA_TZ)
        mm24 = sum(num(f, "Chuva") or 0 for f in filas
                   if f["DataHora"] >= (fecha - timedelta(hours=24))
                   .strftime("%Y-%m-%d %H:%M:%S"))
        nivel_cm = num(ult, "Nivel")
        estaciones.append({
            "id": f"ana-{cod}",
            "nombre": nombre,
            "curso": curso,
            "lat": lat,
            "lon": lon,
            "nivel": round(nivel_cm / 100, 2) if nivel_cm is not None else None,
            "caudal": num(ult, "Vazao"),
            "fecha": fecha.isoformat(timespec="minutes"),
            "horas": round((ahora - fecha).total_seconds() / 3600, 1),
            "mm24": round(mm24, 1),
            "q_medio": q_medio,
            "area_km2": area,
        })
    return {"estaciones": estaciones} if estaciones else None


def leer_ina(ahora: datetime) -> dict | None:
    import requests

    t0 = (ahora - timedelta(days=6)).strftime("%Y-%m-%d")
    t1 = (ahora + timedelta(days=1)).strftime("%Y-%m-%d")
    estaciones = []
    for code, nombre, curso, lat, lon, alerta, evacuacion in ESTACIONES_INA:
        url = (f"{INA_URL}&siteCode={code}&varId=2"
               f"&timeStart={t0}&timeEnd={t1}&format=json")
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            datos = r.json().get("data", [])
        except Exception as exc:
            log.warning("INA %s inaccesible: %s", nombre, exc)
            continue
        if not datos:
            log.warning("INA %s sin datos en la ventana", nombre)
            continue
        ultimo = max(datos, key=lambda o: o["timestart"])
        fecha = datetime.fromisoformat(ultimo["timestart"]).replace(tzinfo=INA_TZ)
        estaciones.append({
            "id": f"ina-{code}",
            "nombre": nombre,
            "curso": curso,
            "lat": lat,
            "lon": lon,
            "nivel": ultimo["valor"],
            "nivel_fecha": fecha.isoformat(timespec="minutes"),
            "nivel_horas": round((ahora - fecha).total_seconds() / 3600, 1),
            "alerta": alerta,
            "evacuacion": evacuacion,
        })
    return {"estaciones": estaciones} if estaciones else None


def horas_desde(fecha_iso: str | None, ahora: datetime) -> float | None:
    if not fecha_iso:
        return None
    try:
        fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (ahora - fecha).total_seconds() / 3600


def leer_catalogo_dinagua() -> dict[int, dict]:
    feats = wfs._get("dinagua:V_Catalogo_publica", timeout=60)
    if not feats:
        return {}
    return {int(f["properties"]["id"]): f["properties"] for f in feats}


def leer_salto_grande() -> dict | None:
    try:
        r = wfs.SESSION.get(SALTO_GRANDE_URL, timeout=40)
        r.raise_for_status()
    except Exception as exc:
        log.warning("salto grande inaccesible: %s", exc)
        return None
    html = r.text

    def celda(etiqueta: str) -> float | None:
        # "Caudal Turbinado ... <td>6.000 m<sup>3</sup>/s</td>" ("." = miles)
        m = re.search(etiqueta + r".*?<td[^>]*>([\d.,]+)\s*m<sup>3</sup>/s", html, re.S)
        if not m:
            return None
        return float(m.group(1).replace(".", "").replace(",", "."))

    turbinado = celda("Caudal Turbinado")
    vertido = celda("Caudal Vertido")
    fecha = re.search(r"Fecha:\s*(\d{2}/\d{2}/\d{4})\s*Hora:\s*(\d{2}:\d{2})", html)
    if turbinado is None and vertido is None:
        return None
    return {
        "turbinado": turbinado,
        "vertido": vertido,
        "total": (turbinado or 0) + (vertido or 0),
        "fecha_local": f"{fecha.group(1)} {fecha.group(2)}" if fecha else None,
    }


def leer_lluvia_inumet(ahora: datetime) -> dict | None:
    try:
        r = wfs.SESSION.get(LLUVIA_URL, timeout=120)
        r.raise_for_status()
    except Exception as exc:
        log.warning("lluvia INUMET inaccesible: %s", exc)
        return None

    corte = ahora - timedelta(days=5)
    corte_txt = corte.strftime("%Y-%m-%d")
    lecturas: dict[str, list[tuple[datetime, float]]] = {}
    for fila in csv.reader(io.StringIO(r.text), delimiter=";"):
        if len(fila) < 3 or fila[0][:10] < corte_txt:
            continue
        nombre = fila[1].strip()
        if nombre not in ESTACIONES_INUMET:
            continue
        try:
            fecha = datetime.strptime(fila[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            mm = float(fila[2])
        except ValueError:
            continue
        lecturas.setdefault(nombre, []).append((fecha, mm))
    if not lecturas:
        return None

    hasta = max(f for v in lecturas.values() for f, _ in v)
    estaciones = []
    for nombre, vals in sorted(lecturas.items()):
        lat, lon = ESTACIONES_INUMET[nombre]
        estaciones.append({
            "nombre": nombre.removesuffix(" G3"),
            "lat": lat,
            "lon": lon,
            "mm24": round(sum(m for f, m in vals if f > hasta - timedelta(hours=24)), 1),
            "mm72": round(sum(m for f, m in vals if f > hasta - timedelta(hours=72)), 1),
            "fuente": "INUMET",
        })
    return {"hasta": hasta.isoformat(timespec="minutes"), "estaciones": estaciones}


def leer_lluvia_inia(ahora: datetime) -> list[dict] | None:
    estaciones = []
    anio = str(ahora.year)
    for dataset, (nombre, lat, lon) in ESTACIONES_INIA.items():
        try:
            r = wfs.SESSION.get(CKAN_PACKAGE_URL + dataset, timeout=60)
            r.raise_for_status()
            recursos = r.json()["result"]["resources"]
            url = next(
                x["url"] for x in recursos
                if x.get("format") == "CSV" and anio in (x.get("name") or "")
            )
            rc = wfs.SESSION.get(url, timeout=60)
            rc.raise_for_status()
        except Exception as exc:
            log.warning("lluvia INIA %s: %s", dataset, exc)
            continue
        filas = [
            f for f in csv.DictReader(io.StringIO(rc.text))
            if f.get("pluviometro") not in (None, "", "NA")
        ]
        if not filas:
            continue
        try:
            fecha = datetime.strptime(filas[-1]["fecha"], "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
            mm = [float(f["pluviometro"]) for f in filas[-3:]]
        except ValueError:
            continue
        if ahora - fecha > timedelta(days=3):
            continue
        estaciones.append({
            "nombre": nombre,
            "lat": lat,
            "lon": lon,
            "mm24": round(mm[-1], 1),
            "mm72": round(sum(mm), 1),
            "fecha": filas[-1]["fecha"],
            "fuente": "INIA",
        })
    return estaciones or None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    ahora = datetime.now(timezone.utc)

    mapping = json.loads(ESTACIONES.read_text(encoding="utf-8"))
    catalogo = leer_catalogo_dinagua()
    salto = leer_salto_grande()
    lluvia_inumet = leer_lluvia_inumet(ahora)
    lluvia_inia = leer_lluvia_inia(ahora)
    lluvia = lluvia_inumet
    if lluvia_inia:
        if lluvia:
            lluvia["estaciones"].extend(lluvia_inia)
        else:
            lluvia = {"hasta": None, "estaciones": lluvia_inia}
    ina = leer_ina(ahora)
    ute = leer_ute_rio_negro(ahora)
    ana = leer_ana(ahora)
    sohma = leer_sohma(ahora)
    fuentes = {
        "dinagua_wfs": "ok" if catalogo else "caida",
        "salto_grande": "ok" if salto else "caida",
        "inumet_lluvia": "ok" if lluvia_inumet else "caida",
        "inia_lluvia": "ok" if lluvia_inia else "caida",
        "ina": "ok" if ina else "caida",
        "ute_rio_negro": "ok" if ute else "caida",
        "ana": "ok" if ana else "caida",
        "sohma": "ok" if sohma else "caida",
        "caru": "no_implementada",
    }

    estaciones = []
    factores: dict[str, dict] = {}
    for feat in mapping["features"]:
        p = feat["properties"]
        est_id = int(p["id"])
        lon, lat = feat["geometry"]["coordinates"][:2]
        e = {
            "id": est_id,
            "nombre": p["nombre"],
            "curso": p["curso"],
            "tipo": p["tipo"],
            "lat": lat,
            "lon": lon,
            "q_medio": p["q_medio"],
            "codigo5": p["codigo5"],
            "nivel": None, "nivel_fecha": None, "nivel_horas": None,
            "caudal": None, "caudal_fecha": None, "caudal_horas": None,
            "factor": None,
        }

        if est_id == ID_SALTO_GRANDE:
            if salto:
                e["caudal"] = salto["total"]
                e["caudal_fecha"] = salto["fecha_local"]
                e["caudal_horas"] = 1.0
        elif est_id in catalogo:
            c = catalogo[est_id]
            e["nivel"] = c.get("ultimo_valor")
            e["nivel_fecha"] = c.get("ultima_fecha")
            e["nivel_horas"] = horas_desde(c.get("ultima_fecha"), ahora)
            e["caudal"] = c.get("ultimo_caudal")
            e["caudal_fecha"] = c.get("ultima_caudal_fecha")
            e["caudal_horas"] = horas_desde(c.get("ultima_caudal_fecha"), ahora)

        caudal_fresco = (
            e["caudal"] is not None
            and e["caudal_horas"] is not None
            and e["caudal_horas"] <= FRESCURA_MAX_CAUDAL_H
        )
        if caudal_fresco and p["join_ok"] and p["q_medio"]:
            factor = e["caudal"] / p["q_medio"]
            e["factor"] = round(min(max(factor, FACTOR_CLAMP[0]), FACTOR_CLAMP[1]), 3)

        estaciones.append(e)

        # factor por curso (nombre completo del río: codigo5 de DINAGUA es por
        # sección, no por río); gana la estación de mayor cuenca con dato fresco
        if e["factor"] is not None and p["curso"]:
            clave = str(p["curso"])
            previa = factores.get(clave)
            if previa is None or p["area_km2"] > previa["area_km2"]:
                factores[clave] = {
                    "factor": e["factor"],
                    "estacion": p["nombre"],
                    "area_km2": p["area_km2"] or 0,
                }

    # Palmar como pseudo-estación: el erogado previsto para hoy manda sobre el
    # bajo río Negro igual que Salto Grande sobre el río Uruguay. Es previsión
    # hidráulica de UTE, no medición: el nombre lo declara.
    if ute and ute["dias"]:
        erogado = ute["dias"][0].get("erogado_palmar")
        horas_ute = horas_desde(ute.get("actualizado"), ahora)
        if erogado and horas_ute is not None and horas_ute <= FRESCURA_MAX_CAUDAL_H:
            factor = round(min(max(erogado / Q_MEDIO_PALMAR, FACTOR_CLAMP[0]),
                               FACTOR_CLAMP[1]), 3)
            estaciones.append({
                "id": ID_PALMAR,
                "nombre": "Palmar — erogado previsto (UTE)",
                "curso": "Río Negro",
                "tipo": "erogado_previsto",
                "lat": COORDS_PALMAR[0],
                "lon": COORDS_PALMAR[1],
                "q_medio": Q_MEDIO_PALMAR,
                "codigo5": None,
                "nivel": None, "nivel_fecha": None, "nivel_horas": None,
                "caudal": erogado,
                "caudal_fecha": ute.get("actualizado"),
                "caudal_horas": round(horas_ute, 1),
                "factor": factor,
            })
            previa = factores.get("Río Negro")
            if previa is None or AREA_PALMAR_KM2 > previa["area_km2"]:
                factores["Río Negro"] = {
                    "factor": factor,
                    "estacion": "Palmar — erogado previsto (UTE)",
                    "area_km2": AREA_PALMAR_KM2,
                }

    # Caudal ANA fresco -> factor del curso compartido (misma regla: gana la
    # estación de mayor cuenca).
    if ana:
        for e in ana["estaciones"]:
            if not e["caudal"] or e["horas"] > FRESCURA_MAX_CAUDAL_H:
                continue
            factor = round(min(max(e["caudal"] / e["q_medio"], FACTOR_CLAMP[0]),
                               FACTOR_CLAMP[1]), 3)
            e["factor"] = factor
            previa = factores.get(e["curso"])
            if previa is None or e["area_km2"] > previa["area_km2"]:
                factores[e["curso"]] = {
                    "factor": factor,
                    "estacion": e["nombre"],
                    "area_km2": e["area_km2"],
                }

    # Activación de manchas: nivel actual vs umbrales por datum oficial
    # (cota_oficial - cota_cero; incertidumbre ~±1 m, ver analizar_datum.py).
    por_id = {e["id"]: e for e in estaciones}
    activacion = {}
    umbrales_loc = json.loads(ACTIVACION.read_text(encoding="utf-8")) if ACTIVACION.exists() else {}
    for cod, cfg in umbrales_loc.items():
        e = por_id.get(cfg["estacion_id"])
        if not e or e["nivel"] is None or e["nivel_horas"] is None:
            continue
        if e["nivel_horas"] > FRESCURA_MAX_ACTIVACION_H:
            continue
        nivel = e["nivel"]
        activos = [u for u in cfg["umbrales"] if nivel >= u["nivel"]]
        proximos = [u for u in cfg["umbrales"] if nivel < u["nivel"]]
        entrada = {
            "estacion": cfg["estacion"],
            "nivel": nivel,
            "nivel_horas": round(e["nivel_horas"], 1),
            "periodo_activo": max((u["periodo"] for u in activos), default=0),
        }
        if proximos:
            u = min(proximos, key=lambda x: x["nivel"])
            entrada["proximo"] = {"periodo": u["periodo"],
                                  "faltan_m": round(u["nivel"] - nivel, 2)}
        activacion[cod] = entrada

    estado = {
        "generado": ahora.isoformat(timespec="seconds"),
        "fuentes": fuentes,
        "estaciones": estaciones,
        "factores_curso": {k: {"factor": v["factor"], "estacion": v["estacion"]}
                           for k, v in factores.items()},
        "activacion": activacion,
        "lluvia": lluvia,
        "salto_grande": salto,
        "ina": ina,
        "ute_rio_negro": ute,
        "ana": ana,
        "sohma": sohma,
    }

    SALIDA.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    log.info("guardado %s: %d estaciones, %d cursos con factor, fuentes=%s",
             SALIDA, len(estaciones), len(factores), fuentes)

    snap = HISTORICO / ahora.strftime("%Y/%m/%d-%H%M.json")
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
