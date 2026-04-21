"""Descarga las capas DINAGUA necesarias para el proyecto a data/raw/.

Uso:
    python pipeline/descargar_capas.py [capa ...]
Sin argumentos descarga todas.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import wfs

RAW = Path(__file__).parent.parent / "data" / "raw"

CAPAS = {
    "catalogo_estaciones": "dinagua:V_Catalogo_publica",
    "cursos": "dinagua:shp_cursos",
    "curvas_tr": "dinagua:curvas_tr",
    "curvas_cri": "dinagua:curvas_cri",
    "localidades_amenazas": "dinagua:localidades_amenazas",
    "problemas_drenaje": "dinagua:problemas_drenaje",
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    seleccion = sys.argv[1:] or list(CAPAS)
    for nombre in seleccion:
        type_name = CAPAS[nombre]
        destino = RAW / f"{nombre}.geojson"
        logging.info("--- %s (%s) ---", nombre, type_name)
        features, skipped = wfs.fetch_layer(type_name)
        if not features:
            logging.error("sin datos para %s", nombre)
            continue
        wfs.save_geojson(features, destino)
        if skipped:
            (RAW / f"{nombre}_skipped_ids.json").write_text(str(skipped))


if __name__ == "__main__":
    main()
