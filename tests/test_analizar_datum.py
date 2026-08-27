import unittest

from pipeline.analizar_datum import (
    bloqueos_candidato,
    cursos_compatibles,
    diagnosticar_separacion,
    estacion_superficial,
    normalizar_crs_cuencas,
    tipo_inundacion,
)


class _CapaFalsa:
    def __init__(self, bounds, crs="EPSG:4326"):
        self.total_bounds = bounds
        self.crs = crs
        self.operacion = None

    def set_crs(self, crs, allow_override=False):
        self.operacion = ("set_crs", crs, allow_override)
        self.crs = crs
        return self

    def to_crs(self, crs):
        self.operacion = ("to_crs", crs)
        self.crs = crs
        return self


class ClasificacionHidraulicaTest(unittest.TestCase):
    def test_excluye_piezometros_y_acepta_estaciones_superficiales(self):
        self.assertFalse(estacion_superficial("Piezométrica — Acuífero Guaraní"))
        self.assertTrue(estacion_superficial("Hidrométrica + T"))
        self.assertTrue(estacion_superficial("Limnimétrica"))

    def test_compatibilidad_de_curso_no_depende_de_acentos(self):
        self.assertTrue(cursos_compatibles("Río Santa Lucía", "Rio Santa Lucia"))
        self.assertTrue(cursos_compatibles("Ao. de las Vacas", "Arroyo Las Vacas"))
        self.assertFalse(cursos_compatibles("Río Negro", "Río Uruguay"))

    def test_separa_mecanismos(self):
        self.assertEqual(tipo_inundacion("SA-STO")[0], "pluvial_urbana")
        self.assertEqual(tipo_inundacion("CO-CLO")[0], "costera_estuarina")
        self.assertEqual(tipo_inundacion("CO-JLL")[0], "mixta_no_separada")
        self.assertEqual(tipo_inundacion("CA-SLA")[0], "fluvial")

    def test_umbrales_solapados_no_son_distinguibles(self):
        _, distinguibles = diagnosticar_separacion([
            {"periodo": 10, "nivel": 4.0},
            {"periodo": 100, "nivel": 4.5},
        ])
        self.assertFalse(distinguibles)
        _, distinguibles = diagnosticar_separacion([
            {"periodo": 10, "nivel": 4.0},
            {"periodo": 100, "nivel": 6.0},
        ])
        self.assertTrue(distinguibles)

    def test_caso_pluvial_queda_bloqueado_sin_sensor_superficial(self):
        bloqueos = bloqueos_candidato(
            codigo="SA-STO",
            tipo="pluvial_urbana",
            estacion=None,
            curso_compatible=False,
            umbrales=[],
            distinguibles=False,
        )
        self.assertIn("sin_estacion_superficial_compatible", bloqueos)
        self.assertIn("requiere_modelo_pluvial_urbano", bloqueos)

    def test_corrige_crs_wfs_solo_si_la_magnitud_es_utm(self):
        capa = _CapaFalsa([312_000, 6_055_000, 1_261_000, 7_125_000])
        _, metadatos = normalizar_crs_cuencas(capa)
        self.assertEqual(capa.operacion, ("set_crs", "EPSG:32721", True))
        self.assertEqual(
            metadatos["accion"],
            "crs_declarado_incorrecto_corregido_por_magnitud",
        )

    def test_crs_ambiguo_falla_cerrado(self):
        with self.assertRaisesRegex(ValueError, "CRS de cuencas ambiguo"):
            normalizar_crs_cuencas(_CapaFalsa([1000, 2000, 3000, 4000]))


if __name__ == "__main__":
    unittest.main()
