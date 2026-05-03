"""Genera web/public/data/estado_actual.json con el estado hídrico actual.

Pensado para correr en cron (GitHub Actions): depende solo de requests +
stdlib. El mapping estación->tramo viene precalculado por build_estaciones.py.

Fuentes (cada una tolera fallos de forma independiente):
- WFS DINAGUA V_Catalogo_publica: último nivel y último caudal por estación.
- saltogrande.org/datos_horarios.php: caudal turbinado + vertido (horario).
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wfs

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
ESTACIONES = ROOT / "web" / "public" / "data" / "estaciones.geojson"
SALIDA = ROOT / "web" / "public" / "data" / "estado_actual.json"
HISTORICO = ROOT / "data" / "historico"

FRESCURA_MAX_CAUDAL_H = 24 * 7
FRESCURA_MAX_NIVEL_H = 24 * 7
FACTOR_CLAMP = (0.05, 20.0)
SALTO_GRANDE_URL = "https://www.saltogrande.org/datos_horarios.php"
ID_SALTO_GRANDE = -1


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    ahora = datetime.now(timezone.utc)

    mapping = json.loads(ESTACIONES.read_text(encoding="utf-8"))
    catalogo = leer_catalogo_dinagua()
    salto = leer_salto_grande()
    fuentes = {
        "dinagua_wfs": "ok" if catalogo else "caida",
        "salto_grande": "ok" if salto else "caida",
        "ina": "no_implementada",
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

        # factor por curso: gana la estación de mayor cuenca con dato fresco
        if e["factor"] is not None and p["codigo5"] is not None:
            clave = str(p["codigo5"])
            previa = factores.get(clave)
            if previa is None or p["area_km2"] > previa["area_km2"]:
                factores[clave] = {
                    "factor": e["factor"],
                    "estacion": p["nombre"],
                    "area_km2": p["area_km2"] or 0,
                }

    estado = {
        "generado": ahora.isoformat(timespec="seconds"),
        "fuentes": fuentes,
        "estaciones": estaciones,
        "factores_curso": {k: {"factor": v["factor"], "estacion": v["estacion"]}
                           for k, v in factores.items()},
    }

    SALIDA.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    log.info("guardado %s: %d estaciones, %d cursos con factor, fuentes=%s",
             SALIDA, len(estaciones), len(factores), fuentes)

    snap = HISTORICO / ahora.strftime("%Y/%m/%d-%H%M.json")
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
