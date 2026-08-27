# Cauce — ríos del Uruguay en tiempo real

Mapa web interactivo de la red hídrica uruguaya donde cada río se dibuja con
ancho, color y animación proporcionales a su caudal, al estilo de
[River Flow Map USA](https://norway-charts.netlify.app/river_flow_map_usa/).
Incluye datos en vivo de 8 fuentes (DINAGUA, INUMET, INIA, Salto Grande, UTE,
INA Argentina, ANA Brasil, SOHMA), modo creciente con manchas oficiales de
inundación, una compuerta de activación por nivel actualmente deshabilitada, y
previsión a 7 días en la cuenca del río Negro.

## Aviso

**Cauce no es un servicio oficial de alertas.** Nadie monitorea el sitio ni
valida sus avisos. Ante una emergencia, llame al 911. Los avisos y advertencias
oficiales los emite [INUMET](https://www.inumet.gub.uy/); la respuesta ante
inundaciones la coordina el
[SINAE](https://www.gub.uy/sistema-nacional-emergencias/) a través del CECOED
de cada departamento.

Limitaciones conocidas de los datos derivados:

- La activación automática de manchas está **deshabilitada por defecto**. Las
  19 localidades candidatas conservan sus escenarios oficiales manuales, pero
  ninguna se marca «activa ahora» hasta validar tanto el datum como la relación
  hidráulica estación→localidad.
- El factor «× la media» es una escala de visualización, no una estimación
  hidrológica: un caudal medido escala el curso entero, sin tiempo de tránsito
  ni afluentes. El mapa lo rotula como estimado y declara si el insumo fue
  observado o pronosticado.
- Cada nivel y caudal publica una bandera QC. Los valores futuros, no finitos o
  fuera del rango físico operativo se rechazan; un salto de nivel >1 m entre
  lecturas separadas ≤2 h queda dudoso. Ninguno se usa en factores ni
  activaciones. El valor original no se corrige ni se elimina del snapshot.
- Los umbrales de lluvia (50 mm/24 h, 100 mm/72 h) son fijos: no consideran
  humedad antecedente ni tamaño de cuenca.
- Solo hay manchas donde existe estudio oficial. Fuera de esas ciudades, la
  ausencia de mancha no implica ausencia de riesgo.
- La validación retrospectiva 2017–2019 registra 10 eventos candidatos: 5 no
  tienen cobertura y 5 poseen un hidrograma completo; en estos últimos la
  regla coincide 4 veces y omite 1. Es evidencia exploratoria, no desempeño
  operativo: faltan eventos negativos exhaustivos, datum confirmado y
  relación hidráulica validada. El dictamen público mantiene 0 localidades
  habilitables.

## Estado

Publicado en <https://nicoseijas.github.io/cauce/>. Fases 0–4 del
[ROADMAP](ROADMAP.md) completas: mapa animado con actualización cada 2 h, modo
creciente y vista de anomalía. La interfaz muestra «RECIENTE», «PARCIAL» o
«VENCIDO» según la edad del archivo y el estado de cada fuente; si faltan datos
no emite un resultado negativo de inundación.

## Desarrollo

```bash
# pipeline de datos (Python)
python -m venv .venv && .venv/Scripts/pip install -r requirements.lock
.venv/Scripts/python pipeline/descargar_capas.py   # capas WFS DINAGUA -> data/raw/
.venv/Scripts/python pipeline/build_red.py         # red recortada -> data/processed/
.venv/Scripts/python pipeline/build_climatologia.py  # caudal medio DINAGUA por tramo
.venv/Scripts/python pipeline/build_estaciones.py  # mapping estación<->tramo
.venv/Scripts/python pipeline/verificar_join.py    # chequeo estación<->tramo

# pruebas de la compuerta de seguridad temporal/hidráulica
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python pipeline/build_catalogo.py --check

# informe retrospectivo por evento y cuenca (descarga ~165 MB de CKAN la primera vez)
.venv/Scripts/python pipeline/build_validacion_activacion.py

# web (Vite + MapLibre)
cd web && npm install
npm run dev        # desarrollo
npm run build      # producción (dist/)
```

## Enlaces permanentes

Cada estación tiene una URL propia que se puede compartir, citar o guardar:

```text
https://nicoseijas.github.io/cauce/estaciones/paso-de-los-toros
```

El popup de cada estación ofrece «Copiar enlace a esta estación». Abrir uno de
esos enlaces lleva el mapa a la estación y muestra su última observación.

El segmento legible deriva del nombre que publica el organismo. Cuando dos
organismos miden el mismo lugar, el segundo lleva el organismo como sufijo:
`nueva-palmira` es la estación de DINAGUA y `nueva-palmira-ina` la del INA.

Como un nombre publicado puede cambiar, cada estación tiene además un
identificador canónico `<organismo>-<id de origen>` que no cambia nunca. Sirve
como enlace alternativo y redirige al nombre legible vigente:

```text
/estaciones/dinagua-189   ->   /estaciones/paso-de-los-toros
```

Ambos identificadores se publican en `estado_actual.json` como `estacion_id` y
`slug`, y el esquema del contrato de datos los exige.

## Datos para investigación

La interfaz publica los datos también en forma tabular: «Ver los datos en una
tabla» abre tres hojas con búsqueda, filtro por fuente, orden por columna y
exportación a CSV de lo que quede filtrado.

| Hoja | Contenido |
|---|---|
| Estaciones | Última observación de las cuatro redes: nivel, caudal, caudal medio de referencia, antigüedad y bandera QC |
| Histórico | Una fila por instante medido de la serie acumulada (45 días), unida por fecha de observación |
| Lluvia | Acumulados de 24 y 72 h de INUMET e INIA |

Cada fila enlaza con su estación en el mapa. El histórico se dibuja hasta 2.000
filas por vez —el conteo declara cuántas quedaron fuera— y el CSV exporta la
selección completa. La serie publicada excluye los valores que el control de
calidad rechazó o dejó en duda; los snapshots de `data/historico/` los
conservan con su bandera.

El directorio `web/public/data/` es también un paquete de datos documentado:

- [`datapackage.json`](web/public/data/datapackage.json) inventaría los 16
  productos, sus fuentes, clasificación (observado, oficial, pronosticado o
  estimado), licencia conocida, limitaciones, tamaño, hash, extensión espacial
  o temporal y esquema observado.
- [`checksums.sha256`](web/public/data/checksums.sha256) permite verificar que
  los productos y los esquemas no fueron alterados. Desde `web/public/data/`,
  ejecutar `sha256sum -c checksums.sha256`.
- [`estado-v3.schema.json`](web/public/data/schema/estado-v3.schema.json)
  documenta el contrato de `estado_actual.json`, incluidas las banderas de
  calidad y la cobertura de activación.
- [`validacion_activacion.json`](web/public/data/validacion_activacion.json) y
  su [`esquema v1`](web/public/data/schema/validacion-activacion-v1.schema.json)
  publican el análisis por evento completo y cuenca, los archivos fuente con
  su hash, la cobertura faltante y todos los bloqueos de cada candidata.
- [`catalogo_base.json`](data/referencia/catalogo_base.json) contiene los
  metadatos humanos; `pipeline/build_catalogo.py` deriva conteos, extensiones y
  hashes. CI exige que el catálogo se pueda reconstruir sin diferencias.

Las geometrías se almacenan en **OGC:CRS84**, con orden longitud/latitud. El
procesamiento métrico usa **EPSG:32721** cuando el recurso lo declara. Los
niveles usan referencias verticales mixtas —incluidos ceros locales, Wharton y
Ex Wharton— y no deben compararse entre estaciones sin una transformación
vertical documentada. El catálogo declara resolución, fecha, procedencia y
vacíos de cobertura por producto.

Las 19 configuraciones candidatas se clasifican por mecanismo antes de
evaluarlas: 15 fluviales, 2 costeras/estuarinas, 1 pluvial urbana y 1 mixta
sin separar. Diecisiete tienen una estación superficial cercana y solo 14
coinciden además con el curso. La asociación anterior de Salto con un
piezómetro del acuífero Guaraní fue retirada: lluvia o nivel subterráneo no se
usan como atajo para inferir una mancha.

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
   (`curvas_cri`) y zonas urbanas con amenaza de drenaje. Los escenarios son
   manuales; la activación por nivel permanece cerrada hasta validar cada
   relación estación→localidad.

El frontend es un sitio estático (MapLibre GL + capa animada WebGL) alimentado
por archivos generados por un pipeline Python programado (GitHub Actions).

### Control de calidad hidrométrico

`estado_actual.json` usa el esquema 3 y contiene `qc_nivel`/`qc_caudal` por
estación, más un resumen reproducible en `control_calidad`. Los estados son
`ok`, `vencido`, `dudoso`, `rechazado` y `sin_dato`. La referencia de
continuidad solo avanza con una observación aceptada: nunca se desplaza una
serie para acomodar un cambio de datum. Este QC es operativo; no sustituye la
calibración del sensor, una curva de gasto ni la verificación del datum
vertical, y no detecta derivas lentas ni cambios entre lecturas separadas por
más de 2 h.

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
