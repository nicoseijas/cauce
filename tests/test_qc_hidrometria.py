import unittest
from datetime import datetime, timedelta, timezone

from pipeline.qc_hidrometria import (
    construir_resumen,
    contexto_nivel,
    evaluar_medicion,
    extraer_referencia,
)


class ControlCalidadHidrometricaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ahora = datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc)

    def fecha(self, horas: float) -> str:
        return (self.ahora - timedelta(hours=horas)).isoformat()

    def test_observacion_valida_es_apta_para_derivados(self) -> None:
        qc = evaluar_medicion("nivel", 4.2, self.fecha(2), self.ahora)
        self.assertEqual(qc["estado"], "ok")
        self.assertTrue(qc["apto_derivados"])
        self.assertEqual(qc["referencia"]["valor"], 4.2)

    def test_fecha_futura_se_rechaza(self) -> None:
        qc = evaluar_medicion("nivel", 1.0, self.fecha(-10), self.ahora)
        self.assertEqual(qc["estado"], "rechazado")
        self.assertEqual(qc["codigos"], ["fecha_futura"])
        self.assertFalse(qc["apto_informativo"])

    def test_valor_vencido_se_conserva_solo_como_historia(self) -> None:
        qc = evaluar_medicion("caudal", 12.0, self.fecha(49), self.ahora)
        self.assertEqual(qc["estado"], "vencido")
        self.assertTrue(qc["apto_informativo"])
        self.assertFalse(qc["apto_derivados"])

    def test_rango_fluvial_no_se_aplica_a_una_presa(self) -> None:
        fluvial = evaluar_medicion("nivel", 35.0, self.fecha(1), self.ahora)
        embalse = evaluar_medicion(
            "nivel", 35.0, self.fecha(1), self.ahora, contexto="embalse"
        )
        self.assertEqual(fluvial["estado"], "rechazado")
        self.assertEqual(embalse["estado"], "ok")
        self.assertEqual(
            contexto_nivel("Presa Paso Severino", "Limnimétrica", "Río"),
            "embalse",
        )

    def test_cambio_brusco_es_dudoso_y_no_mueve_la_referencia(self) -> None:
        referencia = {"valor": 2.0, "fecha": self.fecha(1)}
        qc = evaluar_medicion(
            "nivel", 5.0, self.fecha(0), self.ahora, referencia=referencia
        )
        self.assertEqual(qc["estado"], "dudoso")
        self.assertEqual(qc["codigos"], ["cambio_brusco_no_verificado"])
        self.assertFalse(qc["apto_derivados"])
        self.assertEqual(qc["referencia"], referencia)

    def test_referencia_legacy_con_fecha_futura_no_se_hereda(self) -> None:
        anterior = {
            "nivel": 1.0,
            "nivel_fecha": self.fecha(-240),
        }
        self.assertIsNone(extraer_referencia(anterior, "nivel", self.ahora))

    def test_resumen_publica_incidencia_y_metodo(self) -> None:
        estacion = {
            "id": 1,
            "nombre": "Estación",
            "fuente": "DINAGUA",
            "nivel": 500.0,
            "nivel_fecha": self.fecha(1),
            "caudal": None,
            "caudal_fecha": None,
            "qc_nivel": evaluar_medicion("nivel", 500.0, self.fecha(1), self.ahora),
            "qc_caudal": evaluar_medicion("caudal", None, None, self.ahora),
        }
        resumen = construir_resumen([estacion])
        self.assertFalse(resumen["metodo"]["corrige_valores"])
        self.assertEqual(resumen["resumen"]["nivel"]["rechazado"], 1)
        self.assertEqual(resumen["incidencias"][0]["valor"], 500.0)


if __name__ == "__main__":
    unittest.main()
