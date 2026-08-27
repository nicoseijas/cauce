"""Índice de búsqueda de las entidades que el mapa puede mostrar.

Reúne estaciones, cursos, localidades, departamentos y represas en un archivo
liviano para que buscar no obligue a descargar la red completa, que pesa dos
órdenes de magnitud más. No consulta fuentes externas: solo reordena lo que
otros pasos del pipeline ya publicaron.

Cada entidad declara dónde encuadrar el mapa. Los cursos traen su envolvente
porque un río no se ve en un punto; el resto trae una coordenada.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "public" / "data"
SALIDA = DATA / "buscador.json"

SCHEMA_VERSION = 1

# El nombre de localidad llega en mayúsculas y sin diacríticos desde la capa de
# amenazas. Estas partículas quedan en minúscula al recomponerlo; los acentos
# que la fuente no trae no se inventan, salvo que otra capa publique el mismo
# nombre ya acentuado.
PARTICULAS = {"de", "del", "la", "las", "los", "y", "el", "al", "e"}

REPRESAS = [
    {"nombre": "Salto Grande", "curso": "Río Uruguay", "lat": -31.2758, "lon": -57.9394},
    {"nombre": "Rincón del Bonete", "curso": "Río Negro", "lat": -32.8308, "lon": -56.4211},
    {"nombre": "Baygorria", "curso": "Río Negro", "lat": -32.8729, "lon": -56.8056},
    {"nombre": "Palmar (Constitución)", "curso": "Río Negro", "lat": -33.0556, "lon": -57.4507},
]


class BuscadorError(ValueError):
    """Falta un insumo publicado o tiene una forma inesperada."""


def leer_json(nombre: str) -> Any:
    ruta = DATA / nombre
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuscadorError(f"no se pudo leer {ruta}: {exc}") from exc


def titular(texto: str) -> str:
    """Recompone un topónimo en mayúsculas sin alterar los que ya vienen bien."""
    if texto != texto.upper():
        return texto
    palabras = texto.casefold().split()
    return " ".join(
        p if i and p in PARTICULAS else p.capitalize()
        for i, p in enumerate(palabras)
    )


def _coordenadas(geometria: dict) -> Iterable[tuple[float, float]]:
    """Aplana cualquier geometría GeoJSON a pares (lon, lat)."""
    pila = [geometria.get("coordinates")]
    while pila:
        actual = pila.pop()
        if not isinstance(actual, list) or not actual:
            continue
        if isinstance(actual[0], (int, float)) and len(actual) >= 2:
            yield float(actual[0]), float(actual[1])
        else:
            pila.extend(actual)


def envolvente(geometria: dict) -> list[float] | None:
    """Devuelve [oeste, sur, este, norte] o None si no hay coordenadas."""
    puntos = list(_coordenadas(geometria))
    if not puntos:
        return None
    lons = [p[0] for p in puntos]
    lats = [p[1] for p in puntos]
    return [round(min(lons), 5), round(min(lats), 5), round(max(lons), 5), round(max(lats), 5)]


def entidades_estaciones(estado: dict) -> list[dict]:
    estaciones = list(estado.get("estaciones") or [])
    for clave in ("ina", "ana", "sohma"):
        estaciones.extend((estado.get(clave) or {}).get("estaciones") or [])
    salida = []
    for e in estaciones:
        if not e.get("slug"):
            raise BuscadorError(f"estación sin slug: {e.get('nombre')!r}")
        salida.append({
            "tipo": "estacion",
            "nombre": e["nombre"],
            "contexto": e.get("curso") or e.get("fuente"),
            "slug": e["slug"],
            "lat": e["lat"],
            "lon": e["lon"],
        })
    return salida


def entidades_cursos(red: dict) -> list[dict]:
    por_nombre: dict[str, list[float]] = {}
    for feature in red.get("features", []):
        nombre = (feature.get("properties") or {}).get("nombre")
        caja = envolvente(feature.get("geometry") or {})
        if not nombre or not caja:
            continue
        previa = por_nombre.get(nombre)
        por_nombre[nombre] = caja if previa is None else [
            min(previa[0], caja[0]), min(previa[1], caja[1]),
            max(previa[2], caja[2]), max(previa[3], caja[3]),
        ]
    return [
        {
            "tipo": "curso",
            "nombre": nombre,
            "contexto": None,
            "bbox": caja,
            "lat": round((caja[1] + caja[3]) / 2, 5),
            "lon": round((caja[0] + caja[2]) / 2, 5),
        }
        for nombre, caja in sorted(por_nombre.items())
    ]


def entidades_localidades(amenazas: dict, capitales: dict) -> list[dict]:
    """Une localidades con amenaza y capitales departamentales sin duplicarlas.

    Cuando ambas capas publican el mismo topónimo gana el de capitales, que
    conserva los diacríticos que la capa de amenazas perdió.
    """
    por_clave: dict[str, dict] = {}
    for feature in amenazas.get("features", []):
        p = feature.get("properties") or {}
        nombre = titular(p.get("localidad") or "")
        lon, lat = (feature.get("geometry") or {}).get("coordinates", (None, None))
        if not nombre or lat is None:
            continue
        por_clave[nombre.casefold()] = {
            "tipo": "localidad",
            "nombre": nombre,
            "contexto": titular(p.get("departamento") or "") or None,
            "lat": lat,
            "lon": lon,
        }
    for feature in capitales.get("features", []):
        p = feature.get("properties") or {}
        nombre = p.get("nombre")
        lon, lat = (feature.get("geometry") or {}).get("coordinates", (None, None))
        if not nombre or lat is None:
            continue
        clave = _sin_diacriticos(nombre).casefold()
        anterior = next(
            (v for k, v in por_clave.items() if _sin_diacriticos(k) == clave), None
        )
        if anterior is not None:
            anterior["nombre"] = nombre
            continue
        por_clave[nombre.casefold()] = {
            "tipo": "localidad",
            "nombre": nombre,
            "contexto": None,
            "lat": lat,
            "lon": lon,
        }
    return sorted(por_clave.values(), key=lambda e: e["nombre"])


def _sin_diacriticos(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def entidades_departamentos(capa: dict) -> list[dict]:
    salida = []
    for feature in capa.get("features", []):
        nombre = (feature.get("properties") or {}).get("nombre")
        lon, lat = (feature.get("geometry") or {}).get("coordinates", (None, None))
        if nombre and lat is not None:
            salida.append({
                "tipo": "departamento",
                "nombre": nombre,
                "contexto": None,
                "lat": lat,
                "lon": lon,
            })
    return sorted(salida, key=lambda e: e["nombre"])


def entidades_represas() -> list[dict]:
    return [
        {
            "tipo": "represa",
            "nombre": r["nombre"],
            "contexto": r["curso"],
            "lat": r["lat"],
            "lon": r["lon"],
        }
        for r in REPRESAS
    ]


def construir() -> dict:
    estado = leer_json("estado_actual.json")
    entidades = (
        entidades_estaciones(estado)
        + entidades_cursos(leer_json("red_nombres.geojson"))
        + entidades_localidades(leer_json("amenazas.geojson"), leer_json("capitales.geojson"))
        + entidades_departamentos(leer_json("departamentos_nombres.geojson"))
        + entidades_represas()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nota": (
            "Índice de navegación. Los topónimos de localidad provienen de la capa "
            "de amenazas, que los publica en mayúsculas y sin diacríticos."
        ),
        "entidades": entidades,
    }


def main() -> int:
    try:
        indice = construir()
    except BuscadorError as exc:
        print(f"ERROR: {exc}")
        return 1
    SALIDA.write_bytes(
        (json.dumps(indice, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )
    conteo: dict[str, int] = {}
    for e in indice["entidades"]:
        conteo[e["tipo"]] = conteo.get(e["tipo"], 0) + 1
    print(
        f"escrito: {SALIDA.relative_to(ROOT)} "
        f"({len(indice['entidades'])} entidades, {SALIDA.stat().st_size // 1024} KB) {conteo}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
