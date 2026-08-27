"""Consolida los snapshots de data/historico/ en series por estación.

Cada snapshot guarda la última observación conocida por estación; acumulando
snapshots cada 2 h se reconstruye la serie real deduplicando por fecha de
observación (no por fecha de snapshot). Salida: web/public/data/series.json
con { id: { nivel: [[epoch_s, v], ...], caudal: [...] } }.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qc_hidrometria import QC_VERSION, TOLERANCIA_FUTURO_H

RAIZ = Path(__file__).resolve().parent.parent
HISTORICO = RAIZ / "data" / "historico"
SALIDA = RAIZ / "web" / "public" / "data" / "series.json"

VENTANA_DIAS = 45
MAX_PUNTOS = 600


def epoch(fecha: str | None) -> int | None:
    if not fecha:
        return None
    try:
        dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    except ValueError:
        # Salto Grande publica "dd/mm/aaaa HH:MM" en hora local (UTC-3)
        try:
            dt = datetime.strptime(fecha, "%d/%m/%Y %H:%M").replace(
                tzinfo=timezone(timedelta(hours=-3))
            )
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def main() -> None:
    # id -> variable ("nivel"/"caudal") -> {epoch: valor}; los snapshots se
    # recorren en orden cronológico para que una revisión posterior gane.
    series: dict[str, dict[str, dict[int, float]]] = {}
    descartados: dict[str, set[tuple[str, str, int]]] = defaultdict(set)
    ahora = datetime.now(timezone.utc)
    futuro_max = int((ahora + timedelta(hours=TOLERANCIA_FUTURO_H)).timestamp())

    def punto(
        sid: str,
        variable: str,
        fecha: str | None,
        valor,
        qc: dict | None = None,
    ) -> None:
        t = epoch(fecha)
        if t is None or valor is None:
            return
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            descartados["valor_no_numerico"].add((sid, variable, t))
            return
        puntos = series.setdefault(sid, {}).setdefault(variable, {})
        if qc and qc.get("estado") in ("rechazado", "dudoso"):
            puntos.pop(t, None)
            for codigo in qc.get("codigos") or [qc["estado"]]:
                descartados[codigo].add((sid, variable, t))
            return
        if not math.isfinite(numero):
            puntos.pop(t, None)
            descartados["valor_no_finito"].add((sid, variable, t))
            return
        if t > futuro_max:
            puntos.pop(t, None)
            descartados["fecha_futura"].add((sid, variable, t))
            return
        puntos[t] = numero

    archivos = sorted(HISTORICO.rglob("*.json"))
    for archivo in archivos:
        try:
            snap = json.loads(archivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for e in snap.get("estaciones") or []:
            sid = str(e.get("id"))
            punto(sid, "nivel", e.get("nivel_fecha"), e.get("nivel"), e.get("qc_nivel"))
            punto(sid, "caudal", e.get("caudal_fecha"), e.get("caudal"), e.get("qc_caudal"))
        for e in (snap.get("ina") or {}).get("estaciones", []):
            punto(str(e.get("id")), "nivel", e.get("nivel_fecha"), e.get("nivel"), e.get("qc_nivel"))
        for e in (snap.get("ana") or {}).get("estaciones", []):
            sid = str(e.get("id"))
            punto(sid, "nivel", e.get("fecha"), e.get("nivel"), e.get("qc_nivel"))
            punto(sid, "caudal", e.get("fecha"), e.get("caudal"), e.get("qc_caudal"))
        for e in (snap.get("sohma") or {}).get("estaciones", []):
            punto(str(e.get("id")), "nivel", e.get("fecha"), e.get("nivel"), e.get("qc_nivel"))

    corte = int((ahora - timedelta(days=VENTANA_DIAS)).timestamp())
    salida: dict[str, dict[str, list[list[float]]]] = {}
    for sid, variables in series.items():
        est: dict[str, list[list[float]]] = {}
        for variable, puntos in variables.items():
            recientes = sorted(
                (t, v) for t, v in puntos.items() if t >= corte
            )[-MAX_PUNTOS:]
            if len(recientes) >= 2:
                est[variable] = [[t, v] for t, v in recientes]
        if est:
            salida[sid] = est

    SALIDA.write_text(
        json.dumps(
            {
                "generado": ahora.isoformat(timespec="minutes"),
                "ventana_dias": VENTANA_DIAS,
                "control_calidad": {
                    "version": QC_VERSION,
                    "observaciones_descartadas": {
                        codigo: len(puntos) for codigo, puntos in descartados.items()
                    },
                    "nota": "los snapshots conservan los valores originales y sus banderas QC",
                },
                "estaciones": salida,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    n_puntos = sum(len(p) for e in salida.values() for p in e.values())
    print(
        f"{len(archivos)} snapshots -> {len(salida)} estaciones con serie, "
        f"{n_puntos} puntos, {SALIDA.stat().st_size / 1024:.0f} KB"
    )


if __name__ == "__main__":
    main()
