"""Identificadores estables y URL legibles de las estaciones.

Cada estación recibe dos identificadores con roles distintos. El canónico
(`estacion_id`) combina organismo e identificador original y no cambia aunque
el organismo renombre la estación. El `slug` es la URL legible y sí deriva del
nombre publicado; cuando dos organismos miden el mismo lugar, el que no tiene
prioridad lleva el organismo como sufijo.

La asignación depende del conjunto completo de estaciones, no de cada una por
separado: solo así se pueden detectar las colisiones de nombre.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# Ante nombres iguales, el primero de la lista conserva el slug limpio y los
# demás lo llevan sufijado. Las estaciones nacionales van primero porque son
# las que el público busca por nombre.
PRIORIDAD_ORGANISMOS = ("dinagua", "ctm", "ute", "ina", "ana", "sohma")

# Los ids negativos son centinelas del pipeline, no identificadores de origen.
IDS_SENTINELA = {-1: ("ctm", "salto-grande"), -2: ("ute", "palmar-previsto")}


class IdentidadError(ValueError):
    """El conjunto de estaciones no permite asignar identificadores estables."""


def slugificar(texto: str) -> str:
    """Convierte un nombre a minúsculas ASCII separadas por guiones."""
    sin_diacriticos = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", sin_diacriticos.lower())).strip("-")


def partir_id_externo(id_externo: str) -> tuple[str, str]:
    """Separa `ina-78` en organismo e identificador de origen."""
    organismo, _, resto = id_externo.partition("-")
    if not resto:
        raise IdentidadError(f"identificador externo sin organismo: {id_externo!r}")
    return organismo, resto


def identidad_canonica(id_origen: Any) -> tuple[str, str]:
    """Devuelve (organismo, identificador de origen) para cualquier estación."""
    if isinstance(id_origen, int):
        if id_origen in IDS_SENTINELA:
            return IDS_SENTINELA[id_origen]
        if id_origen < 0:
            raise IdentidadError(f"id negativo sin centinela declarado: {id_origen}")
        return "dinagua", str(id_origen)
    if isinstance(id_origen, str) and id_origen:
        return partir_id_externo(id_origen)
    raise IdentidadError(f"id de estación no utilizable: {id_origen!r}")


def _orden_prioridad(organismo: str) -> tuple[int, str]:
    try:
        return (PRIORIDAD_ORGANISMOS.index(organismo), "")
    except ValueError:
        return (len(PRIORIDAD_ORGANISMOS), organismo)


def asignar_identidad(estaciones: Iterable[dict]) -> list[dict]:
    """Agrega `estacion_id` y `slug` a cada estación y devuelve la lista.

    Muta las estaciones recibidas, que es como el resto del pipeline construye
    el estado. Falla si dos estaciones comparten identificador canónico.
    """
    lista = list(estaciones)
    identidades = []
    for estacion in lista:
        organismo, origen = identidad_canonica(estacion.get("id"))
        identidades.append((estacion, organismo, f"{organismo}-{origen}"))

    canonicos = [canonico for _, _, canonico in identidades]
    repetidos = sorted({c for c in canonicos if canonicos.count(c) > 1})
    if repetidos:
        raise IdentidadError(f"identificadores canónicos repetidos: {repetidos}")

    base_de = {
        canonico: slugificar(estacion.get("nombre") or "") or canonico
        for estacion, _, canonico in identidades
    }
    veces = {}
    for base in base_de.values():
        veces[base] = veces.get(base, 0) + 1

    # El desempate ordena por prioridad de organismo y luego por identificador,
    # de modo que agregar una estación no reasigne el slug de las existentes.
    for base, cuenta in veces.items():
        if cuenta < 2:
            continue
        competidores = sorted(
            (c for c, b in base_de.items() if b == base),
            key=lambda c: (_orden_prioridad(c.split("-", 1)[0]), c),
        )
        for canonico in competidores[1:]:
            base_de[canonico] = f"{base}-{canonico.split('-', 1)[0]}"

    slugs = list(base_de.values())
    colisiones = sorted({s for s in slugs if slugs.count(s) > 1})
    if colisiones:
        raise IdentidadError(f"slugs sin desambiguar: {colisiones}")

    for estacion, _, canonico in identidades:
        estacion["estacion_id"] = canonico
        estacion["slug"] = base_de[canonico]
    return lista


def indice_alias(estaciones: Iterable[dict]) -> dict[str, str]:
    """Mapa de identificador canónico a slug, para resolver enlaces viejos."""
    return {
        e["estacion_id"]: e["slug"]
        for e in estaciones
        if e.get("estacion_id") and e.get("slug")
    }
