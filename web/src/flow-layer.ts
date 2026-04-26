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

const VERT = `
attribute vec2 aStart;
attribute vec2 aEnd;
attribute float aPhase;
attribute float aQ;
uniform mat4 uMatrix;
uniform float uTime;
uniform float uSize;
varying float vQ;
void main() {
  float speed = 0.15 + 0.85 * aQ;
  float t = fract(aPhase + uTime * speed);
  vec2 pos = mix(aStart, aEnd, t);
  gl_Position = uMatrix * vec4(pos, 0.0, 1.0);
  gl_PointSize = uSize * (1.0 + 3.5 * aQ);
  vQ = aQ;
}`;

const FRAG = `
precision mediump float;
varying float vQ;
void main() {
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  float alpha = smoothstep(0.5, 0.1, d) * (0.2 + 0.5 * vQ);
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
        const n = Math.max(1, Math.floor(len / spacingMerc));
        for (let k = 0; k < n; k++) {
          data.push(a.x, a.y, b.x, b.y, Math.random(), q01);
        }
      }
    }
  }
  return new Float32Array(data);
}

const FLOATS_PER_PARTICLE = 6;

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

  constructor(private fc: FeatureCollection, private spacingMerc = 3e-5) {}

  particleCount(): number {
    return this.count;
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

    for (const name of ["aStart", "aEnd", "aPhase", "aQ"]) {
      this.loc[name] = gl.getAttribLocation(this.program, name);
    }
    this.uMatrix = gl.getUniformLocation(this.program, "uMatrix")!;
    this.uTime = gl.getUniformLocation(this.program, "uTime")!;
    this.uSize = gl.getUniformLocation(this.program, "uSize")!;
  }

  render: CustomRenderMethod = (gl, matrix) => {
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uMatrix, false, matrix as Float32Array);
    gl.uniform1f(this.uTime, (performance.now() - this.start) / 20000);
    const zoomScale = Math.min(6, Math.pow(1.5, this.map.getZoom() - 6));
    gl.uniform1f(this.uSize, 1.5 * zoomScale * (window.devicePixelRatio || 1));

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

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.drawArrays(gl.POINTS, 0, this.count);
    this.map.triggerRepaint();
  }
}
