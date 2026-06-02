# Roadmap

Fases incrementales; cada una termina con algo publicable. Las estimaciones
son de esfuerzo relativo, no fechas.

## Fase 0 — Preparación y datos base (esfuerzo: bajo)

Objetivo: tener todos los insumos de datos en disco y las decisiones de stack
cerradas.

- [x] Inicializar repo (git, `.gitignore` para datos crudos, estructura
      `pipeline/` + `web/` + `data/`).
- [x] Descargar HydroRIVERS Sudamérica y recortar a Uruguay
      (`pipeline/build_red.py`: 4.569 tramos con `UPLAND_SKM >= 100`,
      1,7 MB GeoJSON).
- [x] Adaptar el scraper de `datauy` como `pipeline/wfs.py` +
      `descargar_capas.py`; descargadas: `shp_cursos` (13.678),
      `V_Catalogo_publica` (100 estaciones), `curvas_tr`, `curvas_cri`,
      `localidades_amenazas`, `problemas_drenaje`; cuencas 1/2 y
      departamentos copiados de `datauy`.
- [x] Join estación ↔ tramo verificado (`pipeline/verificar_join.py`):
      66/83 estaciones con dist < 1 km y ratio de áreas 0,5–2 (la mayoría
      con ratio 1,00). Fallan: estaciones de estuario (Nueva Palmira, Fray
      Bentos) y arroyos bajo el umbral de la red.
- [x] Spike de render: MapLibre GL + capa custom WebGL de partículas
      (animación 100 % en vertex shader) — **60 fps con 20.441 partículas y
      4.569 tramos** en Chrome headless desktop. Falta medir en móvil real
      (queda para Fase 1).

**Criterio de salida: CUMPLIDO** (2026-08-20). Pendiente arrastrado a Fase 1:
el eje del bajo río Uruguay (aguas abajo de Paysandú) queda fuera del buffer
de recorte — ampliar el recorte hacia el oeste o incluir explícitamente
`MAIN_RIV` del río Uruguay.

## Fase 1 — MVP: mapa estático de caudal medio (esfuerzo: medio)

Objetivo: mapa navegable de Uruguay con ríos animados según caudal **medio**
(sin datos en vivo). Ver especificación completa en `docs/03-mvp.md`.

- [x] Pipeline: HydroRIVERS filtrado (`UPLAND_SKM >= 100`), simplificado y
      exportado como GeoJSON único (221 KB gzip: no hacen falta tiles). Eje
      del bajo río Uruguay recuperado por área drenada (el estuario
      Paraná/Plata se excluye); nombres locales por join con `shp_cursos`
      (4.115/4.585 tramos con nombre).
- [x] Frontend: basemap propio (fondo + departamentos), capa de ríos con
      ancho/color en escala logarítmica de `DIS_AV_CMS`.
- [x] Animación de partículas aguas abajo en vertex shader, velocidad y
      brillo proporcionales al caudal (60 fps, ~20.500 partículas).
- [x] Hover: resalta el curso completo (por `codigo5`) con tooltip de nombre
      y caudal medio.
- [x] Workflow de deploy a GitHub Pages (`.github/workflows/deploy.yml`).
- [ ] Publicar: crear el repo en GitHub, push y habilitar Pages.

Validaciones ejecutadas (criterios de `docs/03-mvp.md`): payload ~495 KB gzip
(presupuesto 3 MB), 60 fps desktop, los 15 cursos de referencia presentes con
nombre, orientación aguas abajo verificada en 4.532/4.532 tramos encadenados.
Pendientes: medición en móvil real y URL pública (requiere el push).

**Criterio de salida:** URL pública con el mapa animado de caudal medio,
fluido en desktop y móvil.

## Fase 2 — Capa dinámica: datos casi en tiempo real (esfuerzo: alto)

Objetivo: que el mapa refleje el estado hídrico actual, no solo el promedio.

- [x] `pipeline/build_estaciones.py`: mapping estático estación→tramo
      (72/101 con join validado por distancia + ratio de cuencas), incluye
      pseudo-estación Salto Grande.
- [x] `pipeline/build_estado.py` (solo requests+stdlib, apto cron) genera
      `estado_actual.json` + snapshot en `data/historico/`:
  - WFS DINAGUA `V_Catalogo_publica` (último nivel/caudal por estación). ✔
  - Scraping de `saltogrande.org/datos_horarios.php` (turbinado + vertido). ✔
  - [ ] API INA `alerta.ina.gob.ar/pub/datos/` (alturas/caudales río
        Uruguay) — API verificada viva, falta integrar.
  - [ ] CARU (tabla de alturas de puertos) como respaldo.
- [x] Modelo de escala v1: factor caudal_actual/caudal_medio por estación
      (clamp 0,05–20), propagado a los tramos del mismo curso (`codigo5`);
      gana la estación de mayor cuenca. Tramos sin señal quedan en caudal
      medio, marcados "(estimado)" en el tooltip. (La propagación por cuenca
      nivel 2 con decaimiento queda como mejora.)
- [x] Capa de estaciones: puntos con popup (nivel, caudal, antigüedad) y
      semáforo de frescura <24 h / 24–48 h / >48 h como el SIH.
- [x] Datos viejos: solo escalan cursos las estaciones con caudal de <7 días
      y join validado.
- [x] Workflow cron cada 2 h (`.github/workflows/estado.yml`): regenera el
      JSON, commitea y redeploya Pages (el deploy va inline porque un push
      con `GITHUB_TOKEN` no dispara otros workflows).

**Criterio de salida:** el mapa cambia solo, con timestamp visible de última
actualización y distinción medido/estimado.

## Fase 3 — Modo creciente: zonas inundables (esfuerzo: medio)

Objetivo: mostrar qué zonas afecta la crecida de los cursos ante lluvia
extrema, usando los productos oficiales de DINAGUA (ver
`docs/02-arquitectura.md`, "Modo creciente").

- [x] Pipeline `build_inundacion.py`: capas WFS descargadas, simplificadas y
      exportadas (~690 KB gzip, carga diferida). Cobertura inventariada:
      ~70 localidades, escenarios de 5 a 1000 años + CMP; `periodo`
      parseado a número para filtrar.
- [x] Toggle "modo creciente" con selector de escenario (10 / 100 /
      Extrema, filtro `periodo <=`), manchas apiladas con popup (curso,
      cota, fuente) y nota de cobertura ("fuera de las ciudades con estudio
      la ausencia de mancha no implica ausencia de riesgo").
- [x] Capa "inundaciones registradas" (`curvas_cri`, línea punteada) con
      fecha del evento en el popup.
- [x] Capa de drenaje urbano (`problemas_drenaje`) activable.
- [ ] Puntos de `localidades_amenazas` (554 localidades con amenaza
      identificada sin mancha dibujada).
- [x] Verificación de datum (`pipeline/analizar_datum.py`): los umbrales se
      derivan como `cota_oficial − cota_cero` (datum Wharton). Hallazgo:
      `cota_local` difiere sistemáticamente ~0,9 m de esa derivación en
      varias localidades (referencia local sin documentar) → incertidumbre
      declarada de ±1 m en la UI; confirmar el significado de `cota_local`
      con `dinagua.servicios@ambiente.gub.uy`. 19 localidades con umbrales
      utilizables (`web/public/data/activacion.json`).
- [x] Activación automática: `build_estado.py` compara el nivel fresco
      (<48 h) de la estación asociada contra los umbrales y emite
      `activacion` por localidad (mancha superada + margen a la siguiente).
      El mapa pinta las manchas activas en rojo intenso, el popup antepone
      "ACTIVA AHORA" y el panel resume ("Carmelo: a 0,74 m de su mancha de
      10 años").
- [ ] (Opcional/avanzado) Estimación HAND con MDT de IDEuy para zonas sin
      estudio oficial, siempre etiquetada como estimación propia. Elección
      de DEM, acondicionamiento y derivación de drenaje según la skill
      `terrain-hydrology`; validar contra eventos históricos completos por
      cuenca (AGENTS.md), con las curvas CRI como verdad de terreno.

**Criterio de salida:** en las ciudades cubiertas por DINAGUA (Durazno,
Treinta y Tres, etc.) el mapa muestra la mancha del escenario elegido y, si
hay dato de estación fresco, cuál está activa hoy.

## Fase 4 — Contexto e histórico (esfuerzo: medio)

- [ ] Precipitación: capa de lluvia acumulada 24/72 h desde el CSV horario de
      INUMET (CKAN, actualización diaria).
- [ ] Vista "caudal vs. normal" (anomalía) como toggle, análoga al mapa USA.
- [ ] Cruce lluvia→creciente: resaltar cuencas con precipitación acumulada
      extrema como **aviso de atención**, nunca como mancha inferida — la
      lluvia no salta directo a mancha; la cadena es lluvia → escorrentía/
      caudal → nivel → mancha (ver AGENTS.md).
- [ ] Persistir cada snapshot del job de Fase 2 para construir series propias
      (Uruguay no publica series de caudal descargables).
- [ ] Mini-gráfico de serie temporal en el popup de estación (con los datos
      acumulados propios + niveles CKAN 2017–2019 donde existan).
- [ ] Capa de represas/embalses (Bonete, Baygorria, Palmar, Salto Grande) con
      datos operativos disponibles.

## Fase 5 — Pulido y alcance extendido (esfuerzo: abierto)

- [ ] Nombres de ríos con jerarquía por zoom (usar `nombre_2` de
      `shp_cursos` / Natural Earth).
- [ ] Buscador de cursos y permalinks por río/estación.
- [ ] Detalle 1:10.000 de IDEuy en zooms altos (solo estética).
- [ ] Pedir a `dinagua.servicios@ambiente.gub.uy` acceso a series/curvas de
      gasto; si llegan, reemplazar la heurística de escala por conversión
      nivel→caudal real.
- [ ] Cobertura costera del modo creciente (`curvas_costas`, 281 k features,
      requiere tiling).
- [ ] Re-conflación de geometría en zonas donde HydroRIVERS diverge de la
      cartografía oficial (auditoría `pipeline/comparar_fidelidad.py`,
      2026-08-20: media 256 m y mediana 156 m dentro de Uruguay, pero 3,3 %
      de puntos a >1 km concentrados en las tierras bajas de la Laguna Merín
      —bañados, bajo Cebollatí/Tacuarí—, el embalse de Rincón del Bonete y
      meandros del alto Río Negro): reemplazar la geometría de esos tramos
      por `shp_cursos` de DINAGUA conservando los atributos de caudal de
      HydroRIVERS.
- [ ] Performance: presupuesto de <3 MB de datos iniciales, tiles por zoom,
      medir en móvil real.

## Riesgos principales

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Frescura heterogénea de DINAGUA (caudales a veces rezagados años) | La capa "en vivo" miente | Usar nivel (casi al día) como señal primaria; umbral de antigüedad; etiqueta "estimado" |
| Endpoints frágiles (TLS roto en ambiente.gub.uy, CARU en IP:8080, HTML scraping) | Pipeline se rompe en silencio | Job tolerante a fallos por fuente + alerta; el mapa degrada a caudal medio |
| Sin curvas de gasto públicas (nivel→caudal) | Escala dinámica es heurística | Documentarlo en la UI; gestionar acceso con DINAGUA (Fase 4) |
| Rendimiento WebGL en móvil con ~14 k tramos | UX pobre | Filtrar por zoom, simplificar geometría, presupuesto de FPS en el spike de Fase 0 |
| Datum de cotas de curvas ≠ cota cero de estaciones | El modo creciente activa manchas equivocadas | Verificación de datum por localidad antes de habilitar la activación automática; hasta entonces, solo escenarios manuales |
| Manchas oficiales solo en ciudades estudiadas | Falsa sensación de "acá no se inunda" fuera de cobertura | Mostrar cobertura explícita (localidades con/sin estudio) y `localidades_amenazas` como señal mínima |
