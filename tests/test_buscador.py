import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from build_buscador import (  # noqa: E402
    entidades_cursos,
    entidades_localidades,
    envolvente,
    titular,
)

TIPOS = {"estacion", "curso", "localidad", "departamento", "represa"}


class TestTitular(unittest.TestCase):
    def test_recompone_mayusculas_dejando_particulas_en_minuscula(self):
        self.assertEqual(titular("BELLA UNION"), "Bella Union")
        self.assertEqual(titular("SAN JOSE DE MAYO"), "San Jose de Mayo")
        self.assertEqual(titular("LAS PIEDRAS"), "Las Piedras")

    def test_la_particula_inicial_conserva_la_mayuscula(self):
        self.assertEqual(titular("LOS CERRILLOS"), "Los Cerrillos")

    def test_no_altera_un_nombre_ya_bien_escrito(self):
        # Reescribirlo perdería los diacríticos que la fuente sí trae.
        self.assertEqual(titular("Paysandú"), "Paysandú")
        self.assertEqual(titular("Rincón del Bonete"), "Rincón del Bonete")


class TestEnvolvente(unittest.TestCase):
    def test_linea(self):
        geom = {"type": "LineString", "coordinates": [[-58.0, -34.0], [-56.0, -32.0]]}
        self.assertEqual(envolvente(geom), [-58.0, -34.0, -56.0, -32.0])

    def test_geometria_anidada(self):
        geom = {
            "type": "MultiPolygon",
            "coordinates": [[[[-58.0, -34.0], [-57.0, -33.0], [-58.0, -34.0]]]],
        }
        self.assertEqual(envolvente(geom), [-58.0, -34.0, -57.0, -33.0])

    def test_geometria_vacia(self):
        self.assertIsNone(envolvente({"type": "LineString", "coordinates": []}))


class TestCursos(unittest.TestCase):
    def test_une_los_tramos_de_un_mismo_curso_en_una_envolvente(self):
        red = {"features": [
            {"properties": {"nombre": "Río X"},
             "geometry": {"type": "LineString", "coordinates": [[-58.0, -34.0], [-57.0, -33.0]]}},
            {"properties": {"nombre": "Río X"},
             "geometry": {"type": "LineString", "coordinates": [[-56.0, -32.0], [-55.0, -31.0]]}},
        ]}
        cursos = entidades_cursos(red)
        self.assertEqual(len(cursos), 1)
        self.assertEqual(cursos[0]["bbox"], [-58.0, -34.0, -55.0, -31.0])

    def test_descarta_tramos_sin_nombre(self):
        red = {"features": [
            {"properties": {}, "geometry": {"type": "LineString", "coordinates": [[-58.0, -34.0]]}},
        ]}
        self.assertEqual(entidades_cursos(red), [])


class TestLocalidades(unittest.TestCase):
    def _amenaza(self, localidad, departamento="ARTIGAS"):
        return {"properties": {"localidad": localidad, "departamento": departamento},
                "geometry": {"type": "Point", "coordinates": [-56.0, -33.0]}}

    def _capital(self, nombre):
        return {"properties": {"nombre": nombre},
                "geometry": {"type": "Point", "coordinates": [-56.0, -33.0]}}

    def test_una_capital_ya_presente_no_se_duplica_y_aporta_sus_tildes(self):
        salida = entidades_localidades(
            {"features": [self._amenaza("PAYSANDU")]},
            {"features": [self._capital("Paysandú")]},
        )
        self.assertEqual([e["nombre"] for e in salida], ["Paysandú"])

    def test_una_capital_ausente_se_agrega(self):
        salida = entidades_localidades(
            {"features": [self._amenaza("BELLA UNION")]},
            {"features": [self._capital("Trinidad")]},
        )
        self.assertEqual(sorted(e["nombre"] for e in salida), ["Bella Union", "Trinidad"])


class TestIndicePublicado(unittest.TestCase):
    """Contrato sobre el índice realmente publicado."""

    @classmethod
    def setUpClass(cls):
        cls.indice = json.loads((ROOT / "web" / "public" / "data" / "buscador.json")
                                .read_text(encoding="utf-8"))
        cls.entidades = cls.indice["entidades"]
        cls.estado = json.loads((ROOT / "web" / "public" / "data" / "estado_actual.json")
                                .read_text(encoding="utf-8"))

    def test_toda_entidad_tiene_lo_necesario_para_encuadrar(self):
        incompletas = [
            e for e in self.entidades
            if e.get("tipo") not in TIPOS or not e.get("nombre")
            or not isinstance(e.get("lat"), (int, float))
            or not isinstance(e.get("lon"), (int, float))
        ]
        self.assertEqual(incompletas, [])

    def test_las_coordenadas_caen_en_la_region(self):
        fuera = [
            e["nombre"] for e in self.entidades
            if not (-60 <= e["lon"] <= -50 and -36 <= e["lat"] <= -29)
        ]
        self.assertEqual(fuera, [])

    def test_los_cursos_traen_envolvente(self):
        sin_bbox = [e["nombre"] for e in self.entidades
                    if e["tipo"] == "curso" and len(e.get("bbox") or []) != 4]
        self.assertEqual(sin_bbox, [])

    def test_cada_estacion_del_estado_esta_en_el_indice_con_su_slug(self):
        publicadas = list(self.estado["estaciones"])
        for clave in ("ina", "ana", "sohma"):
            publicadas.extend((self.estado.get(clave) or {}).get("estaciones", []))
        esperados = {e["slug"] for e in publicadas}
        indexados = {e["slug"] for e in self.entidades if e["tipo"] == "estacion"}
        self.assertEqual(esperados, indexados)

    def test_no_hay_localidades_repetidas(self):
        nombres = [e["nombre"] for e in self.entidades if e["tipo"] == "localidad"]
        self.assertEqual(len(nombres), len(set(nombres)))


if __name__ == "__main__":
    unittest.main()
