# Fuentes de datos

Inventario relevado y verificado el 2026-08-20. "VERIFICADO" = la URL se
consultó directamente y respondió como se describe; "NO VERIFICADO" = afirmado
por documentación o buscadores.

Nota transversal: `www.ambiente.gub.uy` sirve una cadena TLS incompleta (falta
el certificado intermedio). Los clientes HTTP estrictos fallan la validación;
hay que inyectar la cadena o tolerar la verificación explícitamente (el
scraper existente usa `verify=False`).

## 1. GeoServer DINAGUA (WFS) — fuente principal — VERIFICADO

- Endpoint: `https://www.ambiente.gub.uy/dinagua-gs/wfs`
  (también responde en `/dinagua-gs/dinagua/ows`).
- Sin autenticación, salida `application/json` (GeoJSON).
- Usar WFS 1.1.0 para las vistas sin clave primaria (2.0.0 falla); paginar por
  rangos de `id` con `CQL_FILTER` (ya resuelto en el scraper de `datauy`).

### Capas clave

| Capa | Contenido | Estado |
|---|---|---|
| `dinagua:V_Catalogo_publica` | **~100 estaciones hidrométricas** con `Nombre`, `Tipo` (hidrométrica/limnimétrica), `Curso`, `LAT`/`LONG`, área de cuenca, cota cero, y `ultimo_valor`/`ultima_fecha` (nivel), `ultimo_caudal`/`ultima_caudal_fecha` (caudal m³/s), `diasnivel`/`diascaudal` (antigüedad) | Funciona. **Es la única vía programática a datos actuales de caudal/nivel de Uruguay** |
| `dinagua:shp_cursos` | Red de cursos de agua: **13.678 tramos** MultiLineString con `nombre_2`, `long` (km), `clase` (jerarquía), `codigo5` | Funciona (verificado con GetFeature). Sin atributos de caudal. CRS proyectado (confirmar EPSG al descargar) |
| `dinagua:shp_cuencas_nivel1..5` | Cuencas hidrográficas en 5 niveles | Funciona; niveles 1 y 2 ya descargados en `datauy/scraper/output` |
| `dinagua:sdh_estaciones` | Misma info de estaciones con `id_cuenca_nivel5` | **Rota**: el servidor falla con "No code EPSG:94309" incluso pidiendo solo atributos. Usar `V_Catalogo_publica` |
| `dinagua:shp_espejos_de_agua`, `shp_esteros_banados` | Lagos, embalses, bañados | No probadas; mismas convenciones |
| `V_Pozos_publica`, `V_Tomas_publica`, `V_Embalses_publica`, `V_Usos_*_publica` | Aprovechamientos de agua (permisos) | Funcionan; no necesarias para el mapa de caudales |

### Advertencia de frescura

La frescura de `V_Catalogo_publica` es heterogénea: los **niveles** están casi
al día en muchas estaciones; los **caudales** publicados pueden tener años de
rezago en algunas (ej. Mercedes con caudal de 2020). Es un snapshot de "último
valor", no una serie temporal. El pipeline debe filtrar por antigüedad.

## 2. SIH y telemetría DINAGUA — sin API pública — VERIFICADO

- Visualizador SIH: `https://www.ambiente.gub.uy/SIH/paginas/visualizador/visualizador.xhtml`
  (JSF/PrimeFaces con sesión; semáforo de frescura <24 h / 24–48 h / >48 h;
  confirma que la red telemétrica transmite casi en tiempo real). Scrapearlo
  es frágil; no usar como fuente primaria.
- Panel interno: `https://www.ambiente.gub.uy/informacion_hidrica/componentes/tablaCards.php`
  (HTML sin auth, estado de envío de estaciones el mismo día) y
  `tablasValores.php?ID=<código>` (lecturas por sensor). Endpoints internos
  sin garantía de estabilidad — solo como diagnóstico.
- Contacto oficial para pedir API/series/curvas de gasto:
  `dinagua.servicios@ambiente.gub.uy`.

## 3. Salto Grande (CTM) — caudal horario del bajo río Uruguay — VERIFICADO

- `https://www.saltogrande.org/datos_operativos.php` — niveles de embalse y
  restitución, actualización horaria.
- `https://www.saltogrande.org/datos_horarios.php` — **caudal turbinado y
  vertido en m³/s**, navegable al pasado con `?fh=YYYY-MM-DD+HH:00:00`.
  HTML renderizado en servidor, sin JS: scraping simple y estable; el
  histórico se reconstruye iterando `fh`.
- Turbinado + vertido ≈ caudal real del río Uruguay aguas abajo de la represa.
- Licencia/términos no declarados.

## 4. INA Argentina — la mejor API REST de la región — VERIFICADO

- Base: `https://alerta.ina.gob.ar/pub/datos/` (REST, JSON/GeoJSON/CSV, sin
  autenticación). GUI de ayuda: `https://alerta.ina.gob.ar/pub/gui/apibase`.
- Endpoints: `/estaciones` (con lat/lon, río, niveles de alerta/evacuación),
  `/series`, `/datos` (observaciones), `/datosProno` (pronósticos),
  `/variables`.
- Cubre la cuenca del Plata incluido el **río Uruguay** (alturas y caudales);
  pronósticos del río Uruguay lunes/miércoles/viernes.
- Para el litoral (frontera oeste) es la vía programática más sólida.

## 5. CARU — alturas de puertos del río Uruguay — VERIFICADO, frágil

- App enlazada desde `caru.org.uy`:
  `http://190.0.152.194:8080/alturas/web/user/alturas` (HTTP plano sobre IP).
- Tabla HTML con alturas de ~15 puertos (Bella Unión, Salto, Paysandú,
  Concordia, Colón, etc.), registros del día en períodos de 6/12/24 h con
  tendencia. Sin JSON. Usar solo como respaldo, con tolerancia a caída.

## 6. INUMET — precipitación — VERIFICADO

- Vía CKAN (`catalogodatos.gub.uy`), datasets
  `inumet-observaciones-meteorologicas-*`: precipitación puntual **horaria**
  de estaciones automáticas, CSV/XML, **actualización diaria** (verificado
  modificado el mismo 2026-08-20). Licencia odc-uy.
- Descarga directa de recurso CSV sin auth. No existe API REST propia de
  INUMET (`api.inumet.gub.uy` no resuelve).
- Complemento INIA GRAS vía CKAN (`inia-precipitacion-temps-extremas-{le,lb,
  tb,sg,tyt}`): pluviómetro **diario** (09 a 09 h), un CSV por año,
  actualización diaria (verificado 2026-08-21). El recurso del año se
  resuelve por `package_show`; coordenadas en el JSON de metadatos de cada
  dataset. Licencia odc-uy.

## 7. CKAN catalogodatos.gub.uy — histórico — VERIFICADO

- API CKAN estándar sin auth:
  `https://catalogodatos.gub.uy/api/3/action/package_search?q=...`.
  El buscador no hace stemming ("caudales" da 0; "niveles" y "DINAGUA" sí).
- `ambiente-dinagua-mediciones-de-nivel-2017/2018/2019`: CSV de niveles,
  congelados desde 2022. **No hay datasets de caudal en CKAN**; los caudales
  históricos viven en PDFs (Anuario Hidrológico 2021–2024 en gub.uy).

## 8. Geometría de la red hidrográfica

| Fuente | Rol | Estado |
|---|---|---|
| **HydroRIVERS v1.0** (`https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_sa_shp.zip`, 95 MB Sudamérica) | **Base del mapa animado**: cada tramo trae caudal medio de largo plazo (`DIS_AV_CMS`, m³/s — confirmar nombre de columna en el PDF técnico), orden de Strahler (`ORD_STRA`) y área drenada (`UPLAND_SKM`). Es lo que usa el mapa de referencia | VERIFICADO (descarga); licencia libre con atribución, incluye uso comercial |
| `dinagua:shp_cursos` (WFS §1) | Nombres locales y jerarquía nacional; join con estaciones por nombre de curso | VERIFICADO |
| IDEuy hidrografía 1:10.000 (CKAN `ide-hidrografia-nacional-y-urbana` → el GeoJSON es una grilla índice; cada feature trae `descarga_zip` hacia `https://visualizador.ide.uy/descargas/datos/Hidrografia/Nacional/<CUENCA>.zip`) | Detalle estético en zooms altos. Sin caudal ni acumulación de flujo | VERIFICADO (mecanismo de descarga) |
| MTOP GeoServer (`https://geoservicios.mtop.gub.uy/geoserver/`, capas `hidro_pl`, `hidro_pg`, `v_cursos_nav_flot`) | Alternativa de referencia; sin caudal | VERIFICADO |
| OSM/Geofabrik (`uruguay-latest.osm.pbf`) | Complemento; topología inconsistente | NO VERIFICADO |

## 9. Riesgo de inundación — GeoServer DINAGUA — VERIFICADO

Mismo endpoint WFS de §1. Verificado el 2026-08-20 con GetFeature; estas capas
son la base del "modo creciente" del mapa.

| Capa | Contenido | Verificación |
|---|---|---|
| `dinagua:curvas_tr` | **238 polígonos de mancha de inundación por período de retorno** (`tipo_curva`: "10 años", "100 años", …) por ciudad y curso, con `cota_local`, `cota_oficial`, fuente del estudio hidráulico. Ej.: Río Santa Lucía Tr100, Cañada Blanco Tr10 | Funciona |
| `dinagua:curvas_cri` | **82 polígonos de inundaciones reales registradas** (CRI), con `fecha_evento` y cotas. Ej.: Río Yí en Durazno jun-2019, Olimar/Yerbal en Treinta y Tres 2007. Fuentes: FAU sensores remotos, CECOED, ITU-UdelaR | Funciona |
| `dinagua:localidades_amenazas` | 554 localidades con flags de amenaza: `ribera`, `canadas`, `drenaje`, `presas`, `accesibilidad`, `costas` + total | Funciona |
| `dinagua:problemas_drenaje` | 1.925 polígonos urbanos con conflictos de drenaje pluvial (inundación de viviendas/calles) | Funciona |
| `dinagua:curvas_costas` | Escenarios costeros (marejada/nivel del mar), **281.023 features** — requiere tiling sí o sí | Funciona (volumen enorme) |
| `dinagua:localidades_tr`, `localidades_cri`, `localidades_mdr`, `localidades_ndri` | Índices por localidad de los productos anteriores (mapas de riesgo, drenaje) | No probadas en detalle |
| `dinagua:shp_areas_inf` | Presunta capa de áreas inundables | **Rota** (respuesta no-JSON), investigar |

Limitaciones:

- `curvas_tr`/`curvas_cri` cubren solo las ciudades y cursos estudiados por
  DINAGUA (Inundaciones y Drenaje Urbano), no todo el país. Inventariar la
  cobertura real (lista de localidades y qué Tr tiene cada una) es tarea de
  pipeline.
- Las cotas (`cota_local`/`cota_oficial`) permiten cruzar con el nivel actual
  de las estaciones (§1) para saber qué mancha está activa o cerca de
  activarse — verificar que el datum coincida con la "Cota Cero (Wh)" del
  catálogo de estaciones antes de comparar.
- Para zonas sin estudio oficial, una estimación nacional exige modelado
  propio (ver HAND en `02-arquitectura.md`); el MDT nacional de IDEuy
  (vuelo 2017/18) es el insumo — NO VERIFICADA su descarga en este
  relevamiento.

## 10. Huecos confirmados

1. **No existe API pública de caudales en tiempo real de Uruguay.** Lo más
   cercano es el "último valor" del WFS de DINAGUA.
2. **No hay series temporales de caudal descargables** (solo niveles CKAN
   2017–2019 y PDFs de anuarios). Consecuencia: el proyecto debe persistir
   sus propios snapshots desde el día uno.
3. **UTE no publica datos operativos de sus represas** (Bonete, Baygorria,
   Palmar). Proxy: informes PDF diarios de ADME (`adme.com.uy`, requiere
   parsing de PDF) o las estaciones DINAGUA sobre el Río Negro.
4. **Las curvas de gasto (nivel→caudal) no son públicas**: convertir nivel a
   caudal exige pedirlas a DINAGUA o usar heurísticas declaradas como tales.
5. CARP/Río de la Plata sin datos abiertos; proxy: SOHMA (boletines) e INA.
