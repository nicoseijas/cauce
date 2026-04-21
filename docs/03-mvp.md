# Especificación del MVP (Fase 1)

## Objetivo

Mapa web público de Uruguay con la red hídrica animada según **caudal medio de
largo plazo** (HydroRIVERS). Sin datos en vivo todavía: el MVP valida el
render, el pipeline de geometría y el deploy. La capa dinámica es Fase 2.

## Alcance

### Incluido

1. **Extensión**: territorio uruguayo completo + río Uruguay (ambas márgenes
   visibles) + Río de la Plata como costa.
2. **Red hídrica**: tramos HydroRIVERS con área drenada sobre el umbral
   elegido; atributos `q_medio`, `orden`, `nombre` (donde el join con
   `shp_cursos` lo aporte).
3. **Render**:
   - ancho de línea ∝ log10(1 + q_medio), reescalado por zoom;
   - animación de flujo aguas abajo (partículas o dash offset), velocidad ∝
     log(q_medio);
   - color: rampa única por caudal (la rampa por anomalía queda para Fase 3).
4. **Interacción**: pan/zoom fluidos; hover resalta el curso y muestra
   tooltip con nombre y caudal medio; click fija el tooltip.
5. **UI mínima**: título, leyenda de escala de caudal, atribuciones
   (HydroSHEDS/HydroRIVERS, DINAGUA, basemap), enlace al repo.
6. **Deploy**: sitio publicado en GitHub Pages con build reproducible
   (`npm run build` en Actions + artefactos de datos versionados).

### Excluido (explícitamente)

- Datos en tiempo real, estaciones, lluvia, represas, buscador, modo
  anomalía, series históricas, detalle IDEuy.

## Criterios de aceptación

- [ ] El mapa carga con < 3 MB transferidos y es interactivo en < 3 s en una
      conexión 4G simulada.
- [ ] 60 fps de animación en desktop; ≥ 30 fps en un móvil medio, con al
      menos los ríos principales visibles a zoom país.
- [ ] El Río Negro, el río Uruguay, el Santa Lucía, el Cebollatí y el
      Cuareim son identificables a simple vista por su ancho relativo.
- [ ] Hover sobre cualquier tramo con nombre muestra el nombre correcto
      (validar 15 cursos conocidos a mano).
- [ ] La dirección de la animación es aguas abajo en los 15 cursos validados
      (HydroRIVERS trae la orientación; verificar tras el clip).
- [ ] El build de datos corre de cero (`python build_red.py`) en una máquina
      limpia y produce artefactos idénticos (determinista).
- [ ] URL pública accesible y funcional en Chrome, Firefox y Safari iOS.

## Plan de trabajo sugerido

1. **Spike de render** (primero, es el mayor riesgo): 1.000 tramos hardcoded
   animados en MapLibre custom layer vs. deck.gl → elegir motor.
2. `build_red.py`: clip + filtrado + join de nombres + export.
3. Integración: cargar red real, escala log, estilos por zoom.
4. Hover/tooltip con agrupación de tramos por curso.
5. Leyenda, atribuciones, pulido visual del basemap.
6. Deploy + medición de los criterios de aceptación.

## Datos de validación manual

Cursos para el checklist de nombres/dirección: Río Uruguay, Río Negro, Río
Santa Lucía, Río Cebollatí, Río Cuareim, Río Yí, Río Tacuarembó, Río Queguay,
Río Arapey, Río Olimar, Río San José, Río Daymán, Arroyo Cuñapirú, Río San
Salvador, Río Rosario.
