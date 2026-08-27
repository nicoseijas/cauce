"""Construye el catálogo científico y las sumas de integridad publicadas.

El catálogo base contiene las decisiones humanas (procedencia, licencia, CRS,
resolución y limitaciones). Este módulo agrega únicamente propiedades que se
pueden reproducir desde los artefactos: tamaño, hash, extensión, conteos y
esquema observado. No descarga ni modifica las fuentes primarias.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "web" / "public" / "data"
BASE_PATH = ROOT / "data" / "referencia" / "catalogo_base.json"
CATALOG_PATH = DATA_DIR / "datapackage.json"
CHECKSUM_PATH = DATA_DIR / "checksums.sha256"
GENERATED_NAMES = {CATALOG_PATH.name, CHECKSUM_PATH.name}
TEXTO_SOLO_LF = {".json", ".geojson", ".sha256"}
QC_STATES = {"ok", "vencido", "dudoso", "rechazado", "sin_dato"}
SOURCE_STATES = {"ok", "caida", "vencida", "sin_fecha", "no_implementada"}


class CatalogError(ValueError):
    """Error de contrato o integridad de los productos publicados."""


def _reject_constant(value: str) -> None:
    raise CatalogError(f"constante JSON no finita: {value}")


def load_json_strict(path: Path) -> Any:
    """Carga JSON y rechaza NaN/Infinity, que no pertenecen a JSON estricto."""
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"no se pudo leer JSON estricto en {path}: {exc}") from exc


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _nombre_legible(path: Path) -> str:
    """Ruta relativa al repositorio cuando lo está; completa en otro caso."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _file_hash(path: Path) -> str:
    contenido = path.read_bytes()
    # El hash publicado identifica bytes, así que un archivo de texto guardado
    # con CRLF en Windows y con LF en Linux daría dos sumas para el mismo
    # contenido. .gitattributes fija LF; esto detecta el archivo que se escapó
    # antes de que la diferencia aparezca como un fallo remoto inexplicable.
    if path.suffix in TEXTO_SOLO_LF and b"\r\n" in contenido:
        raise CatalogError(
            f"{_nombre_legible(path)} tiene fin de línea CRLF; el hash publicado "
            f"dejaría de coincidir en otra plataforma. Regrabar el archivo con LF."
        )
    return _sha256(contenido)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "any"


def _merge_types(types: set[str]) -> tuple[str, list[str]]:
    non_null = types - {"null"}
    if non_null <= {"integer", "number"} and non_null:
        primary = "number" if "number" in non_null else "integer"
    elif len(non_null) == 1:
        primary = next(iter(non_null))
    elif not non_null:
        primary = "any"
    else:
        primary = "any"
    return primary, sorted(types)


def infer_fields(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Infere un esquema tabular conservador para las propiedades GeoJSON."""
    seen: dict[str, set[str]] = {}
    present = Counter[str]()
    for record in records:
        for name, value in record.items():
            seen.setdefault(name, set()).add(_json_type(value))
            present[name] += 1
    fields: list[dict[str, Any]] = []
    total = len(records)
    for name in sorted(seen):
        primary, observed = _merge_types(seen[name])
        fields.append(
            {
                "name": name,
                "type": primary,
                "nullable": "null" in seen[name] or present[name] < total,
                "observed_types": observed,
            }
        )
    return fields


def _iter_positions(coordinates: Any) -> Iterable[tuple[float, float]]:
    if not isinstance(coordinates, list) or not coordinates:
        raise CatalogError("coordenadas GeoJSON vacías o inválidas")
    if isinstance(coordinates[0], (int, float)) and not isinstance(coordinates[0], bool):
        if len(coordinates) < 2:
            raise CatalogError("posición GeoJSON con menos de dos ordenadas")
        lon, lat = coordinates[0], coordinates[1]
        if isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise CatalogError("posición GeoJSON no numérica")
        lon_f, lat_f = float(lon), float(lat)
        if not math.isfinite(lon_f) or not math.isfinite(lat_f):
            raise CatalogError("posición GeoJSON no finita")
        yield lon_f, lat_f
        return
    for child in coordinates:
        yield from _iter_positions(child)


def _geometry_positions(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    geom_type = geometry.get("type")
    if geom_type == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list):
            raise CatalogError("GeometryCollection sin geometries")
        for child in geometries:
            if not isinstance(child, dict):
                raise CatalogError("geometría hija inválida")
            yield from _geometry_positions(child)
        return
    if geom_type not in {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon",
    }:
        raise CatalogError(f"tipo de geometría no soportado: {geom_type!r}")
    yield from _iter_positions(geometry.get("coordinates"))


def _temporal_extent(records: list[dict[str, Any]], fields: list[str]) -> dict[str, str] | None:
    values: list[str] = []
    for record in records:
        for field in fields:
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    if not values:
        return None
    return {"start": min(values), "end": max(values)}


def analyze_geojson(data: Any, temporal_fields: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise CatalogError("el GeoJSON debe ser un FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list):
        raise CatalogError("FeatureCollection sin lista features")

    geometry_counts: Counter[str] = Counter()
    properties: list[dict[str, Any]] = []
    bbox = [math.inf, math.inf, -math.inf, -math.inf]
    position_count = 0
    null_geometry_count = 0
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise CatalogError(f"feature {index} inválida")
        props = feature.get("properties")
        if props is None:
            props = {}
        if not isinstance(props, dict):
            raise CatalogError(f"properties de feature {index} no es un objeto")
        properties.append(props)
        geometry = feature.get("geometry")
        if geometry is None:
            null_geometry_count += 1
            continue
        if not isinstance(geometry, dict):
            raise CatalogError(f"geometry de feature {index} inválida")
        geom_type = geometry.get("type")
        geometry_counts[str(geom_type)] += 1
        for lon, lat in _geometry_positions(geometry):
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise CatalogError(
                    f"coordenada fuera de OGC:CRS84 en feature {index}: [{lon}, {lat}]"
                )
            bbox[0] = min(bbox[0], lon)
            bbox[1] = min(bbox[1], lat)
            bbox[2] = max(bbox[2], lon)
            bbox[3] = max(bbox[3], lat)
            position_count += 1

    result: dict[str, Any] = {
        "record_count": len(features),
        "geometry_counts": dict(sorted(geometry_counts.items())),
        "null_geometry_count": null_geometry_count,
        "position_count": position_count,
        "schema": {"fields": infer_fields(properties)},
    }
    if position_count:
        result["spatial"] = {
            "crs": "OGC:CRS84",
            "axis_order": ["longitude", "latitude"],
            "bbox": [round(value, 7) for value in bbox],
        }
    temporal = _temporal_extent(properties, temporal_fields or [])
    if temporal:
        result["temporal"] = temporal
    return result


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_station_count(data: dict[str, Any]) -> int:
    total = len(data.get("estaciones", []))
    for key in ("ina", "ana", "sohma"):
        section = data.get(key)
        if isinstance(section, dict) and isinstance(section.get("estaciones"), list):
            total += len(section["estaciones"])
    return total


def _state_stations(data: dict[str, Any]) -> list[dict[str, Any]]:
    stations: list[Any] = list(data.get("estaciones", []))
    for key in ("ina", "ana", "sohma"):
        section = data.get(key)
        if isinstance(section, dict) and isinstance(section.get("estaciones"), list):
            stations.extend(section["estaciones"])
    return [station for station in stations if isinstance(station, dict)]


def _state_dates(data: dict[str, Any], derivatives_only: bool = False) -> list[datetime]:
    dates: list[datetime] = []
    for station in _state_stations(data):
        for variable in ("nivel", "caudal"):
            if derivatives_only:
                qc = station.get(f"qc_{variable}")
                if not isinstance(qc, dict) or qc.get("apto_derivados") is not True:
                    continue
            parsed = _parse_datetime(station.get(f"{variable}_fecha"))
            if parsed:
                dates.append(parsed)
    return dates


def _state_forecast_dates(data: dict[str, Any]) -> list[datetime]:
    ute = data.get("ute_rio_negro")
    if not isinstance(ute, dict) or not isinstance(ute.get("dias"), list):
        return []
    dates: list[datetime] = []
    for day in ute["dias"]:
        if isinstance(day, dict):
            parsed = _parse_datetime(day.get("fecha"))
            if parsed:
                dates.append(parsed)
    return dates


def analyze_json(name: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CatalogError(f"{name} debe contener un objeto JSON")
    result: dict[str, Any] = {"schema": {"fields": infer_fields([data])}}
    if name == "estado_actual.json":
        validar_estado_v3(data)
        result["record_count"] = _state_station_count(data)
        result["schema_version"] = data["schema_version"]
        result["qc_version"] = data["control_calidad"]["version"]
        raw_dates = _state_dates(data)
        if raw_dates:
            result["temporal"] = {
                "start": _iso_utc(min(raw_dates)),
                "end": _iso_utc(max(raw_dates)),
                "scope": "fechas de medición publicadas, incluidas vencidas o rechazadas",
            }
        usable_dates = _state_dates(data, derivatives_only=True)
        if usable_dates:
            result["usable_temporal"] = {
                "start": _iso_utc(min(usable_dates)),
                "end": _iso_utc(max(usable_dates)),
                "scope": "mediciones aptas para derivados según QC al generar el snapshot",
            }
        forecast_dates = _state_forecast_dates(data)
        if forecast_dates:
            ute = data["ute_rio_negro"]
            result["forecast_temporal"] = {
                "start": _iso_utc(min(forecast_dates)),
                "end": _iso_utc(max(forecast_dates)),
                "horizon_days": ute.get("horizonte_dias"),
                "probability": ute.get("probabilidad"),
                "uncertainty": ute.get("incertidumbre"),
            }
    elif name == "series.json":
        stations = data.get("estaciones")
        if not isinstance(stations, dict):
            raise CatalogError("series.json no contiene estaciones")
        result["record_count"] = len(stations)
        result["window_days"] = data.get("ventana_dias")
        qc = data.get("control_calidad")
        if isinstance(qc, dict):
            result["qc_version"] = qc.get("version")
        epochs: list[int | float] = []
        for station in stations.values():
            if not isinstance(station, dict):
                continue
            for variable in ("nivel", "caudal"):
                points = station.get(variable, [])
                if not isinstance(points, list):
                    continue
                for point in points:
                    if (
                        isinstance(point, list) and len(point) >= 2
                        and isinstance(point[0], (int, float)) and not isinstance(point[0], bool)
                        and math.isfinite(float(point[0]))
                    ):
                        epochs.append(point[0])
        if epochs:
            result["temporal"] = {
                "start": _iso_utc(datetime.fromtimestamp(min(epochs), timezone.utc)),
                "end": _iso_utc(datetime.fromtimestamp(max(epochs), timezone.utc)),
            }
    elif name == "validacion_activacion.json":
        localidades = data.get("localidades")
        fuentes = data.get("fuentes_series")
        resumen = data.get("resumen")
        if not isinstance(localidades, dict) or not isinstance(fuentes, list) or not isinstance(resumen, dict):
            raise CatalogError("validacion_activacion.json no cumple su estructura mínima")
        anios = sorted(
            fuente["anio"] for fuente in fuentes
            if isinstance(fuente, dict) and isinstance(fuente.get("anio"), int)
        )
        result["record_count"] = len(localidades)
        result["schema_version"] = data.get("schema_version")
        result["validation_summary"] = resumen
        if anios:
            result["temporal"] = {
                "start": f"{anios[0]}-01-01",
                "end": f"{anios[-1]}-12-31",
                "scope": "años de las series históricas evaluadas; no representa vigencia operativa",
            }
    else:
        result["record_count"] = len(data)
    return result


def validar_estado_v3(data: Any) -> None:
    """Comprueba invariantes de seguridad que el JSON Schema documenta."""
    if not isinstance(data, dict) or data.get("schema_version") != 3:
        raise CatalogError("estado_actual.json no cumple schema_version=3")
    required = {
        "generado", "fuentes", "fuentes_detalle", "estaciones", "factores_curso",
        "activacion", "activacion_cobertura", "control_calidad",
    }
    missing = required - data.keys()
    if missing:
        raise CatalogError(f"estado v3 sin campos requeridos: {sorted(missing)}")
    if _parse_datetime(data["generado"]) is None:
        raise CatalogError("estado v3 con fecha generado inválida")
    if not isinstance(data["fuentes"], dict) or any(
        status not in SOURCE_STATES for status in data["fuentes"].values()
    ):
        raise CatalogError("estado v3 contiene un estado de fuente inválido")
    if not isinstance(data["estaciones"], list):
        raise CatalogError("estado v3 estaciones no es una lista")
    for station in data["estaciones"]:
        if not isinstance(station, dict):
            raise CatalogError("estado v3 contiene una estación inválida")
        for coordinate, low, high in (("lon", -180, 180), ("lat", -90, 90)):
            value = station.get(coordinate)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise CatalogError(f"estación {station.get('id')} con {coordinate} inválida")
        for variable in ("nivel", "caudal"):
            qc = station.get(f"qc_{variable}")
            if not isinstance(qc, dict) or qc.get("estado") not in QC_STATES:
                raise CatalogError(f"estación {station.get('id')} sin QC válido para {variable}")
            if not isinstance(qc.get("apto_derivados"), bool):
                raise CatalogError(f"QC de estación {station.get('id')} sin aptitud explícita")
            value = station.get(variable)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise CatalogError(f"estación {station.get('id')} con {variable} no finito")
    factors = data["factores_curso"]
    if not isinstance(factors, dict):
        raise CatalogError("estado v3 factores_curso no es un objeto")
    for course, factor in factors.items():
        if not isinstance(factor, dict):
            raise CatalogError(f"factor inválido para {course}")
        if factor.get("clasificacion") != "estimado":
            raise CatalogError(f"factor de {course} no está rotulado estimado")
        if factor.get("insumo_clasificacion") not in {"observado", "pronosticado"}:
            raise CatalogError(f"factor de {course} sin clasificación de insumo")
        age = factor.get("antiguedad_h")
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not -1 <= age <= 48:
            raise CatalogError(f"factor de {course} usa un insumo vencido")
        if not factor.get("qc_version"):
            raise CatalogError(f"factor de {course} sin versión QC")
    coverage = data["activacion_cobertura"]
    coverage_fields = {
        "configuradas", "habilitadas", "evaluadas", "rechazadas_qc",
        "con_estacion_superficial", "con_curso_compatible",
        "tipos_inundacion", "bloqueos", "fuente_disponible",
    }
    if not isinstance(coverage, dict) or not coverage_fields <= coverage.keys():
        raise CatalogError("estado v3 sin cobertura de activación completa")


def _published_assets() -> set[str]:
    return {
        path.name
        for path in DATA_DIR.iterdir()
        if path.is_file() and path.suffix in {".json", ".geojson"}
        and path.name not in GENERATED_NAMES
    }


def build_outputs() -> tuple[bytes, bytes]:
    base = load_json_strict(BASE_PATH)
    if not isinstance(base, dict) or not isinstance(base.get("resources"), dict):
        raise CatalogError("catalogo_base.json no contiene resources")
    configured = set(base["resources"])
    published = _published_assets()
    if configured != published:
        missing = sorted(published - configured)
        extra = sorted(configured - published)
        raise CatalogError(f"inventario desalineado; sin metadatos={missing}, sin archivo={extra}")

    resources: list[dict[str, Any]] = []
    generated_dates: list[datetime] = []
    metadata_date = _parse_datetime(base.get("metadata_updated"))
    if metadata_date:
        generated_dates.append(metadata_date)
    for name in sorted(configured):
        path = DATA_DIR / name
        content = path.read_bytes()
        data = load_json_strict(path)
        manual = dict(base["resources"][name])
        temporal_fields = manual.pop("temporal_fields", [])
        analysis = (
            analyze_geojson(data, temporal_fields)
            if path.suffix == ".geojson"
            else analyze_json(name, data)
        )
        for date_key in ("generado",):
            parsed = _parse_datetime(data.get(date_key)) if isinstance(data, dict) else None
            if parsed:
                generated_dates.append(parsed)
        resource = {
            "name": path.stem.replace("_", "-"),
            "path": name,
            "profile": "data-resource",
            "format": "geojson" if path.suffix == ".geojson" else "json",
            "mediatype": "application/geo+json" if path.suffix == ".geojson" else "application/json",
            "bytes": len(content),
            "hash": f"sha256:{_sha256(content)}",
            **manual,
            **analysis,
        }
        resources.append(resource)

    created = max(generated_dates) if generated_dates else datetime.now(timezone.utc)
    package_info = base["package"]
    catalog = {
        "profile": "data-package",
        **package_info,
        "created": _iso_utc(created),
        "metadata_schema_version": base.get("schema_version"),
        "licenses": [
            {
                "name": "mixed",
                "title": "Licencias mixtas; consultar sources y cada recurso",
                "path": f"{package_info.get('repository', '')}/blob/main/README.md#licencia-y-datos",
            }
        ],
        "contributors": [{"title": "Nicolás Seijas", "role": "author"}],
        "sources": [dict({"id": key}, **value) for key, value in sorted(base["sources"].items())],
        "spatial_conventions": {
            "horizontal_storage_crs": "OGC:CRS84",
            "axis_order": ["longitude", "latitude"],
            "processing_crs": "EPSG:32721 (WGS 84 / UTM zone 21S), cuando se declara por recurso",
            "vertical_reference": "Mixta y dependiente de la estación/estudio; no comparar niveles entre estaciones sin transformación documentada.",
        },
        "reproducibility": {
            "catalog_source": "data/referencia/catalogo_base.json",
            "catalog_builder": "pipeline/build_catalogo.py",
            "python_lock": "requirements.lock",
            "web_lock": "web/package-lock.json",
            "integrity": "checksums.sha256",
        },
        "resources": resources,
    }
    catalog_bytes = _json_bytes(catalog)

    checksum_entries = [(name, _file_hash(DATA_DIR / name)) for name in sorted(configured)]
    for schema_path in sorted((DATA_DIR / "schema").glob("*.json")):
        schema_relative = schema_path.relative_to(DATA_DIR).as_posix()
        checksum_entries.append((schema_relative, _file_hash(schema_path)))
    checksum_entries.append((CATALOG_PATH.name, _sha256(catalog_bytes)))
    checksum_entries.sort()
    checksum_bytes = "".join(f"{digest}  {name}\n" for name, digest in checksum_entries).encode("ascii")
    return catalog_bytes, checksum_bytes


def _check_or_write(path: Path, expected: bytes, check: bool) -> bool:
    current = path.read_bytes() if path.exists() else None
    if current == expected:
        return True
    if check:
        print(f"DESACTUALIZADO: {path.relative_to(ROOT)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(expected)
    print(f"escrito: {path.relative_to(ROOT)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verifica sin modificar archivos")
    args = parser.parse_args()
    try:
        catalog, checksums = build_outputs()
    except CatalogError as exc:
        print(f"ERROR: {exc}")
        return 1
    ok_catalog = _check_or_write(CATALOG_PATH, catalog, args.check)
    ok_checksums = _check_or_write(CHECKSUM_PATH, checksums, args.check)
    if args.check and ok_catalog and ok_checksums:
        print("catálogo y sumas de integridad reproducibles: OK")
    return 0 if ok_catalog and ok_checksums else 1


if __name__ == "__main__":
    raise SystemExit(main())
