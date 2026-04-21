# Arquitectura técnica

## Principio rector

Sitio 100 % estático + pipeline de datos programado. No hay backend en
runtime: el navegador solo descarga archivos pregenerados. Esto copia el
modelo del mapa de referencia (Netlify) y elimina costos de operación.

```
┌─────────────────────────── pipeline (Python, GitHub Actions) ───────────────────────────┐
│                                                                                         │
│  una vez / por release:                       cada 1–3 h:                               │
│  HydroRIVERS ─┐                               WFS DINAGUA V_Catalogo_publica ─┐         │
│  shp_cursos ──┼─► build_red.py ─► red hídrica │ Salto Grande (scrape) ────────┼─► build_estado.py │
│  cuencas ─────┘    (PMTiles/GeoJSON           │ INA /pub/datos ───────────────┤    │              │
│                     + atributos estáticos)    │ CARU (scrape, opcional) ──────┘    ▼              │
│                                               │ INUMET CSV (1×/día)      estado_actual.json      │
└───────────────────────────────┬───────────────┴──────────────────┬──────────────────────┘
                                ▼                                  ▼
                        hosting estático (GitHub Pages)
                                ▼
                 frontend: MapLibre GL + capa animada WebGL (TS + Vite)
```

## Pipeline de datos (Python)

Reutilizar `D:\nico\datauy\scraper` como punto de partida (ya resuelve WFS
1.1.0, paginación por rangos de ID, registros corruptos y TLS roto).

### `build_red.py` — corre manualmente o por release

1. Descargar HydroRIVERS SA, recortar al bbox de Uruguay + río Uruguay + bajo
   Río Negro (clip con cuencas nivel 1 de DINAGUA ya descargadas).
2. Filtrar tramos por `UPLAND_SKM` (umbral por zoom; el mapa de referencia usa
   cuenca ≥ 500 km² como piso global y muestra más detalle al acercar).
3. Join con `shp_cursos` de DINAGUA para nombres locales (`nombre_2`) por
   proximidad espacial + similitud de nombre.
4. Asignar a cada tramo: `q_medio` (DIS_AV_CMS), `orden` (ORD_STRA),
   `cuenca_n2`, `nombre`, y el `id_estacion` más cercana aguas arriba/abajo.
5. Emitir:
   - `red.pmtiles` (tiles vectoriales via tippecanoe) para producción, o
     GeoJSON por niveles de zoom si el volumen lo permite (~14 k tramos
     filtrados puede entrar en 2–4 MB gzip como GeoJSON simplificado; medir
     antes de complicarse con tiles).
   - `estaciones.geojson` (catálogo estático: id, nombre, curso, lat/lon).

### `build_estado.py` — cron cada 1–3 h (GitHub Actions)

1. WFS `V_Catalogo_publica`: por estación, `ultimo_valor`, `ultima_fecha`,
   `ultimo_caudal`, `ultima_caudal_fecha`.
2. Salto Grande `datos_horarios.php`: turbinado + vertido (m³/s).
3. INA `alerta.ina.gob.ar/pub/datos/datos`: alturas/caudales de estaciones del
   río Uruguay.
4. CARU (mejor esfuerzo, try/except por fuente: si una fuente cae, el resto
   sigue y se marca `fuente_caida`).
5. Calcular por estación un **factor de estado** (ver modelo abajo) y emitir
   `estado_actual.json` (pequeño: ~100 estaciones + metadatos + timestamp).
6. Persistir el snapshot crudo en `data/historico/YYYY/MM/DD-HH.json`
   (commit al repo o bucket): Uruguay no publica series de caudal, así que
   este archivo es el histórico del proyecto.

Cadencias distintas: INUMET 1×/día; Salto Grande/INA cada hora; WFS DINAGUA
cada 3 h alcanza (la publicación aguas arriba no es más frecuente).

## Modelo de datos para la animación

### Escala visual (igual que el mapa de referencia)

- `ancho_px = k · log10(1 + Q)` con Q en m³/s, clampeado por zoom.
- `velocidad_particulas ∝ log(Q)`; color en rampa por Q o por anomalía.

### Estado dinámico: factor por cuenca

Problema: hay ~100 estaciones para ~14 k tramos y las curvas de gasto no son
públicas. Solución heurística, honesta en la UI:

1. Para cada estación con dato fresco (`ultima_fecha` < umbral, p. ej. 48 h):
   - si hay `ultimo_caudal` fresco: `factor = Q_actual / Q_medio_tramo`.
   - si solo hay nivel: factor derivado del nivel normalizado contra el rango
     histórico de esa estación (percentil del nivel en los snapshots
     acumulados). Es un proxy declarado, no un caudal.
2. Propagar el factor a los tramos de la misma cuenca nivel 2, con decaimiento
   por distancia a la estación.
3. Tramos sin señal fresca: `factor = 1` y estilo "estimado" (línea pálida,
   como hace el mapa USA con caudales no medidos).
4. El frontend multiplica: `Q_render = q_medio · factor`.

## Modo creciente (zonas inundables)

Objetivo: mostrar qué zonas afectaría la crecida de los cursos ante lluvia
extrema. Tres niveles de honestidad, de mayor a menor certeza:

### Nivel 1 — Manchas oficiales por escenario (estático)

- `curvas_tr` de DINAGUA: el usuario elige el escenario ("crecida de 10
  años", "crecida de 100 años" ≈ lluvia extrema) y se pintan los polígonos
  oficiales sobre las ciudades estudiadas.
- `curvas_cri` como capa comparativa: "hasta acá llegó el agua en <evento>"
  (Durazno 2019, Treinta y Tres 2007, …), útil para dar realismo y validar.
- `problemas_drenaje` y `localidades_amenazas` como capa secundaria: zonas
  urbanas con inundación por drenaje pluvial (lluvia intensa local, no
  desborde de río) y localidades con amenaza identificada donde no hay mancha
  dibujada.
- Pipeline: descarga por WFS (mismo scraper), simplificación y tiles; las
  curvas costeras (`curvas_costas`, 281 k features) solo si se decide cubrir
  el litoral y siempre tileadas.

### Nivel 2 — Manchas activadas por el dato en vivo (dinámico, Fase 2+)

Las curvas traen `cota_local`/`cota_oficial` y las estaciones reportan nivel
con cota cero conocida. Con eso:

1. En el build del estado, por cada localidad con curvas: comparar nivel
   actual (y tendencia) de la estación asociada contra las cotas de sus
   curvas.
2. Pintar la mancha de mayor cota superada ("hoy el agua cubre ~esto") y
   señalar la siguiente ("a X cm de la mancha de 10 años").
3. Precondición técnica: verificar la compatibilidad de datum entre
   `cota_oficial` de las curvas y la "Cota Cero (Wh)" del catálogo de
   estaciones, localidad por localidad, antes de habilitar la comparación.

### Nivel 3 — Estimación propia donde no hay estudio oficial (opcional, avanzado)

- Método HAND (Height Above Nearest Drainage) sobre un DEM: clasifica el
  terreno por altura relativa al cauce más próximo y aproxima la mancha para
  un nivel de crecida dado. Insumo: MDT nacional de IDEuy (vuelo 2017/18) o
  Copernicus GLO-30 como fallback.
- Es una aproximación sin hidráulica (no modela puentes, terraplenes,
  remansos): en la UI debe distinguirse siempre de las manchas oficiales
  (trama distinta + leyenda "estimación por modelo de terreno").
- Cómputo pesado y offline (pipeline, no navegador); emprender solo si los
  niveles 1–2 quedan cortos.

## Frontend

- **Stack**: TypeScript + Vite; MapLibre GL JS para basemap y navegación;
  la red animada como **capa custom WebGL** de MapLibre (o deck.gl si el
  spike de Fase 0 muestra que alcanza — `PathLayer` + shader de dash animado).
  Partículas: instanciar puntos que avanzan por la polilínea con offset
  animado en el vertex shader; 14 k tramos filtrados por zoom es un volumen
  cómodo para WebGL.
- **Basemap**: estilo propio minimalista (tierra neutra, sin calles) desde
  tiles libres (OpenFreeMap / Protomaps) para que los ríos dominen la escena.
- **Capas activables** (paridad con la referencia): estaciones, represas,
  nombres de ríos, modo "caudal vs. normal".
- **Interacción**: hover resalta el curso completo (agrupar tramos por
  `codigo5`/nombre), click abre panel con estación más cercana, dato, fecha y
  frescura.
- **Datos en runtime**: `red.pmtiles` (o GeoJSON) cacheado fuerte +
  `estado_actual.json` con `cache-control` corto. El JSON de estado es lo
  único que cambia entre visitas.

## Hosting y CI — decisión: GitHub Pages

- Sitio publicado con GitHub Pages vía el workflow oficial
  (`actions/deploy-pages`), build del frontend con Vite en Actions.
- `build_estado.py` corre en un workflow con `schedule` y redeploya Pages con
  el `estado_actual.json` nuevo (o lo commitea a una rama de datos que el
  deploy incluye). GitHub Pages sirve con `cache-control: max-age=600`, que
  encaja con una cadencia de 1–3 h.
- Restricciones a respetar: archivos < 100 MB (los crudos van gitignoreados),
  repo idealmente < 1 GB → los snapshots históricos de Fase 4 no se acumulan
  en la rama principal (rama de datos aparte o release assets; decidir al
  llegar).
- GitHub Pages soporta range requests, así que PMTiles es viable si se
  necesita.
- Presupuesto de payload inicial: < 3 MB comprimido.

## Decisiones abiertas (resolver en Fase 0)

| Decisión | Opciones | Criterio |
|---|---|---|
| Formato de red | GeoJSON simplificado vs. PMTiles | Peso real tras filtrado; empezar por GeoJSON si < 4 MB gzip |
| Motor de animación | Capa custom MapLibre vs. deck.gl | Spike de 60 fps en móvil con 14 k tramos |
| Histórico de snapshots | Commits al repo vs. bucket | Volumen (~100 KB/snapshot × 8/día ≈ 300 MB/año sin comprimir → bucket probablemente) |
| Alcance geográfico del río Uruguay/Plata | Solo margen uruguaya vs. cuenca binacional visible | Estética del mapa; HydroRIVERS lo da gratis |
