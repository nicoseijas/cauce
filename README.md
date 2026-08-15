# Cauce — ríos del Uruguay en tiempo real

Mapa web interactivo de la red hídrica uruguaya donde cada río se dibuja con
ancho, color y animación proporcionales a su caudal, al estilo de
[River Flow Map USA](https://norway-charts.netlify.app/river_flow_map_usa/).
Incluye datos en vivo de 8 fuentes (DINAGUA, Salto Grande, INUMET, INA, UTE,
ANA Brasil, SOHMA), modo creciente con manchas oficiales de inundación y
activación automática por nivel de estación, y previsión a 7 días en la
cuenca del río Negro.

## Estado

Fases 0–4 del [ROADMAP](ROADMAP.md) completas: mapa animado con datos en
vivo (cron cada 2 h), modo creciente y vista de anomalía. Pendiente de
publicación en GitHub Pages.

## Desarrollo

```bash
# pipeline de datos (Python)
python -m venv .venv && .venv/Scripts/pip install geopandas pyogrio requests pandas
.venv/Scripts/python pipeline/descargar_capas.py   # capas WFS DINAGUA -> data/raw/
.venv/Scripts/python pipeline/build_red.py         # red recortada -> data/processed/
.venv/Scripts/python pipeline/verificar_join.py    # chequeo estación<->tramo

# web (Vite + MapLibre)
cd web && npm install
npm run dev        # desarrollo
npm run build      # producción (dist/)
```

HydroRIVERS se descarga aparte (95 MB) a `data/raw/`:
<https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_sa_shp.zip>

## Documentos

| Documento | Contenido |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Fases del proyecto, entregables y criterios de salida |
| [docs/01-fuentes-de-datos.md](docs/01-fuentes-de-datos.md) | Inventario verificado de APIs y datasets de agua de Uruguay |
| [docs/02-arquitectura.md](docs/02-arquitectura.md) | Stack, pipeline de datos y modelo de renderizado |
| [docs/03-mvp.md](docs/03-mvp.md) | Especificación del MVP con criterios de aceptación |

## Resumen de la solución

Uruguay no publica una API REST de caudales en tiempo real, así que el mapa
combina tres niveles de datos:

1. **Esqueleto estático**: HydroRIVERS (caudal medio de largo plazo
   `DIS_AV_CMS` por tramo) recortado a Uruguay, opcionalmente enriquecido con
   la red de cursos de DINAGUA (13.678 tramos con nombre y jerarquía).
2. **Señal dinámica**: WFS de DINAGUA (`V_Catalogo_publica`: último nivel y
   último caudal de ~100 estaciones), caudal horario de Salto Grande
   (turbinado + vertido), API REST del INA argentino para el río Uruguay y
   tabla de alturas de CARU.
3. **Contexto**: precipitación horaria de INUMET (CKAN, actualización diaria).
4. **Modo creciente**: manchas oficiales de inundación de DINAGUA por período
   de retorno (`curvas_tr`), inundaciones históricas registradas
   (`curvas_cri`) y zonas urbanas con amenaza de drenaje, activables según el
   nivel actual de las estaciones.

El frontend es un sitio estático (MapLibre GL + capa animada WebGL) alimentado
por archivos generados por un pipeline Python programado (GitHub Actions).

## Licencia y datos

Código bajo [licencia MIT](LICENSE). Proyecto open source, publicado en
GitHub Pages. Los datos conservan las licencias de sus fuentes y requieren
atribución:

| Fuente | Datos | Licencia |
|---|---|---|
| DINAGUA / Ministerio de Ambiente (Uruguay) | Estaciones, red de cursos, cuencas, manchas de inundación | Datos abiertos gub.uy (odc-uy) |
| HydroSHEDS / HydroRIVERS | Geometría de red con caudal medio | Licencia HydroSHEDS (libre con atribución) |
| INUMET | Precipitación | odc-uy |
| INA (Argentina) | Alturas/caudales río Uruguay | pública, sin licencia declarada |
| Salto Grande (CTM) | Datos operativos de la represa | sin licencia declarada |

## Activos existentes

- `D:\nico\datauy\scraper` — scraper WFS ya funcional contra el GeoServer de
  DINAGUA, con paginación por rangos de ID y manejo de registros corruptos.
  Es la base del módulo de ingesta. Ya tiene descargadas cuencas nivel 1/2 y
  departamentos en GeoJSON.
