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

// Velocidad y cola en unidades de pantalla (mercator/s y mercator, fijadas
// por frame según el zoom): si fueran fracciones del tramo, los tramos largos
// separarían la cola en "perlas" y los cortos parpadearían.
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
  float tSpeed = min(uSpeedMerc * (0.25 + 0.75 * aQ) / aLen, 0.9);
  float gapT = min(uGapMerc / aLen, 0.12);
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

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const s = gl.createShader(type)!;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(s) ?? "shader error");
  }
  return s;
}

/**
 * Siembra partículas sobre cada segmento recto de las polilíneas.
 * Cada partícula vive en un segmento y recircula con fract(), así toda la
 * animación corre en el vertex shader sin trabajo por frame en CPU.
 */
function buildParticles(fc: FeatureCollection, spacingMerc: number) {
  const data: number[] = [];
  let qMax = 1;
  for (const f of fc.features) {
    const q = Number(f.properties["DIS_AV_CMS"]) || 0;
    if (q > qMax) qMax = q;
  }
  const logQMax = Math.log10(1 + qMax);

  for (const f of fc.features) {
    const q = Number(f.properties["DIS_AV_CMS"]) || 0;
    const q01 = Math.log10(1 + q) / logQMax;
    const lines =
      f.geometry.type === "LineString"
        ? [f.geometry.coordinates as number[][]]
        : (f.geometry.coordinates as number[][][]);
    for (const line of lines) {
      for (let i = 0; i < line.length - 1; i++) {
        const a = maplibregl.MercatorCoordinate.fromLngLat(
          { lng: line[i][0], lat: line[i][1] }, 0);
        const b = maplibregl.MercatorCoordinate.fromLngLat(
          { lng: line[i + 1][0], lat: line[i + 1][1] }, 0);
        const len = Math.hypot(b.x - a.x, b.y - a.y);
        if (len < spacingMerc * 0.25) continue;
        const n = Math.max(1, Math.floor(len / spacingMerc));
        for (let k = 0; k < n; k++) {
          const phase = Math.random();
          for (let trail = 0; trail < TRAIL_LEN; trail++) {
            data.push(a.x, a.y, b.x, b.y, phase, q01, trail, len);
          }
        }
      }
    }
  }
  return new Float32Array(data);
}

const TRAIL_LEN = 6;
const FLOATS_PER_PARTICLE = 8;

export class FlowLayer implements CustomLayerInterface {
  id = "flow-particles";
  type = "custom" as const;
  renderingMode = "2d" as const;

  private map!: Map;
  private program!: WebGLProgram;
  private buffer!: WebGLBuffer;
  private count = 0;
  private start = performance.now();
  private loc: Record<string, number> = {};
  private uMatrix!: WebGLUniformLocation;
  private uTime!: WebGLUniformLocation;
  private uSize!: WebGLUniformLocation;
  private uSpeedMerc!: WebGLUniformLocation;
  private uGapMerc!: WebGLUniformLocation;

  constructor(private fc: FeatureCollection, private spacingMerc = 3e-5) {}

  particleCount(): number {
    return this.count;
  }

  private visible = true;

  setVisible(v: boolean): void {
    this.visible = v;
    this.map?.triggerRepaint();
  }

  onAdd(map: Map, gl: WebGLRenderingContext): void {
    this.map = map;
    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    this.program = gl.createProgram()!;
    gl.attachShader(this.program, vs);
    gl.attachShader(this.program, fs);
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(this.program) ?? "link error");
    }

    const particles = buildParticles(this.fc, this.spacingMerc);
    this.count = particles.length / FLOATS_PER_PARTICLE;
    this.buffer = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, particles, gl.STATIC_DRAW);

    for (const name of ["aStart", "aEnd", "aPhase", "aQ", "aTrail", "aLen"]) {
      this.loc[name] = gl.getAttribLocation(this.program, name);
    }
    this.uMatrix = gl.getUniformLocation(this.program, "uMatrix")!;
    this.uTime = gl.getUniformLocation(this.program, "uTime")!;
    this.uSize = gl.getUniformLocation(this.program, "uSize")!;
    this.uSpeedMerc = gl.getUniformLocation(this.program, "uSpeedMerc")!;
    this.uGapMerc = gl.getUniformLocation(this.program, "uGapMerc")!;
  }

  render: CustomRenderMethod = (gl, matrix) => {
    if (!this.visible) return;
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uMatrix, false, matrix as Float32Array);
    gl.uniform1f(this.uTime, (performance.now() - this.start) / 1000);
    // ~90 px/s el río más caudaloso y cola de ~3,5 px por eslabón, constantes
    // en pantalla a cualquier zoom.
    const pxPerWorld = 512 * Math.pow(2, this.map.getZoom());
    gl.uniform1f(this.uSpeedMerc, 90 / pxPerWorld);
    gl.uniform1f(this.uGapMerc, 3.5 / pxPerWorld);
    const zoomScale = Math.min(4, Math.pow(1.35, this.map.getZoom() - 6));
    gl.uniform1f(this.uSize, 1.3 * zoomScale * (window.devicePixelRatio || 1));

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
