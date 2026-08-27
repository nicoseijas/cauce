"""Verifica la consistencia de datums entre curvas de inundación y estaciones.

Para cada localidad con manchas Tr: busca la estación más cercana (mismo
curso si es posible), y compara dos derivaciones del umbral candidato:
  a) cota_local de la curva            (lectura en la regla local)
  b) cota_oficial - cota_cero_estación (pasando por el datum oficial Wharton)
Si a ≈ b, el datum es compatible. Eso no demuestra que el nivel en la estación
represente hidráulicamente la localidad: la activación automática solo se
habilita además mediante la lista explícita `HIDRAULICA_VALIDADA`.
"""

import json
import logging
import math
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CRS_METRICO = "EPSG:32721"
DIST_MAX_ESTACION_M = 12_000
TOLERANCIA_DATUM_M = 0.75
INCERTIDUMBRE_UMBRAL_M = 1.0

# Fail-closed. Agregar un código únicamente después de documentar la relación
# nivel de estación -> nivel/mancha en la localidad con eventos completos.
HIDRAULICA_VALIDADA: set[str] = set()

# La clasificación no se infiere solo por proximidad. Las manchas de estos
# casos responden a mecanismos distintos y exigen modelos/evidencia distintos.
PLUVIAL_URBANA = {"SA-STO"}
COSTERA_ESTUARINA = {"CO-CLO", "CO-NPA"}
MECANISMOS_MIXTOS = {"CO-JLL"}
FLUVIAL_REGULADA = {"DU-CEN", "RN-LAR", "SA-CON", "SO-MER", "TA-PTS", "TA-SGP"}


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tipo_inundacion(codigo: str) -> tuple[str, bool, str]:
    if codigo in MECANISMOS_MIXTOS:
        return (
            "mixta_no_separada",
            False,
            "separar costera/estuarina de pluvial urbana antes de asociar sensores",
        )
    if codigo in PLUVIAL_URBANA:
        return (
            "pluvial_urbana",
            False,
            "lluvia → drenaje/escorrentía urbana → nivel local → mancha",
        )
    if codigo in COSTERA_ESTUARINA:
        return (
            "costera_estuarina",
            False,
            "caudal fluvial + marea/sudestada → nivel estuarino → mancha",
        )
    return (
        "fluvial",
        codigo in FLUVIAL_REGULADA,
        "lluvia → escorrentía/caudal → nivel fluvial → mancha",
    )


def estacion_superficial(tipo: Any) -> bool:
    texto = norm(str(tipo))
    return ("hidrom" in texto or "limnim" in texto) and "piezom" not in texto


def curso_tokens(curso: Any) -> set[str]:
    texto = norm(str(curso)).replace("nergo", "negro")
    for signo in ",.;:/()-":
        texto = texto.replace(signo, " ")
    stop = {"rio", "ro", "arroyo", "ao", "canada", "cda", "de", "del", "la", "las", "el", "los"}
    return {token for token in texto.split() if len(token) > 2 and token not in stop}


def cursos_compatibles(curso_curvas: Any, curso_estacion: Any) -> bool:
    curvas = curso_tokens(curso_curvas)
    estacion = curso_tokens(curso_estacion)
    return bool(curvas and estacion and curvas.intersection(estacion))


def diagnosticar_separacion(umbrales: list[dict]) -> tuple[list[dict], bool]:
    diagnostico = []
    ordenados = sorted(
        (u for u in umbrales if isinstance(u.get("nivel"), (int, float))),
        key=lambda u: u["nivel"],
    )
    limite = 2 * INCERTIDUMBRE_UMBRAL_M
    for inferior, superior in zip(ordenados, ordenados[1:]):
        separacion = round(superior["nivel"] - inferior["nivel"], 2)
        diagnostico.append({
            "periodo_inferior": inferior["periodo"],
            "periodo_superior": superior["periodo"],
            "separacion_m": separacion,
            "distinguible": separacion >= limite,
        })
    return diagnostico, all(item["distinguible"] for item in diagnostico)


def bloqueos_candidato(
    *,
    codigo: str,
    tipo: str,
    estacion: Any | None,
    curso_compatible: bool,
    umbrales: list[dict],
    distinguibles: bool,
) -> list[str]:
    bloqueos = []
    if estacion is None:
        bloqueos.append("sin_estacion_superficial_compatible")
    elif not curso_compatible:
        bloqueos.append("curso_estacion_no_coincide")
    if not umbrales or not any(u.get("datum_ok") is True for u in umbrales):
        bloqueos.append("datum_vertical_no_validado")
    if not distinguibles:
        bloqueos.append("umbrales_indistinguibles_dada_incertidumbre")
    if codigo not in HIDRAULICA_VALIDADA:
        bloqueos.append("relacion_hidraulica_no_validada_por_eventos_completos")
    if tipo == "pluvial_urbana":
        bloqueos.append("requiere_modelo_pluvial_urbano")
    elif tipo == "mixta_no_separada":
        bloqueos.append("mecanismos_costero_y_pluvial_no_separados")
    elif tipo == "costera_estuarina":
        bloqueos.append("requiere_nivel_costero_y_forzantes_estuarinas")
    return bloqueos


def normalizar_crs_cuencas(cuencas: Any) -> tuple[Any, dict[str, str]]:
    """Corrige el CRS mal declarado por el GeoJSON WFS antes de medir.

    La capa ``shp_cuencas_nivel2`` declara EPSG:4326 aunque sus coordenadas
    vienen en UTM 21S. Se verifica la magnitud antes de sobrescribir el CRS;
    una geometría ambigua falla en vez de producir una unión espacial falsa.
    """
    min_x, min_y, max_x, max_y = map(float, cuencas.total_bounds)
    declarado = str(cuencas.crs) if cuencas.crs else "sin declarar"
    es_geografico = -180 <= min_x <= max_x <= 180 and -90 <= min_y <= max_y <= 90
    es_utm_21s = (
        100_000 <= min_x <= 1_500_000
        and 100_000 <= max_x <= 1_500_000
        and 5_000_000 <= min_y <= 8_000_000
        and 5_000_000 <= max_y <= 8_000_000
    )
    if es_geografico:
        normalizadas = cuencas.to_crs(CRS_METRICO)
        accion = "reproyectado_desde_crs_declarado"
    elif es_utm_21s:
        normalizadas = cuencas.set_crs(CRS_METRICO, allow_override=True)
        accion = "crs_declarado_incorrecto_corregido_por_magnitud"
    else:
        raise ValueError(
            "CRS de cuencas ambiguo: "
            f"declarado={declarado}, bounds={[min_x, min_y, max_x, max_y]}"
        )
    return normalizadas, {
        "crs_declarado": declarado,
        "crs_interpretado": CRS_METRICO,
        "accion": accion,
    }


def main() -> None:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise SystemExit(
            "analizar_datum.py requiere el entorno científico: "
            ".venv\\Scripts\\python.exe pipeline/analizar_datum.py"
        ) from exc

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tr = gpd.read_file(ROOT / "web" / "public" / "data" / "inundacion_tr.geojson")
    est = gpd.read_file(ROOT / "data" / "processed" / "estaciones.geojson")
    tr_m = tr.to_crs(CRS_METRICO)
    est_m = est.to_crs(CRS_METRICO)
    cuencas_path = ROOT / "data" / "raw" / "cuencas_nivel2.geojson"
    cuencas_m = None
    metadatos_crs_cuencas = None
    if cuencas_path.exists():
        cuencas_m, metadatos_crs_cuencas = normalizar_crs_cuencas(
            gpd.read_file(cuencas_path)
        )
        log.info("cuencas nivel 2: %s", metadatos_crs_cuencas)

    resultado: dict[str, dict] = {}
    log.info("%-9s %-32s %6s | %-8s %10s %10s %8s", "loc", "estación", "dist",
             "curva", "cota_loc", "of-cero", "diff")

    for cod, grupo in tr_m.groupby("localidad_cod"):
        centro = grupo.geometry.centroid.union_all().centroid
        cuenca = None
        if cuencas_m is not None:
            contiene = cuencas_m[cuencas_m.geometry.covers(centro)]
            if not contiene.empty:
                fila_cuenca = contiene.sort_values("area").iloc[0]
                cuenca = {
                    "codigo_nivel2": int(fila_cuenca["c2"]),
                    "nombre": fila_cuenca["scp2"],
                    "fuente": "DINAGUA shp_cuencas_nivel2",
                    "crs_geometria_fuente": metadatos_crs_cuencas,
                    "crs_union_espacial": CRS_METRICO,
                }
        est_m["d"] = est_m.geometry.distance(centro)
        cand = est_m[
            (est_m["d"] < DIST_MAX_ESTACION_M)
            & est_m["tipo"].map(estacion_superficial)
        ].sort_values("d")
        if cand.empty:
            continue
        curso_curvas = str(grupo["curso"].mode().iat[0]) if grupo["curso"].notna().any() else ""
        tipo, regulada, cadena_fisica = tipo_inundacion(str(cod))
        mismo_curso = cand[
            [cursos_compatibles(curso_curvas, c) for c in cand["curso"].fillna("")]
        ]
        # Una regla fluvial no es sustituto de un modelo de drenaje urbano.
        # Si no existe sensor superficial del mismo curso, el caso pluvial se
        # conserva como cobertura faltante y no se le inventa un proxy.
        estacion = None if tipo in {"pluvial_urbana", "mixta_no_separada"} else (
            (mismo_curso if not mismo_curso.empty else cand).iloc[0]
        )
        curso_ok = bool(
            estacion is not None
            and cursos_compatibles(curso_curvas, estacion["curso"])
        )
        if estacion is None:
            resultado[cod] = {
                "estacion_id": None,
                "estacion": None,
                "estacion_tipo": None,
                "dist_m": None,
                "curso_curvas": curso_curvas,
                "curso_estacion": None,
                "curso_compatible": False,
                "tipo_inundacion": tipo,
                "regulada": regulada,
                "cadena_fisica_requerida": cadena_fisica,
                "cuenca_nivel2": cuenca,
                "datum_vertical": "sin estación superficial compatible",
                "relacion_hidraulica": "no_validada",
                "incertidumbre_umbral_m": INCERTIDUMBRE_UMBRAL_M,
                "umbrales_distinguibles": False,
                "separacion_umbrales": [],
                "bloqueos": bloqueos_candidato(
                    codigo=str(cod), tipo=tipo, estacion=None,
                    curso_compatible=False, umbrales=[], distinguibles=False,
                ),
                "auto_habilitada": False,
                "umbrales": [],
            }
            continue
        cero = estacion["cota_cero"]

        umbrales = []
        for _, c in grupo.sort_values("periodo").iterrows():
            local = c["cota_local"]
            oficial = c["cota_oficial"]
            local_ok = local is not None and math.isfinite(float(local))
            oficial_ok = oficial is not None and math.isfinite(float(oficial))
            cero_ok = cero is not None and math.isfinite(float(cero))
            derivado = (float(oficial) - float(cero)) if (oficial_ok and cero_ok) else None
            diff = (derivado - float(local)) if (derivado is not None and local_ok) else None
            ok = diff is not None and abs(diff) <= TOLERANCIA_DATUM_M
            log.info("%-9s %-32s %5.0fm | %-8s %10s %10s %8s%s",
                     cod, estacion["nombre"][:32], estacion["d"],
                     c["tipo_curva"],
                     f"{local:.2f}" if local is not None else "—",
                     f"{derivado:.2f}" if derivado is not None else "—",
                     f"{diff:+.2f}" if diff is not None else "—",
                     " OK" if ok else "")
            # Umbral por datum oficial (Wharton): cota_oficial - cota_cero.
            # cota_local difiere sistemáticamente ~0,9 m en varias localidades
            # (referencia local sin documentar): incertidumbre ~±1 m hasta
            # confirmar con DINAGUA.
            if derivado is not None and derivado > 0:
                umbrales.append({
                    "periodo": int(c["periodo"]),
                    "nivel": round(float(derivado), 2),
                    "tipo_curva": c["tipo_curva"],
                    "datum_ok": bool(ok),
                    "datum_estado": (
                        "compatible" if ok else
                        "incompatible" if diff is not None else
                        "sin_evidencia"
                    ),
                    "diferencia_datum_m": round(float(diff), 2) if diff is not None else None,
                    "incertidumbre_m": INCERTIDUMBRE_UMBRAL_M,
                    "intervalo_nivel_m": [
                        round(float(derivado) - INCERTIDUMBRE_UMBRAL_M, 2),
                        round(float(derivado) + INCERTIDUMBRE_UMBRAL_M, 2),
                    ],
                })

        if umbrales:
            # varias manchas del mismo período: activa la de umbral más bajo
            por_periodo: dict[int, dict] = {}
            for u in umbrales:
                previo = por_periodo.get(u["periodo"])
                if (
                    previo is None
                    or (u["datum_ok"] and not previo["datum_ok"])
                    or (u["datum_ok"] == previo["datum_ok"] and u["nivel"] < previo["nivel"])
                ):
                    por_periodo[u["periodo"]] = u
            umbrales_finales = sorted(por_periodo.values(), key=lambda u: u["periodo"])
            separaciones, distinguibles = diagnosticar_separacion(umbrales_finales)
            bloqueos = bloqueos_candidato(
                codigo=str(cod), tipo=tipo, estacion=estacion,
                curso_compatible=curso_ok, umbrales=umbrales_finales,
                distinguibles=distinguibles,
            )
            resultado[cod] = {
                "estacion_id": int(estacion["id"]),
                "estacion": estacion["nombre"],
                "estacion_tipo": estacion["tipo"],
                "dist_m": round(float(estacion["d"])),
                "curso_curvas": curso_curvas,
                "curso_estacion": estacion["curso"],
                "curso_compatible": curso_ok,
                "tipo_inundacion": tipo,
                "regulada": regulada,
                "cadena_fisica_requerida": cadena_fisica,
                "cuenca_nivel2": cuenca,
                "datum_vertical": "Wharton (según campos de DINAGUA)",
                "relacion_hidraulica": (
                    "validada" if cod in HIDRAULICA_VALIDADA else "no_validada"
                ),
                "incertidumbre_umbral_m": INCERTIDUMBRE_UMBRAL_M,
                "umbrales_distinguibles": distinguibles,
                "separacion_umbrales": separaciones,
                "bloqueos": bloqueos,
                "auto_habilitada": not bloqueos,
                "umbrales": umbrales_finales,
            }

    out = ROOT / "web" / "public" / "data" / "activacion.json"
    out.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("")
    habilitadas = sum(v["auto_habilitada"] for v in resultado.values())
    log.info("localidades candidatas: %d | habilitadas automáticamente: %d -> %s",
             len(resultado), habilitadas, out)


if __name__ == "__main__":
    main()
