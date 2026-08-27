import unittest
from datetime import datetime, timedelta, timezone

from pipeline.build_estado import (
    construir_fuentes_detalle,
    dato_fresco,
    evaluar_activacion,
    horas_desde,
    parsear_fecha_salto,
)


class SeguridadTemporalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ahora = datetime(2026, 8, 21, 22, 0, tzinfo=timezone.utc)

    def test_salto_grande_usa_hora_local_con_offset(self) -> None:
        fecha = parsear_fecha_salto("21/08/2026 18:30")
        self.assertIsNotNone(fecha)
        self.assertEqual(fecha.isoformat(timespec="minutes"), "2026-08-21T18:30-03:00")
        self.assertAlmostEqual(horas_desde(fecha.isoformat(), self.ahora), 0.5)

    def test_frescura_es_fail_closed(self) -> None:
        self.assertTrue(dato_fresco(48, 48))
        self.assertFalse(dato_fresco(48.1, 48))
        self.assertFalse(dato_fresco(None, 48))
        self.assertFalse(dato_fresco(-2, 48))

    def test_fuente_accesible_pero_vencida_no_es_apta(self) -> None:
        detalle = construir_fuentes_detalle(
            {"dinagua_wfs": True},
            {"dinagua_wfs": (self.ahora - timedelta(hours=60)).isoformat()},
            self.ahora,
        )
        self.assertEqual(detalle["dinagua_wfs"]["estado"], "vencida")


class CompuertaActivacionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.estacion = {
            "id": 7,
            "nivel": 4.2,
            "nivel_horas": 2.0,
            "qc_nivel": {"apto_derivados": True},
        }
        self.umbral = {
            "periodo": 10,
            "nivel": 4.0,
            "tipo_curva": "10 años",
            "datum_ok": True,
        }

    def test_configuracion_legacy_no_habilita_automaticamente(self) -> None:
        config = {
            "LOC": {
                "estacion_id": 7,
                "estacion": "Estación",
                "umbrales": [self.umbral],
            }
        }
        activacion, cobertura = evaluar_activacion(config, [self.estacion])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura, {
            "configuradas": 1,
            "habilitadas": 0,
            "evaluadas": 0,
            "rechazadas_qc": 0,
            "con_estacion_superficial": 1,
            "con_curso_compatible": 0,
            "tipos_inundacion": {"sin_clasificar": 1},
            "bloqueos": {},
        })

    def test_requiere_habilitacion_y_datum_aprobado(self) -> None:
        config = {
            "LOC": {
                "estacion_id": 7,
                "estacion": "Estación",
                "auto_habilitada": True,
                "umbrales": [self.umbral],
            }
        }
        activacion, cobertura = evaluar_activacion(config, [self.estacion])
        self.assertEqual(activacion["LOC"]["periodo_activo"], 10)
        self.assertEqual(cobertura["evaluadas"], 1)

        config["LOC"]["umbrales"][0]["datum_ok"] = False
        activacion, cobertura = evaluar_activacion(config, [self.estacion])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura["evaluadas"], 0)

    def test_nivel_vencido_no_se_evalua(self) -> None:
        config = {
            "LOC": {
                "estacion_id": 7,
                "estacion": "Estación",
                "auto_habilitada": True,
                "umbrales": [self.umbral],
            }
        }
        vieja = {**self.estacion, "nivel_horas": 24.1}
        activacion, cobertura = evaluar_activacion(config, [vieja])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura["evaluadas"], 0)

    def test_nivel_rechazado_por_qc_no_se_evalua(self) -> None:
        config = {
            "LOC": {
                "estacion_id": 7,
                "estacion": "Estación",
                "auto_habilitada": True,
                "umbrales": [self.umbral],
            }
        }
        rechazada = {**self.estacion, "qc_nivel": {"apto_derivados": False}}
        activacion, cobertura = evaluar_activacion(config, [rechazada])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura["rechazadas_qc"], 1)

    def test_configuracion_incompleta_y_nivel_invalido_fallan_cerrado(self) -> None:
        config = {"LOC": {"auto_habilitada": True}}
        activacion, cobertura = evaluar_activacion(config, [self.estacion])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura["evaluadas"], 0)

        config["LOC"] = {
            "estacion_id": 7,
            "estacion": "Estación",
            "auto_habilitada": True,
            "umbrales": [self.umbral],
        }
        invalida = {**self.estacion, "nivel": float("nan")}
        activacion, cobertura = evaluar_activacion(config, [invalida])
        self.assertEqual(activacion, {})
        self.assertEqual(cobertura["evaluadas"], 0)


if __name__ == "__main__":
    unittest.main()
