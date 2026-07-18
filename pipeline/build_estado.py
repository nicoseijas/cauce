"""Genera web/public/data/estado_actual.json con el estado hídrico actual.

Pensado para correr en cron (GitHub Actions): depende solo de requests +
stdlib. El mapping estación->tramo viene precalculado por build_estaciones.py.

Fuentes (cada una tolera fallos de forma independiente):
- WFS DINAGUA V_Catalogo_publica: último nivel y último caudal por estación.
- saltogrande.org/datos_horarios.php: caudal turbinado + vertido (horario).
- INA alerta.ina.gob.ar: alturas del río Uruguay con niveles oficiales de
  alerta/evacuación de Prefectura (escala local de cada estación).
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


INA_URL = "https://alerta.ina.gob.ar/pub/datos/datos"
# El INA emite hora local argentina (UTC-3) sin offset explícito.
INA_TZ = timezone(timedelta(hours=-3))
# Niveles de alerta/evacuación oficiales de Prefectura según los metadatos de
# /pub/datos/estaciones (2026-08), en la escala local de cada estación: solo
# son comparables con lecturas de la misma escala, nunca con cotas DINAGUA.
ESTACIONES_INA = [
    (78, "Salto Grande Abajo", -31.2755, -57.9369, 17.3, 17.8),
    (79, "Concordia", -31.4000, -58.0167, 11.0, 12.5),
    (80, "Colón", -32.2333, -58.1167, 7.1, 7.9),
    (81, "Concepción del Uruguay", -32.4833, -58.2333, 5.3, 6.3),
    (1699, "Nueva Palmira", -33.8785, -58.4220, None, None),
]


def leer_ina(ahora: datetime) -> dict | None:
    import requests

    t0 = (ahora - timedelta(days=6)).strftime("%Y-%m-%d")
    t1 = (ahora + timedelta(days=1)).strftime("%Y-%m-%d")
    estaciones = []
    for code, nombre, lat, lon, alerta, evacuacion in ESTACIONES_INA:
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
        })
    return {"hasta": hasta.isoformat(timespec="minutes"), "estaciones": estaciones}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    ahora = datetime.now(timezone.utc)

    mapping = json.loads(ESTACIONES.read_text(encoding="utf-8"))
    catalogo = leer_catalogo_dinagua()
    salto = leer_salto_grande()
    lluvia = leer_lluvia_inumet(ahora)
    ina = leer_ina(ahora)
    fuentes = {
        "dinagua_wfs": "ok" if catalogo else "caida",
        "salto_grande": "ok" if salto else "caida",
        "inumet_lluvia": "ok" if lluvia else "caida",
        "ina": "ok" if ina else "caida",
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
        "ina": ina,
    }

    SALIDA.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    log.info("guardado %s: %d estaciones, %d cursos con factor, fuentes=%s",
             SALIDA, len(estaciones), len(factores), fuentes)

    snap = HISTORICO / ahora.strftime("%Y/%m/%d-%H%M.json")
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
