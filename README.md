# Cauce — ríos del Uruguay en tiempo real

Mapa web interactivo de la red hídrica uruguaya donde cada río se dibuja con
ancho, color y animación proporcionales a su caudal, al estilo de
[River Flow Map USA](https://norway-charts.netlify.app/river_flow_map_usa/).
Incluye datos en vivo de 8 fuentes (DINAGUA, INUMET, INIA, Salto Grande, UTE,
INA Argentina, ANA Brasil, SOHMA), modo creciente con manchas oficiales de
inundación y activación automática por nivel de estación, y previsión a 7 días
en la cuenca del río Negro.

## Aviso

**Cauce no es un servicio oficial de alertas.** Nadie monitorea el sitio ni
valida sus avisos. Ante una emergencia, llame al 911. Los avisos y advertencias
oficiales los emite [INUMET](https://www.inumet.gub.uy/); la respuesta ante
inundaciones la coordina el
[SINAE](https://www.gub.uy/sistema-nacional-emergencias/) a través del CECOED
de cada departamento.

Limitaciones conocidas de los datos derivados:

- La activación de manchas usa un umbral **aproximado (±1 m)**, obtenido al
  convertir la cota del estudio al cero de la estación, y no está validada
  contra eventos históricos.
- El factor «× la media» es una escala de visualización, no una estimación
  hidrológica: un caudal medido escala el curso entero, sin tiempo de tránsito
  ni afluentes, contra la media modelada de HydroRIVERS.
- Los umbrales de lluvia (50 mm/24 h, 100 mm/72 h) son fijos: no consideran
  humedad antecedente ni tamaño de cuenca.
- Solo hay manchas donde existe estudio oficial. Fuera de esas ciudades, la
  ausencia de mancha no implica ausencia de riesgo.
- La validación retrospectiva sobre 2019 (`pipeline/validar_activacion.py`)
  da 4 aciertos y 1 fallo en 5 eventos con umbral y serie histórica. En
  Aguas Corrientes los umbrales de 100 años y de creciente extrema están a
  0,23 m, menos que la incertidumbre del propio umbral; en 25 de Agosto el
  único umbral utilizable es el extremo, y un evento real no lo activó.

## Estado

En vivo en <https://nicoseijas.github.io/cauce/>. Fases 0–4 del
[ROADMAP](ROADMAP.md) completas: mapa animado con datos en vivo (cron cada
2 h), modo creciente y vista de anomalía.

## Desarrollo

```bash
# pipeline de datos (Python)
python -m venv .venv && .venv/Scripts/pip install geopandas pyogrio requests pandas
.venv/Scripts/python pipeline/descargar_capas.py   # capas WFS DINAGUA -> data/raw/
.venv/Scripts/python pipeline/build_red.py         # red recortada -> data/processed/
.venv/Scripts/python pipeline/build_climatologia.py  # caudal medio DINAGUA por tramo
.venv/Scripts/python pipeline/build_estaciones.py  # mapping estación<->tramo
.venv/Scripts/python pipeline/verificar_join.py    # chequeo estación<->tramo

# validación retrospectiva de la activación de manchas (descarga ~50 MB de CKAN)
.venv/Scripts/python pipeline/validar_activacion.py --anio 2019

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

1. **Esqueleto estático**: HydroRIVERS recortado a Uruguay (geometría y
   topología), opcionalmente enriquecido con la red de cursos de DINAGUA
   (13.678 tramos con nombre y jerarquía). El **caudal medio de referencia**
   sale de la climatología nacional de DINAGUA (*Regionalización de
   estadísticas de caudales*, 2025: caudal específico por subcuenca de nivel 2,
   1980–2010) acumulado por área aguas arriba; el `DIS_AV_CMS` de HydroRIVERS
   queda solo para los ríos cuya cuenca entra al país ya formada.
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
| DINAGUA / Ministerio de Ambiente (Uruguay) | Estaciones, red de cursos, cuencas, manchas de inundación, mediciones de nivel 2017–2019, caudal específico por subcuenca | Datos abiertos gub.uy (odc-uy) |
| HydroSHEDS / HydroRIVERS | Geometría de red con caudal medio | Licencia HydroSHEDS (libre con atribución) |
| INUMET | Precipitación horaria | odc-uy |
| INIA (GRAS) | Precipitación diaria (09 a 09 h) | odc-uy |
| UTE | Previsión de niveles y erogados del río Negro | pública, sin licencia declarada |
| SOHMA (Armada Nacional) | Mareógrafos del Río de la Plata | pública, sin licencia declarada |
| INA / Prefectura Naval (Argentina) | Alturas/caudales río Uruguay | pública, sin licencia declarada |
| ANA (Brasil) | Niveles, caudales y lluvia en cuencas compartidas | pública, sin licencia declarada |
| Salto Grande (CTM) | Datos operativos de la represa | sin licencia declarada |

Las fuentes «sin licencia declarada» se consultan en vivo y se archivan en
`data/historico/`. La redistribución de ese archivo queda sujeta a lo que cada
organismo defina; ante un pedido de retiro, se quita.

Cita sugerida: Seijas, N. *Cauce — ríos del Uruguay*.
<https://nicoseijas.github.io/cauce/>
