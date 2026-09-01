"""Cliente WFS del GeoServer DINAGUA.

Convenciones del servidor:
- WFS 1.1.0: la 2.0.0 falla en vistas de PostgreSQL sin clave primaria.
- Paginación por rangos de id con CQL_FILTER (startIndex no funciona en vistas).
- Registros con overflow numérico en la BD se aíslan por bisección y se saltan.
- TLS: la cadena de certificados del servidor está incompleta -> verify=False.
"""

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

WFS_BASE = "https://www.ambiente.gub.uy/dinagua-gs/wfs"

SESSION = requests.Session()
SESSION.verify = False
requests.packages.urllib3.disable_warnings()


def _get(type_name: str, cql_filter: str | None = None,
         max_features: int | None = None, timeout: int = 90) -> list[dict] | None:
    params: dict = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": type_name,
        "outputFormat": "application/json",
    }
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    if max_features is not None:
        params["maxFeatures"] = max_features
    try:
        r = SESSION.get(WFS_BASE, params=params, timeout=timeout)
    except requests.RequestException as exc:
        log.warning("request fallida: %s", exc)
        return None
    tipo = r.headers.get("content-type", "")
    if "json" not in tipo:
        log.warning("%s respondió %s con content-type %r (%d bytes)",
                    type_name, r.status_code, tipo, len(r.content))
        return None
    try:
        return r.json().get("features", [])
    except ValueError:
        log.warning("%s respondió JSON ilegible (%d bytes)", type_name, len(r.content))
        return None


def _detect_id_field(props: dict) -> str | None:
    for candidate in ("id", "gid", "fid", "objectid", "ID", "GID"):
        if candidate in props:
            return candidate
    return None


def _fetch_range(type_name: str, id_field: str, lo: int, hi: int,
                 skipped: list[int]) -> list[dict]:
    if lo > hi:
        return []
    feats = _get(type_name, cql_filter=f"{id_field} >= {lo} AND {id_field} <= {hi}")
    if feats is not None:
        return feats
    if lo == hi:
        log.warning("registro corrupto, saltando %s=%d", id_field, lo)
        skipped.append(lo)
        return []
    mid = (lo + hi) // 2
    return (_fetch_range(type_name, id_field, lo, mid, skipped)
            + _fetch_range(type_name, id_field, mid + 1, hi, skipped))


def fetch_layer(type_name: str, id_step: int = 3000) -> tuple[list[dict], list[int]]:
    """Descarga completa de una capa. Devuelve (features, ids_saltados)."""
    first = _get(type_name, max_features=5)
    if not first:
        log.warning("capa vacía o inaccesible: %s", type_name)
        return [], []

    id_field = _detect_id_field(first[0]["properties"])
    if id_field is None:
        feats = _get(type_name, max_features=100_000, timeout=300) or []
        return feats, []

    features: list[dict] = []
    skipped: list[int] = []
    current = 0
    empty_pages = 0
    while empty_pages < 5:
        batch = _fetch_range(type_name, id_field, current, current + id_step - 1, skipped)
        if batch:
            features.extend(batch)
            current = max(int(f["properties"][id_field]) for f in batch) + 1
            empty_pages = 0
        else:
            current += id_step
            empty_pages += 1
    log.info("%s: %d features, %d saltados", type_name, len(features), len(skipped))
    return features, skipped


def save_geojson(features: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    log.info("guardado %s (%d features)", path, len(features))
