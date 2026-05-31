"""Verifica la consistencia de datums entre curvas de inundación y estaciones.

Para cada localidad con manchas Tr: busca la estación más cercana (mismo
curso si es posible), y compara dos derivaciones del umbral de activación:
  a) cota_local de la curva            (lectura en la regla local)
  b) cota_oficial - cota_cero_estación (pasando por el datum oficial Wharton)
Si a ≈ b, los datums cierran y la activación automática es confiable en esa
localidad. Emite data/processed/activacion.json con los umbrales aprobados.
"""

import json
import logging
import unicodedata
from pathlib import Path

import geopandas as gpd

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CRS_METRICO = "EPSG:32721"
DIST_MAX_ESTACION_M = 12_000
TOLERANCIA_DATUM_M = 0.75


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    tr = gpd.read_file(ROOT / "web" / "public" / "data" / "inundacion_tr.geojson")
    est = gpd.read_file(ROOT / "data" / "processed" / "estaciones.geojson")
    tr_m = tr.to_crs(CRS_METRICO)
    est_m = est.to_crs(CRS_METRICO)

    resultado: dict[str, dict] = {}
    log.info("%-9s %-32s %6s | %-8s %10s %10s %8s", "loc", "estación", "dist",
             "curva", "cota_loc", "of-cero", "diff")

    for cod, grupo in tr_m.groupby("localidad_cod"):
        centro = grupo.geometry.centroid.union_all().centroid
        est_m["d"] = est_m.geometry.distance(centro)
        cand = est_m[est_m["d"] < DIST_MAX_ESTACION_M].sort_values("d")
        if cand.empty:
            continue
        curso_curvas = norm(str(grupo["curso"].mode().iat[0]) if grupo["curso"].notna().any() else "")
        mismo_curso = cand[[norm(c) == curso_curvas for c in cand["curso"].fillna("")]]
        estacion = (mismo_curso if not mismo_curso.empty else cand).iloc[0]
        cero = estacion["cota_cero"]

        umbrales = []
        for _, c in grupo.sort_values("periodo").iterrows():
            local = c["cota_local"]
            oficial = c["cota_oficial"]
            derivado = (oficial - cero) if (oficial is not None and cero is not None) else None
            diff = (derivado - local) if (derivado is not None and local is not None) else None
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
                umbrales.append({"periodo": int(c["periodo"]),
                                 "nivel": round(float(derivado), 2),
                                 "tipo_curva": c["tipo_curva"]})

        if umbrales:
            # varias manchas del mismo período: activa la de umbral más bajo
            por_periodo: dict[int, dict] = {}
            for u in umbrales:
                previo = por_periodo.get(u["periodo"])
                if previo is None or u["nivel"] < previo["nivel"]:
                    por_periodo[u["periodo"]] = u
            resultado[cod] = {
                "estacion_id": int(estacion["id"]),
                "estacion": estacion["nombre"],
                "dist_m": round(float(estacion["d"])),
                "umbrales": sorted(por_periodo.values(), key=lambda u: u["periodo"]),
            }

    out = ROOT / "web" / "public" / "data" / "activacion.json"
    out.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("")
    log.info("localidades con umbrales utilizables: %d -> %s", len(resultado), out)


if __name__ == "__main__":
    main()
