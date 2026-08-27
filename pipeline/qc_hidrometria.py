"""Control de calidad operativo para observaciones hidrométricas.

El módulo no corrige, interpola ni cambia el datum de ninguna lectura. Marca
la aptitud de cada valor para usos derivados y conserva valor, fecha y motivo
de rechazo en el estado publicado. La continuidad se contrasta contra la
última referencia aceptada, no contra una lectura previamente rechazada.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from typing import Any

QC_VERSION = "1.0.0"
TOLERANCIA_FUTURO_H = 1.0
VIGENCIA_DERIVADOS_H = 48.0

# Rango usado en la validación histórica para reglas/limnímetros fluviales.
# Presas, piezómetros y otras infraestructuras usan un rango amplio distinto.
RANGO_NIVEL_FLUVIAL_M = (-2.0, 30.0)
RANGO_NIVEL_OTRO_M = (-50.0, 200.0)
RANGO_CAUDAL_M3_S = (0.0, 250_000.0)

# La validación retrospectiva detectó escalones persistentes a partir de 1 m
# entre lecturas separadas por hasta 2 h. En vivo todavía no se conoce la
# persistencia futura: se marca "dudoso" y no se inventa una corrección.
SALTO_NIVEL_MIN_M = 1.0
VENTANA_CONTINUIDAD_H = 2.0
CAMBIO_MISMA_FECHA_TOL = 0.01

# Antecedentes documentados; son una advertencia, no un rechazo permanente.
VIGILANCIA_REFORZADA = {
    47: "dos cambios de marco de referencia detectados en 2018-2019",
    164: "escalones históricos de hasta aproximadamente 12 m",
    14752: "84 lecturas históricas entre 370 y 590 m",
}


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    numero = float(valor)
    return numero if isfinite(numero) else None


def _fecha(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha


def contexto_nivel(nombre: str | None, tipo: str | None, curso: str | None) -> str:
    """Separa reglas fluviales de embalses, piezómetros e infraestructura."""
    texto = " ".join((nombre or "", tipo or "", curso or "")).casefold()
    if "piezom" in texto or "acuífer" in texto or "acuifer" in texto:
        return "subterraneo"
    if "presa" in texto or "embalse" in texto:
        return "embalse"
    return "fluvial"


def extraer_referencia(
    anterior: dict | None,
    variable: str,
    ahora: datetime,
) -> dict | None:
    """Obtiene la última referencia aceptada, con compatibilidad pre-QC."""
    if not anterior:
        return None
    qc = anterior.get(f"qc_{variable}") or {}
    candidata = qc.get("referencia")
    if not candidata:
        sufijo_fecha = "nivel_fecha" if variable == "nivel" else "caudal_fecha"
        candidata = {
            "valor": anterior.get(variable),
            "fecha": anterior.get(sufijo_fecha),
        }
    valor = _numero(candidata.get("valor"))
    fecha = _fecha(candidata.get("fecha"))
    if valor is None or fecha is None:
        return None
    # Una fecha ya imposible no puede contaminar la referencia de corridas
    # posteriores (por ejemplo, una lectura futura heredada de un estado v2).
    if (fecha - ahora).total_seconds() / 3600 > TOLERANCIA_FUTURO_H:
        return None
    return {"valor": valor, "fecha": fecha.isoformat(timespec="minutes")}


def evaluar_medicion(
    variable: str,
    valor: Any,
    fecha_iso: str | None,
    ahora: datetime,
    *,
    referencia: dict | None = None,
    contexto: str = "fluvial",
    continuidad: bool = True,
    vigencia_h: float = VIGENCIA_DERIVADOS_H,
) -> dict:
    """Evalúa una medición sin alterarla y declara para qué usos es apta."""
    resultado = {
        "estado": "sin_dato",
        "codigos": [],
        "apto_informativo": False,
        "apto_derivados": False,
        "antiguedad_h": None,
        "controles": ["valor_finito", "fecha", "rango_fisico"],
        "referencia": referencia,
    }
    numero = _numero(valor)
    if valor is None:
        resultado["codigos"] = ["sin_dato"]
        return resultado
    if numero is None:
        resultado.update(estado="rechazado", codigos=["valor_no_finito"])
        return resultado

    fecha = _fecha(fecha_iso)
    if fecha is None:
        codigo = "fecha_ausente" if not fecha_iso else "fecha_invalida"
        resultado.update(estado="rechazado", codigos=[codigo])
        return resultado
    edad_h = (ahora - fecha).total_seconds() / 3600
    resultado["antiguedad_h"] = round(edad_h, 2)
    if edad_h < -TOLERANCIA_FUTURO_H:
        resultado.update(estado="rechazado", codigos=["fecha_futura"])
        return resultado

    if variable == "caudal":
        minimo, maximo = RANGO_CAUDAL_M3_S
    elif contexto == "fluvial":
        minimo, maximo = RANGO_NIVEL_FLUVIAL_M
    else:
        minimo, maximo = RANGO_NIVEL_OTRO_M
    resultado["rango_aplicado"] = {"min": minimo, "max": maximo}
    if not minimo <= numero <= maximo:
        resultado.update(estado="rechazado", codigos=["fuera_rango_fisico"])
        return resultado

    if continuidad and variable == "nivel" and referencia:
        resultado["controles"].append("continuidad_temporal")
        ref_valor = _numero(referencia.get("valor"))
        ref_fecha = _fecha(referencia.get("fecha"))
        if ref_valor is not None and ref_fecha is not None:
            intervalo_h = (fecha - ref_fecha).total_seconds() / 3600
            delta_m = numero - ref_valor
            resultado["continuidad"] = {
                "intervalo_h": round(intervalo_h, 2),
                "delta_m": round(delta_m, 3),
            }
            if intervalo_h < 0:
                resultado.update(estado="rechazado", codigos=["fecha_retrocede"])
                return resultado
            if intervalo_h == 0 and abs(delta_m) > CAMBIO_MISMA_FECHA_TOL:
                resultado.update(
                    estado="dudoso",
                    codigos=["revision_misma_fecha"],
                    apto_informativo=True,
                )
                return resultado
            if (
                0 < intervalo_h <= VENTANA_CONTINUIDAD_H
                and abs(delta_m) > SALTO_NIVEL_MIN_M
            ):
                resultado.update(
                    estado="dudoso",
                    codigos=["cambio_brusco_no_verificado"],
                    apto_informativo=True,
                )
                return resultado

    # Una observación físicamente válida pero vieja se conserva como historia,
    # aunque nunca se usa para un resultado que describa el estado actual.
    resultado["referencia"] = {
        "valor": numero,
        "fecha": fecha.isoformat(timespec="minutes"),
    }
    resultado["apto_informativo"] = True
    if edad_h > vigencia_h:
        resultado.update(estado="vencido", codigos=["dato_vencido"])
    else:
        resultado.update(estado="ok", apto_derivados=True)
    return resultado


def agregar_vigilancia(estacion: dict) -> None:
    nota = VIGILANCIA_REFORZADA.get(estacion.get("id"))
    if not nota:
        return
    for variable in ("nivel", "caudal"):
        qc = estacion.get(f"qc_{variable}")
        if qc:
            qc["vigilancia"] = nota


def construir_resumen(estaciones: list[dict]) -> dict:
    """Construye un resumen auditable y una lista corta de incidencias."""
    conteos = {"nivel": Counter(), "caudal": Counter()}
    incidencias = []
    vigiladas = []
    for estacion in estaciones:
        if estacion.get("id") in VIGILANCIA_REFORZADA:
            vigiladas.append({
                "id": estacion.get("id"),
                "estacion": estacion.get("nombre"),
                "motivo": VIGILANCIA_REFORZADA[estacion["id"]],
            })
        for variable in ("nivel", "caudal"):
            qc = estacion.get(f"qc_{variable}")
            if not qc:
                continue
            estado = qc.get("estado", "sin_dato")
            conteos[variable][estado] += 1
            if estado not in ("rechazado", "dudoso"):
                continue
            campo_fecha = "nivel_fecha" if variable == "nivel" else "caudal_fecha"
            incidencias.append({
                "id": estacion.get("id"),
                "estacion": estacion.get("nombre"),
                "fuente": estacion.get("fuente"),
                "variable": variable,
                "estado": estado,
                "codigos": qc.get("codigos", []),
                "valor": estacion.get(variable),
                "fecha": estacion.get(campo_fecha),
            })
    return {
        "version": QC_VERSION,
        "metodo": {
            "corrige_valores": False,
            "rango_nivel_fluvial_m": list(RANGO_NIVEL_FLUVIAL_M),
            "rango_nivel_otro_m": list(RANGO_NIVEL_OTRO_M),
            "rango_caudal_m3_s": list(RANGO_CAUDAL_M3_S),
            "salto_nivel_dudoso_m": SALTO_NIVEL_MIN_M,
            "ventana_continuidad_h": VENTANA_CONTINUIDAD_H,
            "vigencia_derivados_h": VIGENCIA_DERIVADOS_H,
            "limitacion": (
                "control operativo; no detecta deriva lenta ni valida cambios "
                "separados por más de 2 h, y no sustituye calibración, curva de "
                "gasto ni validación del datum vertical"
            ),
        },
        "resumen": {k: dict(v) for k, v in conteos.items()},
        "incidencias": incidencias,
        "vigilancia_reforzada": vigiladas,
    }
