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
- [x] Scraper WFS propio (`pipeline/wfs.py` + `descargar_capas.py`);
      descargadas: `shp_cursos` (13.678), `V_Catalogo_publica`
      (100 estaciones), `curvas_tr`, `curvas_cri`, `localidades_amenazas`,
      `problemas_drenaje`, cuencas nivel 1/2 y departamentos.
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
- [x] Publicar: repo `nicoseijas/cauce` en GitHub, Pages habilitado con
      origen Actions — https://nicoseijas.github.io/cauce/ (2026-08-21).

Validaciones ejecutadas (criterios de `docs/03-mvp.md`): payload ~495 KB gzip
(presupuesto 3 MB), 60 fps desktop, los 15 cursos de referencia presentes con
nombre, orientación aguas abajo verificada en 4.532/4.532 tramos encadenados.
Pendiente: medición en móvil real.

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
  - [x] API INA `alerta.ina.gob.ar/pub/datos/`: alturas diarias del río
        Uruguay (Salto Grande Abajo, Concordia, Colón, C. del Uruguay) y
        horarias de Nueva Palmira, con niveles oficiales de
        alerta/evacuación de Prefectura en escala local. ✔
    - [ ] Pronóstico INA: `datosProno` funciona (probado con el Paraná)
          pero la serie de Nueva Palmira (26203/calId 433) devuelve "no se
          encontró serie"; resolver apareamiento serie/corrida o consultar
          al INA. Las estaciones CARU vía INA (Paysandú, Fray Bentos,
          Nuevo Berlín) están listadas pero sin datos en la ventana.
  - [x] UTE `CUPubNivCau` (cuenca del río Negro): niveles observados y
        previsión a 7 días de niveles (San Gregorio, Paso de los Toros,
        Mercedes) y de caudales a erogar en Bonete y Palmar; publicación
        diaria ~12:00. El erogado previsto de Palmar escala el río Negro
        como pseudo-estación (declarado "previsto"). ✔
    - Nota: los informes post-operativos de ADME (cota/erogado observados)
      están rotos del lado del servidor (`po_excel.php` con parse error de
      PHP) y rezagan ~8 días; sus datos abiertos son solo MW por central.
  - [x] ANA (Brasil) `telemetriaws1.ana.gov.br`: nivel/caudal cada 15 min en
        Quaraí (río Cuareim) y Passo das Pedras (río Yaguarón); el caudal
        fresco escala esos cursos compartidos. ✔
    - Nota: Jaguarão ciudad (88300040) y Laguna Merín (88045010) figuran
      activas en el inventario pero no transmiten desde hace >11 días;
      recomprobar periódicamente.
  - [x] Martín García (INA, alto estuario frente a Carmelo) con umbrales de
        alerta/evacuación de Prefectura: única referencia costera con feed
        público. ✔
  - [x] Mareógrafos SOHMA (meteo.armada.mil.uy): Punta Lobos (bahía de
        Montevideo, `Est5Armada.php`) y La Paloma (`Est4Armada.php`), nivel
        cada 5 min referido al cero local Ex Wharton. ✔
    - Notas de la auditoría 2026-08: `Est8`–`Est11` responden 501 (parecen
      ser las mareográficas "en desarrollo": Colonia, Piriápolis, Punta del
      Este); el mareógrafo del puerto ANP solo publica meteorología; el
      modelo SMARA del SHN no tiene puntos uruguayos y publica imágenes;
      las tablas de marea SOHMA son astronómicas y excluyen la
      sobreelevación meteorológica. Sin umbrales oficiales de alerta
      costera publicados: los mareógrafos se muestran informativos.
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
- [x] Puntos de `localidades_amenazas` (324 con amenaza > 0), integrados al
      checkbox "Amenaza urbana" con popup de tipos de amenaza.
- [x] Verificación de datum (`pipeline/analizar_datum.py`): los umbrales se
      derivan como `cota_oficial − cota_cero` (datum Wharton). Hallazgo:
      `cota_local` difiere sistemáticamente ~0,9 m de esa derivación en
      varias localidades (referencia local sin documentar) → incertidumbre
      declarada de ±1 m en la UI; confirmar el significado de `cota_local`
      con `dinagua.servicios@ambiente.gub.uy`. 19 localidades con umbrales
      candidatos, ninguno habilitado automáticamente
      (`web/public/data/activacion.json`).
- [x] Compuerta de activación *fail-closed* (2026-08-21): `build_estado.py`
      solo compara niveles de <24 h cuando la localidad tiene
      `auto_habilitada=true`, datum aprobado y relación hidráulica validada.
      Las configuraciones antiguas no habilitan nada por omisión. Resultado
      actual: 19 localidades candidatas, 0 habilitadas automáticamente; los
      escenarios oficiales manuales siguen visibles.
- [ ] (Opcional/avanzado) Estimación HAND con MDT de IDEuy para zonas sin
      estudio oficial, siempre etiquetada como estimación propia. Elección
      de DEM, acondicionamiento y derivación de drenaje según la skill
      `terrain-hydrology`; validar contra eventos históricos completos por
      cuenca (AGENTS.md), con las curvas CRI como verdad de terreno.

**Criterio de salida:** en las ciudades cubiertas por DINAGUA (Durazno,
Treinta y Tres, etc.) el mapa muestra la mancha del escenario elegido y, si
hay dato de estación fresco, cuál está activa hoy.

## Fase 4 — Contexto e histórico (esfuerzo: medio)

- [x] Precipitación: acumulados 24/72 h desde el CSV horario de INUMET,
      integrados al cron (`leer_lluvia_inumet`). Representación **por
      estación** (círculos por intensidad), no por cuenca: el CSV público
      trae solo 7 estaciones y pintar cuencas enteras sobrevendería
      cobertura (AGENTS.md). Coordenadas aproximadas (INUMET no las publica
      con el CSV). Sumadas las 5 estaciones INIA del CKAN (pluviómetro
      diario 09–09 h, La Estanzuela / Las Brujas / Tacuarembó / Salto
      Grande / Treinta y Tres): 12 estaciones de lluvia y 11 cuencas con
      cobertura de aviso.
- [x] Vista "caudal vs. normal" (anomalía): conmutador en la leyenda, rampa
      divergente sobre ln(factor) (bajo ámbar / normal gris / crecida
      verde-agua), tramos sin medición fresca apagados, partículas y glow
      ocultos en este modo. La propagación del factor pasó a ser por nombre
      de curso completo (el `codigo5` de DINAGUA es por sección, no por
      río): 490 tramos escalados por 11 estaciones.
- [x] Cruce lluvia→creciente: subcuenca (nivel 2, `scp2`) de cada estación
      de lluvia resaltada en ámbar punteado como **aviso de atención** cuando
      el acumulado supera 50 mm/24 h o 100 mm/72 h (umbral orientativo),
      nunca como mancha inferida (AGENTS.md). `build_cuencas_lluvia.py`
      exporta solo las 8 cuencas con estación (INUMET + ANA); el aviso
      aparece en el bloque AHORA y el popup explica la cadena
      lluvia → caudal → nivel → mancha.
- [x] Persistir cada snapshot del job de Fase 2 para construir series propias
      (`data/historico/AAAA/MM/DD-HHMM.json`, commiteado por el cron).
- [x] Mini-gráfico de serie temporal en el popup de estación
      (`pipeline/build_series.py` consolida los snapshots en `series.json`,
      ventana de 45 días; el sparkline aparece con ≥3 observaciones).
      Pendiente: sumar los niveles CKAN 2017–2019 donde existan.
- [x] Capa de represas/embalses (Bonete, Baygorria, Palmar, Salto Grande):
      marcador propio con popup operativo — Salto Grande con erogado en vivo,
      desglose turbinado/vertido (nuevo en `estado_actual.json`) y
      mini-serie; Bonete/Palmar con erogado y cota máxima prevista (UTE);
      Baygorria declarado sin datos públicos.

## Fase 5 — Pulido y alcance extendido (esfuerzo: abierto)

- [x] Nombres de ríos con jerarquía por zoom (glyphs autoalojados, guía
      fusionada por curso y generalizada; sin hidrónimos genéricos). También:
      nombres de departamentos y capitales (Natural Earth). ✔
- [x] Permalinks por estación (2026-08-27, paso 1 del Roadmap V2): identidad
      canónica `<organismo>-<id de origen>` y slug legible asignados en
      `pipeline/identidad.py` y exigidos por el esquema del estado; enrutado
      por History API con `404.html` de rebote; el `estacion_id` redirige al
      slug vigente. Verificado en Chrome sobre un servidor que emula el
      comportamiento de GitHub Pages. ✔
- [ ] Permalinks por río; requiere antes la entidad de río (Fase 5G del V2).
- [x] Buscador global (2026-08-27, paso 2 del Roadmap V2): índice propio en
      `pipeline/build_buscador.py` con estaciones, cursos, localidades,
      departamentos y represas; coincidencia sin diacríticos, agrupada por
      tipo y con carga diferida. Verificado en Chrome. ✔
- [x] Página de estación v1 (2026-08-27, paso 3 del Roadmap V2): panel lateral
      con identidad, estado actual, interpretación separada de la observación,
      gráfico con huecos explícitos, umbrales de la fuente, calidad y
      procedencia leída del catálogo publicado; CSV por estación. El popup del
      mapa pasa a ser un paso intermedio con «Ver estación →». Verificado en
      Chrome. ✔
- [ ] Contexto histórico de la estación: depende de publicar 2017–2019
      (paso 4 del V2); hoy el bloque declara por qué no puede responder.
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

## Fase 6 — Validación y rigor científico (esfuerzo: alto)

Objetivo: pasar de "infraestructura de datos abierta" a producto con error
declarado. Sale de la auditoría de 2026-08-21 (bloque B); los ítems de
lenguaje y descargo de responsabilidad del bloque A ya están resueltos.

- [x] Puerta de seguridad pública: estado global vencido a las 6 h, factores
      descartados a las 48 h, activación descartada a las 24 h, fecha real de
      Salto Grande, cobertura evaluada/configurada visible y estado por fuente
      con última observación. La UI distingue observado, pronosticado y
      estimado; nunca convierte falta de datos en «ninguna mancha superada».

- [x] Validación retrospectiva de la activación de manchas contra `curvas_cri`
      (82 polígonos, `fecha_evento` de 1941 a 2025-07-03).
      **El bloqueo se levantó (2026-08-21):** DINAGUA publica en CKAN las
      lecturas horarias de nivel de 2017, 2018 y 2019
      (`ambiente-dinagua-mediciones-de-nivel-AAAA`, odc-uy, ~50 MB por año),
      que es la serie histórica de las estaciones uruguayas que el WFS no
      sirve. `pipeline/build_validacion_activacion.py` publica un informe
      reproducible con hashes de los tres CSV, partición por evento completo y
      subcuenca, cobertura, criterios de completitud y bloqueos. Nunca divide
      aleatoriamente lecturas de un mismo evento. Resultado 2017–2019: 10
      eventos registrados, 5 sin cobertura y 5 con hidrograma completo:
  - **4 aciertos y 1 fallo** sobre 5 eventos con umbral y serie. Aciertos:
    Paysandú 2019-01-23 (pico 8,43 m → TR10), Florida 2019-06-16 (10,03 →
    TR10), Aguas Corrientes 2019-06-17 (11,48 → TR9999) y Santa Lucía
    2019-06-18 (11,48 → TR100). Los cinco hidrogramas evaluados se verificaron
    físicamente coherentes (ascenso, pico y recesión).
  - **Fallo estructural en 25 de Agosto (FD-2DA):** su único umbral utilizable
    es el de creciente extrema (14,22 m), así que el pico real de 11,48 m no
    activó nada. El sitio solo puede anunciar el escenario extremo para esa
    localidad, o ninguno.
  - **Magnitud sobreestimada en Aguas Corrientes (CA-ACS):** anunció creciente
    extrema para una crecida ordinaria porque sus umbrales de TR100 y de CMP
    están a **0,23 m** uno del otro, cuatro veces menos que la incertidumbre
    declarada de ±1 m.
  - Sin cobertura evaluable: 5 de los 10 eventos. Salto ya no se asocia al
    piezómetro «Club Remeros Salto (Sa1)»: mide el acuífero Guaraní y no es una
    estación de agua superficial. Juan Lacaze queda bloqueada porque sus
    curvas mezclan mecanismo costero y pluvial sin separarlos.
  - Dictamen: **0 de 19 localidades habilitables**. Hay 15 casos fluviales,
    2 costeros/estuarinos, 1 pluvial urbano y 1 mixto; 17 tienen estación
    superficial y 14 coinciden además con el curso. Todos carecen de datum y
    relación hidráulica completamente validados; el registro CRI tampoco
    aporta negativos exhaustivos.
- [ ] Actuar sobre los hallazgos de la validación:
  - 19 de los 27 pares de umbrales consecutivos están a menos de 2 m, o sea
    dentro de ±1 m en ambos. El caso extremo es Constitución: TR10 = 3,31 m,
    TR100 = 3,45 m y CMP = 3,93 m, los tres escenarios en 62 cm. Colapsar los
    umbrales indistinguibles en uno solo en vez de nombrar un período de
    retorno que la incertidumbre no sostiene.
  - Activaciones recurrentes en estaciones estuarinas, estables entre años y
    sin evento registrado: Carmelo 6–9 % de los días, Juan Lacaze 3–5 %,
    Nueva Palmira 0–6 %, La Charqueada 4 %. Ahí el nivel lo mueven la marea y
    la sudestada, no el caudal. Son cota superior de falsa alarma, no falsas
    alarmas confirmadas: el registro CRI es incompleto.
  - `curvas_cri` como capa de verificación no basta para medir falsa alarma.
    Para eso hace falta un registro de eventos negativo, que no existe.
- [x] Control de calidad en el pipeline en vivo, no solo en el análisis
      (2026-08-21). Cada nivel/caudal conserva el valor original y publica
      estado, códigos, controles aplicados y última referencia aceptada. Los
      valores futuros/no finitos/fuera de rango se rechazan; los cambios de
      nivel >1 m en ≤2 h quedan dudosos. Ninguno alimenta factores ni
      activaciones, y `build_series.py` los excluye de la serie visual sin
      borrarlos de los snapshots. La UI muestra cobertura e incidencias. La
      validación encontró que Santa Lucía R-11 —la estación que alimenta tres
      de las 19 localidades con umbral— cambió su marco de referencia dos
      veces en catorce meses: **+12,91 m el 2018-12-16** y **−9,40 m el
      2019-02-22**, con una deriva a valores negativos entre medio. Un cambio
      así deja los umbrales desfasados en metros sin que nada avise, y el
      pipeline toma el último valor tal cual. Otras anomalías del mismo
      barrido sobre las 80 estaciones de 2019: Paso Barrancas con 84 lecturas
      entre 370 y 590 m, y Paso Andrés Pérez con escalones de hasta +12 m.
      Nota metodológica: corregir un escalón desplazando el tramo previo
      **inventa activaciones** (produjo 42 espurias en diciembre de 2018 antes
      de detectarse); el tramo con otro marco hay que descartarlo.
- [x] Contrato reproducible para científicos (2026-08-21): catálogo legible
      por máquinas de los 16 productos, fuente/licencia/clasificación y
      limitaciones por recurso, CRS horizontal y referencia vertical
      explícitos, esquemas JSON del estado v3 y de la validación retrospectiva,
      lockfiles, hashes SHA-256 y CI que detecta deriva, JSON no estricto y
      coordenadas fuera de CRS84. La unión a subcuencas corrige de forma
      explícita el CRS erróneo de la capa WFS (declara EPSG:4326 pero entrega
      coordenadas UTM 21S) y conserva ambos metadatos en el informe.
- [ ] Migrar la telemetría ANA al nuevo HidroWebService autenticado. El
      servicio SOAP usado hoy tenía fin de soporte anunciado para 2026-06-30;
      aún responde, pero constituye un punto único de falla sin continuidad
      garantizada para Cuareim y Yaguarón.
- [x] Climatología nacional en lugar de la media modelada de HydroRIVERS
      (`DIS_AV_CMS` viene de WaterGAP con clima 1971–2000). **Hecho
      (2026-08-21).** Fuente: *Regionalización de estadísticas de caudales* de
      DINAGUA (actualización octubre 2025), cuya **Tabla 1** da el caudal
      específico medio mensual, cuatrimestral y anual (L/s/km²) de las 48
      subcuencas de nivel 2, período 1980–2010, del balance hídrico de
      PLANAGUA revisado en 2025 y contrastado contra la red hidrométrica.
      <https://www.gub.uy/ministerio-ambiente/politicas-y-gestion/publicaciones-hidrologia>
  - La Tabla 1 está en el PDF como imagen: transcrita a
    `data/referencia/caudal_especifico_dinagua.csv`. Las 48 filas se validaron
    contra la redundancia interna de la propia tabla (cada cuatrimestre es la
    media de sus meses y el anual la media de los cuatrimestres); las cuatro
    filas que no cierran exactas difieren ≤0,08, que es el redondeo a un
    decimal de la fuente. La fila 15 se verificó dígito por dígito.
  - `pipeline/build_climatologia.py` asigna a cada tramo su subcuenca de nivel
    2, deriva el área incremental de la topología de HydroRIVERS y acumula
    aguas abajo, como pide el estudio: `Q = Σ (área incremental × q)`. Emite
    `data/processed/climatologia.json` y escribe `q_medio_uy` en la red.
    `build_estaciones.py` lo usa como `q_medio` (88 de 101 estaciones) y el
    frontend lo prefiere para el ancho y para el factor.
  - **Magnitud de la corrección**, sobre 3.877 de 4.585 tramos: la razón entre
    la media vieja y la nueva tiene mediana **1,27**, con p10 0,88 y p90 1,80.
    HydroRIVERS **sobrestimaba más de 1,5×** en el 29 % de los tramos y
    subestimaba por debajo de 0,9× en el 11 %. Por río: San Salvador 1,97×,
    San José 1,81×, Santa Lucía 1,65×, Yí 1,54×, Olimar 1,33×, Queguay 1,28×,
    Cebollatí 1,26×, Arapey 1,07×, Tacuarembó 0,97×, Negro 0,94×. El error
    estaba concentrado en el sur y el suroeste y **subdeclaraba la anomalía**
    justo donde vive más gente.
  - Las subcuencas más secas del país son el litoral suroeste —Río de la Plata
    entre el río Uruguay y el San Juan (5,9 L/s/km²), entre el San Juan y el
    Rosario (6,7), el propio río San Juan (7,0) y el Rosario (9,3)— y los
    tramos bajos del Santa Lucía (8,9 a 9,6). Las más húmedas son del norte:
    Cuareim 19,6, Arapey Grande 18,6 y Tacuarembó 18,4.
  - **Qué queda fuera y por qué:** la Tabla 1 solo describe territorio
    uruguayo (sus 48 filas suman 177.168 km², y los polígonos `cod_pais=URU`
    de la capa de cuencas suman 176.031). Los cursos cuya cuenca entra al país
    ya formada conservan HydroRIVERS y quedan marcados: río Uruguay, Cuareim,
    Yaguarón y Daymán. El corte se hace por cobertura: si el área acumulada
    dentro del país cae por debajo del 80 % del `UPLAND_SKM` del tramo, no se
    publica valor nacional.
  - Dos trampas de los datos, ya resueltas en el script: la capa de cuencas del
    WFS declara EPSG:4326 pero emite UTM 21S (se reusa `leer_wfs_geojson`), y
    trae un polígono `A_B` de 209.288 km² rotulado «RÍO CUAREIM» que
    contaminaba el join hasta que se restringió la capa a `cod_pais=URU`.
  - Pendiente: los valores absolutos no están validados contra caudales
    medidos. La Tabla 1 sale de un balance hídrico, no de aforos directos, y
    no hay serie pública de caudal para contrastarla.
- [ ] Registro de inundaciones observadas, para cerrar el lazo observación →
      activación. **Relevamiento 2026-08-21: no hay fuente uruguaya
      estructurada y automatizable de extensión de inundación observada.**
  - `curvas_cri` es el registro oficial retrospectivo (DINAGUA, Fuerza Aérea,
    CECOED, intendencias, SINAE, CTM Salto Grande), con latencia de meses a
    años.
  - SINAE publica en catalogodatos.gub.uy solo incendios (focos MIRA y áreas
    quemadas). Los evacuados y desplazados salen como texto de noticia durante
    el evento; su listado no acepta filtro por palabra clave.
  - INUMET expone avisos en JSON (`https://www.inumet.gub.uy/tiempo/avisos`:
    `date`, `due_date`, `title`, `description`, `active`), pero es aviso
    meteorológico sin geometría, no inundación observada.
  - GDACS no reporta eventos de Uruguay: su umbral es escala de desastre mayor.
  - **Vía resuelta (2026-08-21): Copernicus GFM por STAC, sin autenticación.**
    El token de 5 h aplica solo a la REST API `api.gfm.eodc.eu/v2/`, que es
    innecesaria. Verificado con `curl`: `https://stac.eodc.eu/api/v1/search`
    `?collections=GFM&bbox=-58.5,-35.0,-53.0,-30.0&datetime=...` devuelve 200
    sin cabecera de autorización (64 ítems en los últimos 7 días sobre
    Uruguay, el más reciente del mismo día), y el COG referenciado acepta
    range read anónimo (206, `image/tiff; application=geotiff`).
  - Cobertura sobre Uruguay: 9 tiles Equi7 `SA020M`. Revisita mediana de 1 día
    y 52 de los últimos 60 días con dato; latencia mediana de 4,2 h entre
    sensado y publicación. Los tiles del oeste y norte —Salto, Paysandú,
    Artigas, Río Negro— rondan 1–2 días; el peor es el de la costa atlántica
    sur (Rocha), con mediana de 9 días.
  - Constelación confirmada por el campo `parent` de los ítems: en 60 días,
    250 de Sentinel-1C, 218 de 1D y 31 de 1A, y estos últimos todos anteriores
    al 2026-06-28. S1D aparece por primera vez el 2026-06-11.
  - Detalle de formato que condiciona la implementación: el asset
    `ensemble_flood_extent` apunta a la variante Equi7, comprimida con **ZSTD**,
    que el `zlib` de la stdlib no descomprime (llega en Python 3.14). Hay una
    variante WGS84 ya reproyectada, en **LZW**, cuya URL está dentro del asset
    `tilejson`: es la que conviene, y hay que leerla de ahí en vez de armarla.
  - El COG trae overviews encadenados dentro de los primeros 64 KB. El tercer
    nivel (~176 m) reduce los bloques a decodificar unas 40 veces y el
    remuestreo es *nearest*, o sea que los valores siguen siendo `{0, 1, 255}`
    sin promediar. Alcanza de sobra para una capa superpuesta al mapa de ríos.
  - EODC además corre un **TiTiler público** en `titiler.services.eodc.eu` con
    `access-control-allow-origin: *`, así que el navegador puede pedirle los
    tiles directo y no hace falta procesar ráster en el cron. Dos trampas: el
    `tilejson` devuelve las URLs con esquema `http://` y GitHub Pages las
    bloquea por contenido mixto, y `data.eodc.eu` no manda cabeceras CORS
    (responde 405 al preflight), o sea que leer el COG desde el navegador con
    una librería cliente no funciona: solo vía TiTiler.
  - El **WMS-T de GFM no existe hoy**: el único host referenciado en el bundle
    JS del portal oficial (`geoserver.gfm.geoville.com`) presenta un
    certificado autofirmado y, saltándolo, devuelve 404.
  - **NASA como respaldo, no como primaria.** Los GeoTIFF `F1/F2/F3` se bajan
    anónimos (verificado: 206); los `.hdf`/`.h5` redirigen a Earthdata (303).
    El token de Earthdata dura 60 días, así que como secret exigiría rotación
    bimestral. El producto VIIRS vigente es `VCDWD_L3`, colección 5200 v002;
    MODIS sigue en paralelo como `MCDWD_L3` c61. El tile de Uruguay es
    `h12v12` en ambos y es el único.
  - El motivo de fondo para no elegir el óptico: medido sobre el recuadro de
    Uruguay, MODIS F1 dio 58,7 % de píxeles sin dato el día 233 y **99,95 % el
    día 230**; VIIRS dio 99,78 % el día 232. Un producto "diario" que casi
    siempre devuelve "sin observación" rinde menos que un radar cada 1–2 días.
  - Arquitectura propuesta: manifiesto chico commiteado por el cron (por tile:
    id de ítem, fecha de adquisición, satélite y URL del COG) que el frontend
    convierte en una capa ráster vía TiTiler, más un GeoJSON grillado generado
    desde el overview de ~176 m para que el mapa degrade con dignidad si EODC
    se cae. Hay que distinguir "sin agua" de "sin observación": el 255 es
    información y va por celda.
  - Riesgos anotados: el `v1` de la API de GFM ya está muerto y el WMS caído
    sin que el portal se entere, así que conviene fallar ruidosamente si el
    STAC devuelve cero ítems en vez de publicar un mapa vacío; y si migran la
    variante WGS de LZW a ZSTD, el decodificador de stdlib se rompe.
  - Cuidado con un detalle del STAC: `flooded_pixels` y `floodable_pixels`
    parecen ser agregados **por escena y no por tile** (dos tiles distintos de
    la misma escena traen valores idénticos). Usarlos para el aviso por cuenca
    contaría de más.
  - Sin verificar: la duración real del token de GFM (no hay cuenta), que un
    token de Earthdata autentique efectivamente la descarga, y si el acceso
    anónimo a los `.tif` de NASA es contractual o accidental —funciona hoy,
    pero la portada de `nrt3` dice que hay que loguearse.
- [ ] Umbrales de lluvia con humedad antecedente y tamaño de cuenca: hoy son
      fijos (50 mm/24 h, 100 mm/72 h) y se aplican igual a la ventana móvil de
      INUMET y al día pluviométrico 09–09 h de INIA.
- [ ] Versionado citable del archivo histórico (DOI o release etiquetado). La
      cita sugerida ya está en el README y en el "Acerca de"; falta el
      identificador estable.

## Riesgos principales

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Frescura heterogénea de DINAGUA (caudales a veces rezagados años) | La capa "en vivo" miente | Usar nivel (casi al día) como señal primaria; umbral de antigüedad; etiqueta "estimado" |
| Endpoints frágiles (TLS roto en ambiente.gub.uy, CARU en IP:8080, HTML scraping) | Pipeline se rompe en silencio | Job tolerante a fallos por fuente + alerta; el mapa degrada a caudal medio |
| Sin curvas de gasto públicas (nivel→caudal) | Escala dinámica es heurística | Documentarlo en la UI; gestionar acceso con DINAGUA (Fase 4) |
| Rendimiento WebGL en móvil con ~14 k tramos | UX pobre | Filtrar por zoom, simplificar geometría, presupuesto de FPS en el spike de Fase 0 |
| Datum de cotas de curvas ≠ cota cero de estaciones | El modo creciente activa manchas equivocadas | Verificación de datum por localidad antes de habilitar la activación automática; hasta entonces, solo escenarios manuales |
| Manchas oficiales solo en ciudades estudiadas | Falsa sensación de "acá no se inunda" fuera de cobertura | Mostrar cobertura explícita (localidades con/sin estudio) y `localidades_amenazas` como señal mínima |
