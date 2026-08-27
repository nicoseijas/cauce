import json
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline.build_validacion_activacion import analizar_evento

ROOT = Path(__file__).resolve().parents[1]


class ValidacionPorEventoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fecha = date(2019, 6, 18)
        self.centro = datetime(2019, 6, 18, 12)
        self.umbrales = [{"periodo": 10, "nivel": 4.0}]

    def _hidrograma(self):
        serie = []
        for horas in range(-72, 73, 6):
            valor = 5.0 - abs(horas) / 36
            serie.append((self.centro + timedelta(hours=horas), valor))
        return serie

    def test_evalua_el_evento_completo_sin_partir_observaciones(self):
        resultado = analizar_evento(self.fecha, self._hidrograma(), self.umbrales)
        self.assertTrue(resultado["hidrograma_completo"])
        self.assertEqual(
            resultado["resultado_regla_candidata"],
            "coincide_superacion_de_umbral",
        )

    def test_sin_recesion_suficiente_no_emite_acierto_ni_fallo(self):
        serie = [p for p in self._hidrograma() if p[0] <= self.centro + timedelta(hours=12)]
        resultado = analizar_evento(self.fecha, serie, self.umbrales)
        self.assertFalse(resultado["hidrograma_completo"])
        self.assertEqual(
            resultado["resultado_regla_candidata"],
            "no_evaluable_hidrograma_incompleto",
        )

    def test_sin_cobertura_es_no_evaluable(self):
        resultado = analizar_evento(self.fecha, [], self.umbrales)
        self.assertEqual(resultado["estado_cobertura"], "sin_cobertura")
        self.assertEqual(resultado["resultado_regla_candidata"], "no_evaluable")


class InformePublicadoTest(unittest.TestCase):
    def test_eventos_se_conservan_enteros_en_una_unica_particion_de_cuenca(self):
        informe = json.loads(
            (ROOT / "web/public/data/validacion_activacion.json").read_text(encoding="utf-8")
        )
        por_localidad = Counter(
            (codigo, evento["fecha_evento"])
            for codigo, localidad in informe["localidades"].items()
            for evento in localidad["eventos"]
        )
        por_cuenca = Counter(
            (evento["localidad"], evento["fecha_evento"])
            for particion in informe["particiones_por_cuenca"].values()
            for evento in particion["eventos"]
        )
        self.assertEqual(por_localidad, por_cuenca)
        self.assertTrue(all(cantidad == 1 for cantidad in por_cuenca.values()))
        self.assertNotIn("sin_cuenca", informe["particiones_por_cuenca"])

    def test_dictamen_no_confunde_coincidencias_con_habilitacion(self):
        informe = json.loads(
            (ROOT / "web/public/data/validacion_activacion.json").read_text(encoding="utf-8")
        )
        self.assertEqual(informe["resumen"]["coincidencias_umbral"], 4)
        self.assertEqual(informe["resumen"]["localidades_habilitables"], 0)
        self.assertEqual(informe["decision_operativa"], "ninguna_localidad_habilitada")


if __name__ == "__main__":
    unittest.main()
