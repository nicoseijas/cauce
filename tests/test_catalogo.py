import json
import math
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pipeline.build_catalogo import (
    CatalogError,
    analyze_geojson,
    build_outputs,
    load_json_strict,
    validar_estado_v3,
)


ROOT = Path(__file__).resolve().parents[1]


class GeoJsonCatalogTests(unittest.TestCase):
    def test_infiere_extension_geometria_campos_y_tiempo(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-58.1, -34.9]},
                    "properties": {"id": 1, "valor": None, "fecha": "2020-01-02"},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-57.2, -33.0], [-56.5, -31.2]],
                    },
                    "properties": {"id": 2, "valor": 3.5, "fecha": "2020-01-01"},
                },
            ],
        }

        result = analyze_geojson(data, ["fecha"])

        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["position_count"], 3)
        self.assertEqual(result["geometry_counts"], {"LineString": 1, "Point": 1})
        self.assertEqual(result["spatial"]["bbox"], [-58.1, -34.9, -56.5, -31.2])
        self.assertEqual(result["temporal"], {"start": "2020-01-01", "end": "2020-01-02"})
        fields = {field["name"]: field for field in result["schema"]["fields"]}
        self.assertEqual(fields["id"]["type"], "integer")
        self.assertEqual(fields["valor"]["type"], "number")
        self.assertTrue(fields["valor"]["nullable"])

    def test_rechaza_coordenada_fuera_de_crs84(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [577000, 6320000]},
                    "properties": {},
                }
            ],
        }
        with self.assertRaisesRegex(CatalogError, "fuera de OGC:CRS84"):
            analyze_geojson(data)

    def test_rechaza_coordenada_no_finita(self):
        data = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [math.inf, -32]},
                    "properties": {},
                }
            ],
        }
        with self.assertRaisesRegex(CatalogError, "no finita"):
            analyze_geojson(data)


class JsonContractTests(unittest.TestCase):
    def test_rechaza_nan_en_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('{"valor": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "no finita"):
                load_json_strict(path)

    def test_estado_publicado_cumple_invariantes_v3(self):
        state = load_json_strict(ROOT / "web/public/data/estado_actual.json")
        validar_estado_v3(state)

    def test_esquema_publicado_es_json_estricto(self):
        schema = load_json_strict(ROOT / "web/public/data/schema/estado-v3.schema.json")
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["properties"]["schema_version"]["const"], 3)
        Draft202012Validator.check_schema(schema)

    def test_estado_publicado_valida_con_json_schema_2020_12(self):
        schema = load_json_strict(ROOT / "web/public/data/schema/estado-v3.schema.json")
        state = load_json_strict(ROOT / "web/public/data/estado_actual.json")
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(state), key=lambda error: list(error.path))
        self.assertEqual([], [f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors])

    def test_validacion_retrospectiva_valida_con_su_esquema(self):
        schema = load_json_strict(
            ROOT / "web/public/data/schema/validacion-activacion-v1.schema.json"
        )
        report = load_json_strict(ROOT / "web/public/data/validacion_activacion.json")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(report), key=lambda error: list(error.path))
        self.assertEqual([], [f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors])

    def test_catalogo_y_checksums_se_pueden_reconstruir(self):
        catalog_bytes, checksum_bytes = build_outputs()
        catalog = json.loads(catalog_bytes)
        self.assertEqual(catalog["profile"], "data-package")
        self.assertEqual(len(catalog["resources"]), 16)
        state = next(resource for resource in catalog["resources"] if resource["path"] == "estado_actual.json")
        self.assertIn("incluidas vencidas o rechazadas", state["temporal"]["scope"])
        self.assertIn("usable_temporal", state)
        self.assertEqual(state["forecast_temporal"]["horizon_days"], 7)
        self.assertIsNone(state["forecast_temporal"]["probability"])
        self.assertIn(b"datapackage.json", checksum_bytes)
        self.assertIn(b"schema/estado-v3.schema.json", checksum_bytes)
        self.assertIn(b"schema/validacion-activacion-v1.schema.json", checksum_bytes)


if __name__ == "__main__":
    unittest.main()
