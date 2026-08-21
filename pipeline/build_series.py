"""Consolida los snapshots de data/historico/ en series por estación.

Cada snapshot guarda la última observación conocida por estación; acumulando
snapshots cada 2 h se reconstruye la serie real deduplicando por fecha de
observación (no por fecha de snapshot). Salida: web/public/data/series.json
con { id: { nivel: [[epoch_s, v], ...], caudal: [...] } }.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    def punto(sid: str, variable: str, fecha: str | None, valor) -> None:
        t = epoch(fecha)
        if t is None or valor is None:
            return
        series.setdefault(sid, {}).setdefault(variable, {})[t] = float(valor)

    archivos = sorted(HISTORICO.rglob("*.json"))
    for archivo in archivos:
        try:
            snap = json.loads(archivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for e in snap.get("estaciones") or []:
            sid = str(e.get("id"))
            punto(sid, "nivel", e.get("nivel_fecha"), e.get("nivel"))
            punto(sid, "caudal", e.get("caudal_fecha"), e.get("caudal"))
        for e in (snap.get("ina") or {}).get("estaciones", []):
            punto(str(e.get("id")), "nivel", e.get("nivel_fecha"), e.get("nivel"))
        for e in (snap.get("ana") or {}).get("estaciones", []):
            sid = str(e.get("id"))
            punto(sid, "nivel", e.get("fecha"), e.get("nivel"))
            punto(sid, "caudal", e.get("fecha"), e.get("caudal"))
        for e in (snap.get("sohma") or {}).get("estaciones", []):
            punto(str(e.get("id")), "nivel", e.get("fecha"), e.get("nivel"))

    corte = int((datetime.now(timezone.utc) - timedelta(days=VENTANA_DIAS)).timestamp())
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
                "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                "ventana_dias": VENTANA_DIAS,
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
