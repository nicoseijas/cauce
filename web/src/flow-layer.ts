import maplibregl, {
  CustomLayerInterface,
  CustomRenderMethod,
  Map,
} from "maplibre-gl";

type FeatureCollection = {
  features: {
    geometry: { type: string; coordinates: number[][] | number[][][] };
    properties: Record<string, unknown>;
  }[];
};

// La animación corre en el vertex shader. Cada partícula vive en una cuerda
// recta; las cuerdas se re-muestrean con largo constante EN PANTALLA cada vez
// que cambia el zoom, para que la velocidad sea uniforme en rectas y curvas
// (con cuerdas por vértice, las curvas —vértices densos— quedaban congeladas
// por el tope anti-parpadeo y las rectas corrían a velocidad plena).
const VERT = `
attribute vec2 aStart;
attribute vec2 aEnd;
attribute float aPhase;
attribute float aQ;
attribute float aTrail;
attribute float aLen;
uniform mat4 uMatrix;
uniform float uTime;
uniform float uSize;
uniform float uSpeedMerc;
uniform float uGapMerc;
varying float vQ;
varying float vFade;
void main() {
  float tSpeed = uSpeedMerc * (0.25 + 0.75 * aQ) / aLen;
  float gapT = min(uGapMerc / aLen, 0.15);
  float t = fract(aPhase + uTime * tSpeed - aTrail * gapT);
  vec2 pos = mix(aStart, aEnd, t);
  gl_Position = uMatrix * vec4(pos, 0.0, 1.0);
  vFade = 1.0 - aTrail / 7.0;
  gl_PointSize = uSize * (0.5 + 2.2 * aQ) * (0.35 + 0.65 * vFade);
  vQ = aQ;
}`;

const FRAG = `
precision mediump float;
varying float vQ;
varying float vFade;
void main() {
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  float alpha = smoothstep(0.5, 0.1, d) * (0.15 + 0.5 * vQ) * vFade * vFade;
  vec3 color = mix(vec3(0.35, 0.65, 0.95), vec3(0.75, 0.95, 1.0), vQ);
  gl_FragColor = vec4(color, alpha);
}`;

const TRAIL_LEN = 6;
const FLOATS_PER_PARTICLE = 8;
// 8 px: sagita p90 <= 1,4 px en todo el rango de zoom (auditoría 2026-08-20);
// con 26 px las partículas se desviaban hasta 2,5 semianchos del río en z9
const CHORD_PX = 8;
const SPACING_PX = 3;
const MAX_PARTICULAS = 120_000;
const ZOOM_CULLING = 7.5;

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(s) ?? "shader error");
  }
  return s;
}

type Polilinea = {
  xs: Float64Array;
  ys: Float64Array;
  acum: Float64Array;
  largo: number;
  q01: number;
  bbox: [number, number, number, number];
};

function prepararPolilineas(fc: FeatureCollection): Polilinea[] {
  let qMax = 1;
  for (const f of fc.features) {
    const q = Number(f.properties["DIS_AV_CMS"]) || 0;
    if (q > qMax) qMax = q;
  }
  const logQMax = Math.log10(1 + qMax);

  const polis: Polilinea[] = [];
  for (const f of fc.features) {
    const q = Number(f.properties["DIS_AV_CMS"]) || 0;
    const q01 = Math.log10(1 + q) / logQMax;
    const lines =
      f.geometry.type === "LineString"
        ? [f.geometry.coordinates as number[][]]
        : (f.geometry.coordinates as number[][][]);
    for (const line of lines) {
      if (line.length < 2) continue;
      const xs = new Float64Array(line.length);
      const ys = new Float64Array(line.length);
      const acum = new Float64Array(line.length);
      let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
      for (let i = 0; i < line.length; i++) {
        const m = maplibregl.MercatorCoordinate.fromLngLat(
          { lng: line[i][0], lat: line[i][1] }, 0);
        xs[i] = m.x;
        ys[i] = m.y;
        if (m.x < minx) minx = m.x;
        if (m.x > maxx) maxx = m.x;
        if (m.y < miny) miny = m.y;
        if (m.y > maxy) maxy = m.y;
        acum[i] = i === 0 ? 0 : acum[i - 1] + Math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]);
      }
      polis.push({ xs, ys, acum, largo: acum[line.length - 1],
                   q01, bbox: [minx, miny, maxx, maxy] });
    }
  }
  return polis;
}

function puntoEn(p: Polilinea, d: number): [number, number] {
  const acum = p.acum;
  let lo = 0, hi = acum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (acum[mid] < d) lo = mid + 1;
    else hi = mid;
  }
  const i = Math.max(1, lo);
  const seg = acum[i] - acum[i - 1];
  const t = seg > 0 ? (d - acum[i - 1]) / seg : 0;
  return [p.xs[i - 1] + (p.xs[i] - p.xs[i - 1]) * t,
          p.ys[i - 1] + (p.ys[i] - p.ys[i - 1]) * t];
}

export class FlowLayer implements CustomLayerInterface {
  id = "flow-particles";
  type = "custom" as const;
  renderingMode = "2d" as const;

  private map!: Map;
  private gl!: WebGLRenderingContext;
  private program!: WebGLProgram;
  private buffer!: WebGLBuffer;
  private count = 0;
  private start = performance.now();
  private loc: Record<string, number> = {};
  private uniforms: Record<string, WebGLUniformLocation> = {};
  private polis: Polilinea[] = [];
  private visible = true;
  private ultimoZoom = -99;
  private ultimoPad: [number, number, number, number] | null = null;

  constructor(private fc: FeatureCollection) {}

  particleCount(): number {
    return this.count;
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.map?.triggerRepaint();
  }

  onAdd(map: Map, gl: WebGLRenderingContext): void {
    this.map = map;
    this.gl = gl;
    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    this.program = gl.createProgram()!;
    gl.attachShader(this.program, vs);
    gl.attachShader(this.program, fs);
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(this.program) ?? "link error");
    }
    for (const name of ["aStart", "aEnd", "aPhase", "aQ", "aTrail", "aLen"]) {
      this.loc[name] = gl.getAttribLocation(this.program, name);
    }
    for (const name of ["uMatrix", "uTime", "uSize", "uSpeedMerc", "uGapMerc"]) {
      this.uniforms[name] = gl.getUniformLocation(this.program, name)!;
    }
    this.buffer = gl.createBuffer()!;
    this.polis = prepararPolilineas(this.fc);
    this.reseed();
    map.on("moveend", this.onMoveEnd);
  }

  onRemove(): void {
    this.map.off("moveend", this.onMoveEnd);
  }

  private onMoveEnd = (): void => {
    const z = this.map.getZoom();
    const fueraDePad = this.ultimoPad && z >= ZOOM_CULLING
      ? !this.vistaDentroDe(this.ultimoPad)
      : false;
    if (Math.abs(z - this.ultimoZoom) > 0.4 || fueraDePad) this.reseed();
  };

  private vistaDentroDe(pad: [number, number, number, number]): boolean {
    const b = this.map.getBounds();
    const sw = maplibregl.MercatorCoordinate.fromLngLat(b.getSouthWest(), 0);
    const ne = maplibregl.MercatorCoordinate.fromLngLat(b.getNorthEast(), 0);
    return sw.x >= pad[0] && ne.y >= pad[1] && ne.x <= pad[2] && sw.y <= pad[3];
  }

  private reseed(): void {
    const z = this.map.getZoom();
    const ppw = 512 * Math.pow(2, z);
    const chord = CHORD_PX / ppw;
    const spacing = SPACING_PX / ppw;

    let pad: [number, number, number, number] | null = null;
    if (z >= ZOOM_CULLING) {
      const b = this.map.getBounds();
      const sw = maplibregl.MercatorCoordinate.fromLngLat(b.getSouthWest(), 0);
      const ne = maplibregl.MercatorCoordinate.fromLngLat(b.getNorthEast(), 0);
      const dx = ne.x - sw.x, dy = sw.y - ne.y;
      pad = [sw.x - dx, ne.y - dy, ne.x + dx, sw.y + dy];
    }

    const data: number[] = [];
    let particulas = 0;
    for (const p of this.polis) {
      if (pad && (p.bbox[2] < pad[0] || p.bbox[0] > pad[2] ||
                  p.bbox[3] < pad[1] || p.bbox[1] > pad[3])) continue;
      const nChords = Math.max(1, Math.round(p.largo / chord));
      const largoChord = p.largo / nChords;
      const porChord = Math.max(1, Math.round(largoChord / spacing));
      for (let c = 0; c < nChords; c++) {
        const [ax, ay] = puntoEn(p, c * largoChord);
        const [bx, by] = puntoEn(p, (c + 1) * largoChord);
        const len = Math.hypot(bx - ax, by - ay);
        if (len <= 0) continue;
        for (let k = 0; k < porChord; k++) {
          const phase = Math.random();
          for (let trail = 0; trail < TRAIL_LEN; trail++) {
            data.push(ax, ay, bx, by, phase, p.q01, trail, len);
          }
          if (++particulas >= MAX_PARTICULAS) break;
        }
        if (particulas >= MAX_PARTICULAS) break;
      }
      if (particulas >= MAX_PARTICULAS) break;
    }

    this.count = data.length / FLOATS_PER_PARTICLE;
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
    this.ultimoZoom = z;
    this.ultimoPad = pad;
    this.map.triggerRepaint();
  }

  render: CustomRenderMethod = (gl, matrix) => {
    if (!this.visible || this.count === 0) return;
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uniforms.uMatrix, false, matrix as Float32Array);
    gl.uniform1f(this.uniforms.uTime, (performance.now() - this.start) / 1000);
    // ~90 px/s el río más caudaloso, constante en pantalla a cualquier zoom
    const ppw = 512 * Math.pow(2, this.map.getZoom());
    gl.uniform1f(this.uniforms.uSpeedMerc, 90 / ppw);
    gl.uniform1f(this.uniforms.uGapMerc, 3.5 / ppw);
    const zoomScale = Math.min(4, Math.pow(1.35, this.map.getZoom() - 6));
    gl.uniform1f(this.uniforms.uSize, 1.3 * zoomScale * (window.devicePixelRatio || 1));

    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const stride = FLOATS_PER_PARTICLE * 4;
    gl.enableVertexAttribArray(this.loc.aStart);
    gl.vertexAttribPointer(this.loc.aStart, 2, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(this.loc.aEnd);
    gl.vertexAttribPointer(this.loc.aEnd, 2, gl.FLOAT, false, stride, 8);
    gl.enableVertexAttribArray(this.loc.aPhase);
    gl.vertexAttribPointer(this.loc.aPhase, 1, gl.FLOAT, false, stride, 16);
    gl.enableVertexAttribArray(this.loc.aQ);
    gl.vertexAttribPointer(this.loc.aQ, 1, gl.FLOAT, false, stride, 20);
    gl.enableVertexAttribArray(this.loc.aTrail);
    gl.vertexAttribPointer(this.loc.aTrail, 1, gl.FLOAT, false, stride, 24);
    gl.enableVertexAttribArray(this.loc.aLen);
    gl.vertexAttribPointer(this.loc.aLen, 1, gl.FLOAT, false, stride, 28);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.drawArrays(gl.POINTS, 0, this.count);
    this.map.triggerRepaint();
  }
}
