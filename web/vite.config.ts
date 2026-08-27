import { defineConfig } from "vite";

// Base absoluta: el enrutado por History API necesita saber bajo qué prefijo
// se sirve el sitio, y con base relativa los assets se romperían en cualquier
// ruta anidada como /cauce/estaciones/<slug>. Debe coincidir con la raíz
// declarada en public/404.html.
export default defineConfig({
  base: "/cauce/",
});
