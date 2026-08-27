import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from identidad import (  # noqa: E402
    IdentidadError,
    asignar_identidad,
    identidad_canonica,
    indice_alias,
    slugificar,
)


class TestSlugificar(unittest.TestCase):
    def test_quita_diacriticos_y_puntuacion(self):
        self.assertEqual(slugificar("Mercedes (Puerto)"), "mercedes-puerto")
        self.assertEqual(slugificar("Quaraí — río Cuareim"), "quarai-rio-cuareim")
        self.assertEqual(slugificar("Treinta y Tres (R.8)"), "treinta-y-tres-r-8")

    def test_no_deja_guiones_en_los_bordes_ni_repetidos(self):
        self.assertEqual(slugificar("  ¿Paso — de los Toros?  "), "paso-de-los-toros")

    def test_nombre_sin_caracteres_utiles_queda_vacio(self):
        self.assertEqual(slugificar("—"), "")


class TestIdentidadCanonica(unittest.TestCase):
    def test_entero_es_dinagua(self):
        self.assertEqual(identidad_canonica(189), ("dinagua", "189"))

    def test_ids_externos_conservan_su_organismo(self):
        self.assertEqual(identidad_canonica("ina-78"), ("ina", "78"))
        self.assertEqual(identidad_canonica("sohma-puntalobos"), ("sohma", "puntalobos"))

    def test_centinelas_negativos_declarados(self):
        self.assertEqual(identidad_canonica(-1), ("ctm", "salto-grande"))
        self.assertEqual(identidad_canonica(-2), ("ute", "palmar-previsto"))

    def test_id_negativo_no_declarado_falla(self):
        with self.assertRaises(IdentidadError):
            identidad_canonica(-3)

    def test_id_ausente_o_vacio_falla(self):
        for valor in (None, "", "sinorganismo"):
            with self.assertRaises(IdentidadError):
                identidad_canonica(valor)


class TestAsignarIdentidad(unittest.TestCase):
    def test_asigna_canonico_y_slug(self):
        estaciones = [{"id": 189, "nombre": "Paso de los Toros"}]
        asignar_identidad(estaciones)
        self.assertEqual(estaciones[0]["estacion_id"], "dinagua-189")
        self.assertEqual(estaciones[0]["slug"], "paso-de-los-toros")

    def test_colision_de_nombre_se_resuelve_por_prioridad_de_organismo(self):
        estaciones = [
            {"id": "ina-1699", "nombre": "Nueva Palmira"},
            {"id": 230, "nombre": "Nueva Palmira"},
        ]
        asignar_identidad(estaciones)
        por_id = {e["estacion_id"]: e["slug"] for e in estaciones}
        self.assertEqual(por_id["dinagua-230"], "nueva-palmira")
        self.assertEqual(por_id["ina-1699"], "nueva-palmira-ina")

    def test_el_orden_de_entrada_no_altera_el_resultado(self):
        crear = lambda: [
            {"id": 173, "nombre": "La Paloma"},
            {"id": "sohma-lapaloma", "nombre": "La Paloma"},
        ]
        directo, invertido = crear(), list(reversed(crear()))
        asignar_identidad(directo)
        asignar_identidad(invertido)
        self.assertEqual(
            {e["estacion_id"]: e["slug"] for e in directo},
            {e["estacion_id"]: e["slug"] for e in invertido},
        )

    def test_agregar_una_estacion_no_reasigna_los_slugs_previos(self):
        previas = [{"id": 230, "nombre": "Nueva Palmira"}]
        asignar_identidad(previas)
        antes = previas[0]["slug"]

        ampliadas = [
            {"id": 230, "nombre": "Nueva Palmira"},
            {"id": "ina-1699", "nombre": "Nueva Palmira"},
        ]
        asignar_identidad(ampliadas)
        self.assertEqual(ampliadas[0]["slug"], antes)

    def test_nombre_vacio_cae_al_identificador_canonico(self):
        estaciones = [{"id": 500, "nombre": "—"}]
        asignar_identidad(estaciones)
        self.assertEqual(estaciones[0]["slug"], "dinagua-500")

    def test_identificadores_canonicos_repetidos_fallan(self):
        estaciones = [
            {"id": 189, "nombre": "Una"},
            {"id": "dinagua-189", "nombre": "Otra"},
        ]
        with self.assertRaises(IdentidadError):
            asignar_identidad(estaciones)

    def test_indice_alias_mapea_canonico_a_slug(self):
        estaciones = [{"id": 189, "nombre": "Paso de los Toros"}]
        asignar_identidad(estaciones)
        self.assertEqual(indice_alias(estaciones), {"dinagua-189": "paso-de-los-toros"})


class TestEstadoPublicado(unittest.TestCase):
    """Contrato sobre los datos realmente publicados."""

    @classmethod
    def setUpClass(cls):
        ruta = ROOT / "web" / "public" / "data" / "estado_actual.json"
        cls.estado = json.loads(ruta.read_text(encoding="utf-8"))
        cls.estaciones = list(cls.estado["estaciones"])
        for clave in ("ina", "ana", "sohma"):
            cls.estaciones.extend((cls.estado.get(clave) or {}).get("estaciones", []))

    def test_toda_estacion_publica_identificador_y_slug(self):
        sin_identidad = [
            e.get("nombre") for e in self.estaciones
            if not e.get("estacion_id") or not e.get("slug")
        ]
        self.assertEqual(sin_identidad, [])

    def test_los_identificadores_y_slugs_son_unicos(self):
        for campo in ("estacion_id", "slug"):
            valores = [e[campo] for e in self.estaciones]
            self.assertEqual(len(valores), len(set(valores)), f"{campo} repetido")

    def test_los_slugs_son_seguros_en_una_url(self):
        import re
        for e in self.estaciones:
            self.assertRegex(e["slug"], r"^[a-z0-9]+(-[a-z0-9]+)*$", e["nombre"])


if __name__ == "__main__":
    unittest.main()
