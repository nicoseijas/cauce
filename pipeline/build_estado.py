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
import math
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wfs
from identidad import asignar_identidad
from qc_hidrometria import (
    QC_VERSION,
    agregar_vigilancia,
    construir_resumen,
    contexto_nivel,
    evaluar_medicion,
    extraer_referencia,
)

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ESTACIONES = ROOT / "web" / "public" / "data" / "estaciones.geojson"
ACTIVACION = ROOT / "web" / "public" / "data" / "activacion.json"
SALIDA = ROOT / "web" / "public" / "data" / "estado_actual.json"
HISTORICO = ROOT / "data" / "historico"
# Una activación describe el estado presente: pasado un día deja de ser apta
# para afirmar que una mancha está superada. Los factores visuales admiten 48 h
# para acompañar fuentes diarias, pero nunca la semana que se toleraba antes.
FRESCURA_MAX_ACTIVACION_H = 24
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
            "clasificacion": "observado",
            "oficial": True,
            "fuente": "SOHMA (Armada)",
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
    return {
        "actualizado": actualizado,
        "clasificacion": "pronosticado",
        "oficial": True,
        "horizonte_dias": 7,
        "probabilidad": None,
        "incertidumbre": "no publicada por UTE",
        "dias": dias,
        "maximos": maximos,
    }


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
            "clasificacion": "observado",
            "oficial": True,
            "fuente": "ANA (Brasil)",
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
            "clasificacion": "observado",
            "oficial": True,
            "fuente": "INA / Prefectura (Argentina)",
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
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return (ahora - fecha).total_seconds() / 3600


def fecha_mas_reciente(valores, ahora: datetime) -> str | None:
    """Devuelve la fecha parseable más reciente sin mezclar formatos por texto."""
    candidatas = []
    for valor in valores:
        horas = horas_desde(valor, ahora)
        if horas is not None and horas >= -1:
            candidatas.append((horas, valor))
    return min(candidatas, default=(None, None), key=lambda x: x[0])[1]


FRESCURA_POR_FUENTE_H = {
    "dinagua_wfs": 48,
    "salto_grande": 48,
    "inumet_lluvia": 48,
    "inia_lluvia": 72,
    "ina": 48,
    "ute_rio_negro": 48,
    "ana": 48,
    "sohma": 24,
}


def construir_fuentes_detalle(
    disponibles: dict[str, bool | None],
    observaciones: dict[str, str | None],
    ahora: datetime,
    previas: dict | None = None,
) -> dict[str, dict]:
    """Estado observable de cada fuente, conservando el último éxito conocido."""
    previas = previas or {}
    salida = {}
    for clave, disponible in disponibles.items():
        anterior = previas.get(clave) or {}
        observacion = observaciones.get(clave)
        if disponible is None:
            estado = "no_implementada"
        elif not disponible:
            estado = "caida"
        elif not observacion:
            estado = "sin_fecha"
        else:
            horas = horas_desde(observacion, ahora)
            limite = FRESCURA_POR_FUENTE_H.get(clave)
            estado = (
                "vencida"
                if horas is None or horas < -1 or (limite is not None and horas > limite)
                else "ok"
            )
        salida[clave] = {
            "estado": estado,
            "ultima_observacion": observacion or anterior.get("ultima_observacion"),
            "ultimo_exito": (
                ahora.isoformat(timespec="seconds")
                if disponible
                else anterior.get("ultimo_exito")
            ),
        }
    return salida


def evaluar_activacion(
    configuracion: dict,
    estaciones: list[dict],
) -> tuple[dict, dict]:
    """Evalúa solo localidades habilitadas explícitamente y con datum aprobado."""
    por_id = {e.get("id"): e for e in estaciones if e.get("id") is not None}
    habilitadas = {
        cod: cfg for cod, cfg in configuracion.items()
        if cfg.get("auto_habilitada") is True
    }
    activacion = {}
    rechazadas_qc = 0
    for cod, cfg in habilitadas.items():
        e = por_id.get(cfg.get("estacion_id"))
        nivel = e.get("nivel") if e else None
        nivel_horas = e.get("nivel_horas") if e else None
        if e and e.get("qc_nivel", {}).get("apto_derivados") is not True:
            rechazadas_qc += 1
            continue
        if (
            not isinstance(nivel, (int, float))
            or not math.isfinite(nivel)
            or not dato_fresco(nivel_horas, FRESCURA_MAX_ACTIVACION_H)
        ):
            continue
        umbrales = [
            u for u in cfg.get("umbrales", [])
            if u.get("datum_ok") is True
            and isinstance(u.get("nivel"), (int, float))
            and math.isfinite(u["nivel"])
        ]
        if not umbrales:
            continue
        activos = [u for u in umbrales if nivel >= u["nivel"]]
        proximos = [u for u in umbrales if nivel < u["nivel"]]
        entrada = {
            "estacion": cfg.get("estacion", str(cfg.get("estacion_id", "sin identificar"))),
            "nivel": nivel,
            "nivel_horas": round(nivel_horas, 1),
            "periodo_activo": max((u["periodo"] for u in activos), default=0),
        }
        if proximos:
            u = min(proximos, key=lambda x: x["nivel"])
            entrada["proximo"] = {
                "periodo": u["periodo"],
                "faltan_m": round(u["nivel"] - nivel, 2),
            }
        activacion[cod] = entrada
    cobertura = {
        "configuradas": len(configuracion),
        "habilitadas": len(habilitadas),
        "evaluadas": len(activacion),
        "rechazadas_qc": rechazadas_qc,
        "con_estacion_superficial": sum(
            cfg.get("estacion_id") is not None for cfg in configuracion.values()
        ),
        "con_curso_compatible": sum(
            cfg.get("curso_compatible") is True for cfg in configuracion.values()
        ),
        "tipos_inundacion": dict(sorted(Counter(
            cfg.get("tipo_inundacion", "sin_clasificar")
            for cfg in configuracion.values()
        ).items())),
        "bloqueos": dict(sorted(Counter(
            bloqueo
            for cfg in configuracion.values()
            for bloqueo in cfg.get("bloqueos", [])
        ).items())),
    }
    return activacion, cobertura


def indexar_estaciones_previas(estado: dict) -> dict[str, dict]:
    """Indexa estaciones propias y externas del último estado conocido."""
    estaciones = list(estado.get("estaciones") or [])
    for clave in ("ina", "ana", "sohma"):
        estaciones.extend((estado.get(clave) or {}).get("estaciones") or [])
    return {
        str(e.get("id")): e for e in estaciones
        if e.get("id") is not None
    }


def aplicar_qc_estacion(
    estacion: dict,
    anterior: dict | None,
    ahora: datetime,
    *,
    continuidad_nivel: bool = True,
) -> None:
    """Adjunta QC de nivel/caudal usando nombres de campo normalizados."""
    contexto = contexto_nivel(
        estacion.get("nombre"), estacion.get("tipo"), estacion.get("curso")
    )
    for variable in ("nivel", "caudal"):
        fecha_campo = f"{variable}_fecha"
        referencia = extraer_referencia(anterior, variable, ahora)
        estacion[f"qc_{variable}"] = evaluar_medicion(
            variable,
            estacion.get(variable),
            estacion.get(fecha_campo),
            ahora,
            referencia=referencia,
            contexto=contexto,
            continuidad=continuidad_nivel if variable == "nivel" else False,
        )
    agregar_vigilancia(estacion)


def leer_catalogo_dinagua() -> dict[int, dict]:
    feats = wfs._get("dinagua:V_Catalogo_publica", timeout=60)
    if not feats:
        return {}
    return {int(f["properties"]["id"]): f["properties"] for f in feats}


def parsear_fecha_salto(fecha_local: str | None) -> datetime | None:
    """Fecha de Salto Grande en hora oficial UTC-3, normalizada con offset."""
    if not fecha_local:
        return None
    try:
        return datetime.strptime(fecha_local, "%d/%m/%Y %H:%M").replace(tzinfo=INA_TZ)
    except ValueError:
        return None


def dato_fresco(horas: float | None, max_horas: float) -> bool:
    """Falla cerrado; tolera hasta una hora de desfase futuro entre relojes."""
    return horas is not None and -1 <= horas <= max_horas


def leer_salto_grande(ahora: datetime) -> dict | None:
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
    fecha_local = f"{fecha.group(1)} {fecha.group(2)}" if fecha else None
    fecha_dt = parsear_fecha_salto(fecha_local)
    return {
        "turbinado": turbinado,
        "vertido": vertido,
        "total": (turbinado or 0) + (vertido or 0),
        "fecha_local": fecha_local,
        "fecha": fecha_dt.isoformat(timespec="minutes") if fecha_dt else None,
        "horas": round((ahora - fecha_dt).total_seconds() / 3600, 1) if fecha_dt else None,
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
            "clasificacion": "observado",
            "oficial": True,
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
            "clasificacion": "observado",
            "oficial": True,
            "mm24": round(mm[-1], 1),
            "mm72": round(sum(mm), 1),
            "fecha": filas[-1]["fecha"],
            "fuente": "INIA",
        })
    return estaciones or None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    ahora = datetime.now(timezone.utc)

    try:
        estado_previo = json.loads(SALIDA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        estado_previo = {}
    previas_estacion = indexar_estaciones_previas(estado_previo)

    mapping = json.loads(ESTACIONES.read_text(encoding="utf-8"))
    catalogo = leer_catalogo_dinagua()
    salto = leer_salto_grande(ahora)
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

    # Las fuentes externas usan nombres históricos distintos; se agregan
    # alias normalizados para que el QC y los consumidores científicos puedan
    # tratarlas con el mismo contrato que las estaciones DINAGUA.
    for e in (ina or {}).get("estaciones", []):
        aplicar_qc_estacion(e, previas_estacion.get(str(e["id"])), ahora)
    for e in (ana or {}).get("estaciones", []):
        e["nivel_fecha"] = e.get("fecha")
        e["caudal_fecha"] = e.get("fecha")
        e["nivel_horas"] = e.get("horas")
        e["caudal_horas"] = e.get("horas")
        aplicar_qc_estacion(e, previas_estacion.get(str(e["id"])), ahora)
    for e in (sohma or {}).get("estaciones", []):
        e["nivel_fecha"] = e.get("fecha")
        e["nivel_horas"] = e.get("horas")
        e["caudal"] = None
        e["caudal_fecha"] = None
        e["caudal_horas"] = None
        aplicar_qc_estacion(e, previas_estacion.get(str(e["id"])), ahora)
    disponibles = {
        "dinagua_wfs": bool(catalogo),
        "salto_grande": bool(salto),
        "inumet_lluvia": bool(lluvia_inumet),
        "inia_lluvia": bool(lluvia_inia),
        "ina": bool(ina),
        "ute_rio_negro": bool(ute),
        "ana": bool(ana),
        "sohma": bool(sohma),
        "caru": None,
    }
    observaciones = {
        "dinagua_wfs": fecha_mas_reciente(
            (c.get(k) for c in catalogo.values()
             for k in ("ultima_fecha", "ultima_caudal_fecha")), ahora),
        "salto_grande": salto.get("fecha") if salto else None,
        "inumet_lluvia": lluvia_inumet.get("hasta") if lluvia_inumet else None,
        "inia_lluvia": fecha_mas_reciente(
            (e.get("fecha") for e in lluvia_inia or []), ahora),
        "ina": fecha_mas_reciente(
            (e.get("nivel_fecha") for e in (ina or {}).get("estaciones", [])), ahora),
        "ute_rio_negro": ute.get("actualizado") if ute else None,
        "ana": fecha_mas_reciente(
            (e.get("fecha") for e in (ana or {}).get("estaciones", [])), ahora),
        "sohma": fecha_mas_reciente(
            (e.get("fecha") for e in (sohma or {}).get("estaciones", [])), ahora),
        "caru": None,
    }
    fuentes_detalle = construir_fuentes_detalle(
        disponibles, observaciones, ahora, estado_previo.get("fuentes_detalle")
    )
    fuentes = {k: v["estado"] for k, v in fuentes_detalle.items()}

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
            "clasificacion": "observado",
            "oficial": True,
            "fuente": "Salto Grande (CTM)" if est_id == ID_SALTO_GRANDE else "DINAGUA",
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
                e["caudal_fecha"] = salto["fecha"]
                e["caudal_horas"] = salto["horas"]
        elif est_id in catalogo:
            c = catalogo[est_id]
            e["nivel"] = c.get("ultimo_valor")
            e["nivel_fecha"] = c.get("ultima_fecha")
            e["nivel_horas"] = horas_desde(c.get("ultima_fecha"), ahora)
            e["caudal"] = c.get("ultimo_caudal")
            e["caudal_fecha"] = c.get("ultima_caudal_fecha")
            e["caudal_horas"] = horas_desde(c.get("ultima_caudal_fecha"), ahora)

        aplicar_qc_estacion(e, previas_estacion.get(str(est_id)), ahora)
        caudal_fresco = e["qc_caudal"]["apto_derivados"] is True
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
                    "clasificacion": "estimado",
                    "insumo_clasificacion": "observado",
                    "oficial": True,
                    "fecha_insumo": e["caudal_fecha"],
                    "antiguedad_h": round(e["caudal_horas"], 1),
                    "alcance": "curso completo por nombre",
                    "incertidumbre": "no cuantificada; escala visual",
                    "qc_version": QC_VERSION,
                }

    # Palmar como pseudo-estación: el erogado previsto para hoy manda sobre el
    # bajo río Negro igual que Salto Grande sobre el río Uruguay. Es previsión
    # hidráulica de UTE, no medición: el nombre lo declara.
    if ute and ute["dias"]:
        erogado = ute["dias"][0].get("erogado_palmar")
        horas_ute = horas_desde(ute.get("actualizado"), ahora)
        if erogado is not None:
            factor = round(min(max(erogado / Q_MEDIO_PALMAR, FACTOR_CLAMP[0]),
                               FACTOR_CLAMP[1]), 3)
            estacion_palmar = {
                "id": ID_PALMAR,
                "nombre": "Palmar — erogado previsto (UTE)",
                "curso": "Río Negro",
                "tipo": "erogado_previsto",
                "clasificacion": "pronosticado",
                "oficial": True,
                "fuente": "UTE",
                "lat": COORDS_PALMAR[0],
                "lon": COORDS_PALMAR[1],
                "q_medio": Q_MEDIO_PALMAR,
                "codigo5": None,
                "nivel": None, "nivel_fecha": None, "nivel_horas": None,
                "caudal": erogado,
                "caudal_fecha": ute.get("actualizado"),
                "caudal_horas": round(horas_ute, 1),
                "valido_para": ute["dias"][0].get("fecha"),
                "horizonte": "día 1 de una previsión a 7 días",
                "probabilidad": None,
                "incertidumbre": "no publicada por UTE",
                "factor": None,
            }
            aplicar_qc_estacion(
                estacion_palmar,
                previas_estacion.get(str(ID_PALMAR)),
                ahora,
                continuidad_nivel=False,
            )
            if estacion_palmar["qc_caudal"]["apto_derivados"] is True:
                estacion_palmar["factor"] = factor
            estaciones.append(estacion_palmar)
            previa = factores.get("Río Negro")
            if (
                estacion_palmar["factor"] is not None
                and (previa is None or AREA_PALMAR_KM2 > previa["area_km2"])
            ):
                factores["Río Negro"] = {
                    "factor": factor,
                    "estacion": "Palmar — erogado previsto (UTE)",
                    "area_km2": AREA_PALMAR_KM2,
                    "clasificacion": "estimado",
                    "insumo_clasificacion": "pronosticado",
                    "oficial": True,
                    "fecha_insumo": ute.get("actualizado"),
                    "valido_para": ute["dias"][0].get("fecha"),
                    "antiguedad_h": round(horas_ute, 1),
                    "horizonte": "día 1 de una previsión a 7 días",
                    "probabilidad": None,
                    "alcance": "curso completo por nombre",
                    "incertidumbre": "no publicada por UTE; escala visual",
                    "qc_version": QC_VERSION,
                }

    # Caudal ANA fresco -> factor del curso compartido (misma regla: gana la
    # estación de mayor cuenca).
    if ana:
        for e in ana["estaciones"]:
            if e["qc_caudal"]["apto_derivados"] is not True:
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
                    "clasificacion": "estimado",
                    "insumo_clasificacion": "observado",
                    "oficial": True,
                    "fecha_insumo": e["fecha"],
                    "antiguedad_h": e["horas"],
                    "alcance": "curso completo por nombre",
                    "incertidumbre": "no cuantificada; escala visual",
                    "qc_version": QC_VERSION,
                }

    # Activación fail-closed: una localidad solo entra si analizar_datum.py la
    # marcó explícitamente con datum Y relación hidráulica validados.
    umbrales_loc = json.loads(ACTIVACION.read_text(encoding="utf-8")) if ACTIVACION.exists() else {}
    activacion, cobertura_activacion = evaluar_activacion(umbrales_loc, estaciones)
    cobertura_activacion["fuente_disponible"] = fuentes.get("dinagua_wfs") == "ok"

    todas_estaciones = list(estaciones)
    for fuente in (ina, ana, sohma):
        todas_estaciones.extend((fuente or {}).get("estaciones", []))
    asignar_identidad(todas_estaciones)
    control_calidad = construir_resumen(todas_estaciones)

    estado = {
        "schema_version": 3,
        "generado": ahora.isoformat(timespec="seconds"),
        "fuentes": fuentes,
        "fuentes_detalle": fuentes_detalle,
        "estaciones": estaciones,
        "factores_curso": {
            k: {campo: valor for campo, valor in v.items() if campo != "area_km2"}
            for k, v in factores.items()
        },
        "activacion": activacion,
        "activacion_cobertura": cobertura_activacion,
        "control_calidad": control_calidad,
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
