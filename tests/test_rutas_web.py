"""El enrutado por History API depende de dos declaraciones de la raíz del
sitio que viven en archivos distintos. Si dejan de coincidir, las rutas
anidadas cargan el índice con las URL de los assets rotas, y eso no lo
detecta ni el typecheck ni el build."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VITE = ROOT / "web" / "vite.config.ts"
PAGINA_404 = ROOT / "web" / "public" / "404.html"


def _base_de_vite() -> str:
    texto = VITE.read_text(encoding="utf-8")
    m = re.search(r'base:\s*"([^"]+)"', texto)
    if not m:
        raise AssertionError("vite.config.ts no declara base")
    return m.group(1)


def _raiz_de_404() -> str:
    texto = PAGINA_404.read_text(encoding="utf-8")
    m = re.search(r'var raiz = "([^"]+)"', texto)
    if not m:
        raise AssertionError("404.html no declara la raíz del sitio")
    return m.group(1)


class TestRaizDelSitio(unittest.TestCase):
    def test_vite_y_404_declaran_la_misma_raiz(self):
        self.assertEqual(_base_de_vite(), _raiz_de_404())

    def test_la_raiz_es_absoluta(self):
        # Una base relativa rompe los assets en /estaciones/<slug>.
        raiz = _base_de_vite()
        self.assertTrue(raiz.startswith("/"), raiz)
        self.assertTrue(raiz.endswith("/"), raiz)

    def test_el_404_no_se_indexa_y_conserva_la_ruta(self):
        texto = PAGINA_404.read_text(encoding="utf-8")
        self.assertIn('name="robots" content="noindex"', texto)
        self.assertIn("sessionStorage", texto)


if __name__ == "__main__":
    unittest.main()
