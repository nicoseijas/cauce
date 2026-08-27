"""Publica evidencia retrospectiva de las activaciones candidatas.

La unidad de evaluación es siempre un evento completo dentro de su cuenca;
nunca se reparten lecturas del mismo evento entre entrenamiento y prueba. El
resultado es exploratorio: `curvas_cri` no es un registro exhaustivo de días
con y sin inundación, y una coincidencia no aprueba ni el datum ni la relación
hidráulica estación-localidad.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

try:
    from .validar_activacion import (
        CSV_CKAN,
        EQUIV_ESTACION,
        cargar_series,
        detectar_escalones,
        eventos_cri,
        maximo_diario,
        periodo_disparado,
        segmentos_confiables,
    )
except ImportError:  # ejecución directa: python pipeline/build_validacion_activacion.py
    from validar_activacion import (
        CSV_CKAN,
        EQUIV_ESTACION,
        cargar_series,
        detectar_escalones,
        eventos_cri,
        maximo_diario,
        periodo_disparado,
        segmentos_confiables,
    )


ROOT = Path(__file__).resolve().parents[1]
DATOS = ROOT / "web" / "public" / "data"
SALIDA = DATOS / "validacion_activacion.json"
VENTANA_ANALISIS_DIAS = 7
MIN_PRE_POST_H = 24
HUECO_MAX_H = 12
CAMBIO_MIN_EVENTO_M = 0.20


def _iso(fecha: datetime) -> str:
    return fecha.isoformat(timespec="minutes")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_gap_h(serie: list[tuple[datetime, float]]) -> float | None:
    if len(serie) < 2:
        return None
    return max(
        (b[0] - a[0]).total_seconds() / 3600
        for a, b in zip(serie, serie[1:])
    )


def analizar_evento(
    evento: date,
    serie: list[tuple[datetime, float]],
    umbrales: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evalúa un hidrograma completo alrededor de una fecha CRI."""
    inicio = datetime.combine(evento - timedelta(days=VENTANA_ANALISIS_DIAS), time.min)
    fin = datetime.combine(evento + timedelta(days=VENTANA_ANALISIS_DIAS + 1), time.min)
    ventana = [(fecha, valor) for fecha, valor in serie if inicio <= fecha < fin]
    base: dict[str, Any] = {
        "fecha_evento": evento.isoformat(),
        "ventana": {"inicio": inicio.date().isoformat(), "fin": (fin - timedelta(days=1)).date().isoformat()},
        "observaciones": len(ventana),
    }
    if not ventana:
        return {**base, "estado_cobertura": "sin_cobertura", "hidrograma_completo": False,
                "resultado_regla_candidata": "no_evaluable"}

    indice_pico = max(range(len(ventana)), key=lambda i: ventana[i][1])
    fecha_pico, pico = ventana[indice_pico]
    antes = [(f, v) for f, v in ventana if f <= fecha_pico - timedelta(hours=MIN_PRE_POST_H)]
    despues = [(f, v) for f, v in ventana if f >= fecha_pico + timedelta(hours=MIN_PRE_POST_H)]
    ascenso = pico - min((v for _, v in antes), default=pico)
    recesion = pico - min((v for _, v in despues), default=pico)
    max_gap = _max_gap_h(ventana)
    completo = (
        bool(antes)
        and bool(despues)
        and max_gap is not None
        and max_gap <= HUECO_MAX_H
        and ascenso >= CAMBIO_MIN_EVENTO_M
        and recesion >= CAMBIO_MIN_EVENTO_M
    )
    periodo = periodo_disparado(pico, umbrales)
    if not completo:
        resultado = "no_evaluable_hidrograma_incompleto"
    elif periodo:
        resultado = "coincide_superacion_de_umbral"
    else:
        resultado = "fallo_omision_de_regla_candidata"
    return {
        **base,
        "estado_cobertura": "con_cobertura",
        "hidrograma_completo": completo,
        "criterios_completitud": {
            "pre_pico_24h": bool(antes),
            "post_pico_24h": bool(despues),
            "hueco_maximo_h": round(max_gap, 2) if max_gap is not None else None,
            "hueco_admisible_h": HUECO_MAX_H,
            "ascenso_m": round(ascenso, 2),
            "recesion_m": round(recesion, 2),
            "cambio_minimo_m": CAMBIO_MIN_EVENTO_M,
        },
        "pico": {"fecha": _iso(fecha_pico), "nivel_m": round(pico, 3)},
        "periodo_candidato_superado": periodo or None,
        "resultado_regla_candidata": resultado,
    }


def _diagnostico_serie(
    serie_original: list[tuple[datetime, float]],
    serie_filtrada: list[tuple[datetime, float]],
    escalones: list[tuple[datetime, float]],
    descartados: list[tuple[datetime, datetime, int]],
) -> dict[str, Any]:
    fechas = [fecha for fecha, _ in serie_filtrada]
    dias = len({fecha.date() for fecha in fechas})
    return {
        "observaciones_entrada": len(serie_original),
        "observaciones_aceptadas": len(serie_filtrada),
        "inicio": _iso(min(fechas)) if fechas else None,
        "fin": _iso(max(fechas)) if fechas else None,
        "dias_con_datos": dias,
        "escalones_detectados": [
            {"fecha": _iso(fecha), "salto_m": round(salto, 2)}
            for fecha, salto in escalones
        ],
        "segmentos_descartados": [
            {"inicio": _iso(inicio), "fin": _iso(fin), "observaciones": cantidad}
            for inicio, fin, cantidad in descartados
        ],
        "limitacion": "el filtro detecta escalones persistentes; no detecta deriva lenta",
    }


def _descargar_si_falta(anio: int) -> Path:
    path = ROOT / "data" / "raw" / f"lecturas_anuales_nivel_{anio}.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"descargando serie {anio} desde CKAN")
        urllib.request.urlretrieve(CSV_CKAN[anio], path)
    return path


def construir_informe(anios: list[int], paths: dict[int, Path]) -> dict[str, Any]:
    activacion = json.loads((DATOS / "activacion.json").read_text(encoding="utf-8"))
    nombres = {
        EQUIV_ESTACION[cfg["estacion"]]
        for cfg in activacion.values()
        if cfg.get("estacion") in EQUIV_ESTACION
    }
    fuentes = []
    series_por_anio: dict[int, dict[str, list[tuple[datetime, float]]]] = {}
    diagnosticos: dict[str, dict[str, Any]] = defaultdict(dict)
    fechas_fuente: list[datetime] = []

    for anio in sorted(anios):
        path = paths[anio]
        fuentes.append({
            "anio": anio,
            "url": CSV_CKAN[anio],
            "archivo": path.name,
            "bytes": path.stat().st_size,
            "sha256": _hash(path),
            "licencia": "Licencia de Datos Abiertos de Uruguay (odc-uy)",
        })
        originales = cargar_series(path, nombres)
        filtradas: dict[str, list[tuple[datetime, float]]] = {}
        for nombre, serie in originales.items():
            escalones = detectar_escalones(serie)
            filtrada, descartados = segmentos_confiables(serie, escalones)
            filtradas[nombre] = filtrada
            diagnosticos[nombre][str(anio)] = _diagnostico_serie(
                serie, filtrada, escalones, descartados,
            )
            fechas_fuente.extend(fecha for fecha, _ in filtrada)
        series_por_anio[anio] = filtradas

    localidades: dict[str, Any] = {}
    resumen = {
        "localidades_candidatas": len(activacion),
        "localidades_con_estacion_superficial": sum(
            cfg.get("estacion_id") is not None for cfg in activacion.values()
        ),
        "localidades_con_curso_compatible": sum(
            cfg.get("curso_compatible") is True for cfg in activacion.values()
        ),
        "tipos_inundacion": dict(sorted(Counter(
            cfg.get("tipo_inundacion", "sin_clasificar")
            for cfg in activacion.values()
        ).items())),
        "bloqueos_candidatos": dict(sorted(Counter(
            bloqueo
            for cfg in activacion.values()
            for bloqueo in cfg.get("bloqueos", [])
        ).items())),
        "eventos_registrados": 0,
        "eventos_con_cobertura": 0,
        "hidrogramas_completos": 0,
        "coincidencias_umbral": 0,
        "fallos_omision": 0,
        "localidades_habilitables": 0,
    }
    particiones: dict[str, dict[str, Any]] = {}

    eventos_por_anio = {anio: eventos_cri(anio) for anio in anios}
    for codigo, cfg in sorted(activacion.items()):
        estacion_publicada = cfg.get("estacion")
        nombre_serie = EQUIV_ESTACION.get(estacion_publicada)
        cuenca = cfg.get("cuenca_nivel2") or {}
        codigo_cuenca = str(cuenca.get("codigo_nivel2", "sin_cuenca"))
        particion = particiones.setdefault(codigo_cuenca, {
            "cuenca_nivel2": cuenca or None,
            "localidades": [],
            "eventos": [],
        })
        particion["localidades"].append(codigo)
        eventos_localidad = []
        activacion_sin_evento = []
        cobertura_anual = []

        for anio in sorted(anios):
            serie = series_por_anio[anio].get(nombre_serie, []) if nombre_serie else []
            fechas_evento = sorted(eventos_por_anio[anio].get(codigo, set()))
            if nombre_serie is None:
                estado = "sin_mapeo_de_estacion"
            elif not serie:
                estado = "sin_serie"
            else:
                estado = "con_serie"
            cobertura_anual.append({
                "anio": anio,
                "estado": estado,
                "estacion_serie": nombre_serie,
                "dias_con_datos": len({fecha.date() for fecha, _ in serie}),
            })

            for evento in fechas_evento:
                evaluacion = analizar_evento(evento, serie, cfg.get("umbrales", []))
                evaluacion["anio"] = anio
                eventos_localidad.append(evaluacion)
                particion["eventos"].append({"localidad": codigo, **evaluacion})
                resumen["eventos_registrados"] += 1
                if evaluacion["estado_cobertura"] == "con_cobertura":
                    resumen["eventos_con_cobertura"] += 1
                if evaluacion["hidrograma_completo"]:
                    resumen["hidrogramas_completos"] += 1
                if evaluacion["resultado_regla_candidata"] == "coincide_superacion_de_umbral":
                    resumen["coincidencias_umbral"] += 1
                if evaluacion["resultado_regla_candidata"] == "fallo_omision_de_regla_candidata":
                    resumen["fallos_omision"] += 1

            if serie and cfg.get("umbrales"):
                diario = maximo_diario(serie)
                activos = [
                    dia for dia, nivel in diario.items()
                    if periodo_disparado(nivel, cfg["umbrales"])
                    and all(abs((dia - evento).days) > VENTANA_ANALISIS_DIAS for evento in fechas_evento)
                ]
                if activos:
                    activacion_sin_evento.append({
                        "anio": anio,
                        "dias": len(activos),
                        "dias_con_datos": len(diario),
                        "porcentaje": round(100 * len(activos) / len(diario), 2),
                        "interpretacion": "cota superior; CRI no registra exhaustivamente los días sin inundación",
                    })

        bloqueos = list(cfg.get("bloqueos", []))
        if not eventos_localidad:
            bloqueos.append("sin_eventos_cri_en_2017_2019")
        elif not any(evento["hidrograma_completo"] for evento in eventos_localidad):
            bloqueos.append("sin_evento_con_hidrograma_completo")
        # CRI no provee negativos exhaustivos: ninguna coincidencia retrospectiva
        # se convierte por sí sola en autorización operativa.
        bloqueos.append("sin_registro_exhaustivo_de_eventos_negativos")
        bloqueos = list(dict.fromkeys(bloqueos))
        estado_validacion = "insuficiente_para_habilitar" if bloqueos else "apta"
        if estado_validacion == "apta":
            resumen["localidades_habilitables"] += 1
        localidades[codigo] = {
            "tipo_inundacion": cfg.get("tipo_inundacion"),
            "regulada": cfg.get("regulada", False),
            "cadena_fisica_requerida": cfg.get("cadena_fisica_requerida"),
            "cuenca_nivel2": cfg.get("cuenca_nivel2"),
            "estacion_id": cfg.get("estacion_id"),
            "estacion": estacion_publicada,
            "estacion_tipo": cfg.get("estacion_tipo"),
            "dist_m": cfg.get("dist_m"),
            "curso_curvas": cfg.get("curso_curvas"),
            "curso_estacion": cfg.get("curso_estacion"),
            "curso_compatible": cfg.get("curso_compatible"),
            "datum_vertical": cfg.get("datum_vertical"),
            "umbrales": cfg.get("umbrales", []),
            "cobertura_anual": cobertura_anual,
            "eventos": eventos_localidad,
            "activaciones_sin_evento_registrado": activacion_sin_evento,
            "estado_validacion": estado_validacion,
            "bloqueos": bloqueos,
        }

    for particion in particiones.values():
        particion["localidades"].sort()
        particion["eventos"].sort(key=lambda item: (item["fecha_evento"], item["localidad"]))

    generado = max(fechas_fuente) if fechas_fuente else datetime(min(anios), 1, 1)
    return {
        "schema_version": 1,
        "generado_desde_datos": _iso(generado),
        "clasificacion": "estimado_retrospectivo_no_operativo",
        "decision_operativa": "ninguna_localidad_habilitada",
        "metodo": {
            "unidad_evaluacion": "evento completo dentro de localidad y cuenca",
            "particion": "por evento y cuenca; nunca se dividen aleatoriamente lecturas de un mismo evento",
            "tipos_separados": [
                "fluvial", "pluvial_urbana", "costera_estuarina", "mixta_no_separada"
            ],
            "ventana_analisis_dias_antes_y_despues": VENTANA_ANALISIS_DIAS,
            "criterio_hidrograma_completo": (
                "al menos 24 h antes y después del pico, huecos <=12 h, "
                "ascenso y recesión >=0,20 m"
            ),
            "correccion_datum": False,
            "zona_horaria_series": (
                "no publicada en los CSV; las horas se conservan sin zona y no se convierten"
            ),
            "limitaciones": [
                "La fecha CRI no delimita por sí sola el inicio y fin físico del evento.",
                "CRI no es un registro exhaustivo de eventos positivos ni negativos.",
                "Una coincidencia de umbral no valida datum ni causalidad hidráulica.",
                "Solo existen series públicas DINAGUA 2017-2019 para esta evaluación.",
            ],
        },
        "fuentes_series": fuentes,
        "resumen": resumen,
        "estaciones": dict(sorted(diagnosticos.items())),
        "particiones_por_cuenca": dict(sorted(particiones.items())),
        "localidades": localidades,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anios", nargs="+", type=int, default=sorted(CSV_CKAN), choices=sorted(CSV_CKAN))
    parser.add_argument("--salida", type=Path, default=SALIDA)
    args = parser.parse_args()
    anios = sorted(set(args.anios))
    paths = {anio: _descargar_si_falta(anio) for anio in anios}
    informe = construir_informe(anios, paths)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(
        json.dumps(informe, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    resumen = informe["resumen"]
    print(
        f"{resumen['eventos_registrados']} eventos: "
        f"{resumen['hidrogramas_completos']} hidrogramas completos, "
        f"{resumen['coincidencias_umbral']} coincidencias, "
        f"{resumen['fallos_omision']} fallos; "
        f"{resumen['localidades_habilitables']} localidades habilitables"
    )
    print(f"escrito: {args.salida.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
