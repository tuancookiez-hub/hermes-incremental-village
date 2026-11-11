// Shared helpers for the art themes: math, noise, the terrain height field, label art and post-processing.
import {
  Mesh, Group, Object3D, Color, InstancedMesh, CanvasTexture, RepeatWrapping, SRGBColorSpace,
  WebGLRenderTarget, HalfFloatType, Vector2
} from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'

export const CHUNK = 16 // must match engine.CHUNK
export const wx = x => x + 0.5
export const wz = y => y + 0.5
export const clamp01 = n => (n < 0 ? 0 : n > 1 ? 1 : n)
export const smooth = t => t * t * (3 - 2 * t)
export const lerp = (a, b, t) => a + (b - a) * t

// deterministic [0,1) hash from integer coords
export function rnd(x, y, k = 0) {
  let h = (x * 374761393 + y * 668265263 + k * 2147483647) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  h ^= h >>> 16
  return ((h >>> 0) % 100000) / 100000
}

export function noise2(x, y) {
  const xi = Math.floor(x)
  const yi = Math.floor(y)
  const u = smooth(x - xi)
  const v = smooth(y - yi)
  const a = rnd(xi, yi, 11)
  const b = rnd(xi + 1, yi, 11)
  const c = rnd(xi, yi + 1, 11)
  const d = rnd(xi + 1, yi + 1, 11)
  return lerp(lerp(a, b, u), lerp(c, d, u), v)
}

export function fbm(x, y, octaves = 4) {
  let sum = 0
  let amp = 0.5
  let total = 0
  for (let i = 0; i < octaves; i++) {
    sum += noise2(x, y) * amp
    total += amp
    amp *= 0.5
    x = x * 2.03 + 17.1
    y = y * 2.03 + 9.3
  }
  return sum / total
}

function blur(src, w, radius) {
  const tmp = new Float32Array(src.length)
  for (let y = 0; y < w; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0
      for (let k = -radius; k <= radius; k++) s += src[y * w + Math.min(w - 1, Math.max(0, x + k))]
      tmp[y * w + x] = s / (radius * 2 + 1)
    }
  }
  for (let y = 0; y < w; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0
      for (let k = -radius; k <= radius; k++) s += tmp[Math.min(w - 1, Math.max(0, y + k)) * w + x]
      src[y * w + x] = s / (radius * 2 + 1)
    }
  }
}

/** Endless smooth terrain. Each chunk is rasterised from its own tiles plus a border of its
 * neighbours', so chunks built at different times meet without a seam. */
export function createField({ heights, res = 3, relief = 0.1, reliefFreq = 0.5, water = 0, outside = '.', floor = 0.06 }) {
  const PAD = 3
  const rows = new Map() // "cx,cy" -> CHUNK * CHUNK tile characters
  const rasters = new Map()
  const inner = CHUNK * res + 1
  const W = (CHUNK + PAD * 2) * res + 1
  const charAt = (x, y) => {
    const cx = Math.floor(x / CHUNK)
    const cy = Math.floor(y / CHUNK)
    const r = rows.get(`${cx},${cy}`)
    return r ? r[(y - cy * CHUNK) * CHUNK + x - cx * CHUNK] : outside
  }
  const crop = src => {
    const out = new Float32Array(inner * inner)
    for (let j = 0; j < inner; j++) {
      for (let i = 0; i < inner; i++) out[j * inner + i] = src[(j + PAD * res) * W + i + PAD * res]
    }
    return out
  }
  function build(cx, cy) {
    const x0 = cx * CHUNK - PAD
    const y0 = cy * CHUNK - PAD
    const h = new Float32Array(W * W)
    const masks = { '~': new Float32Array(W * W), T: new Float32Array(W * W), b: new Float32Array(W * W), R: new Float32Array(W * W) }
    for (let j = 0; j < W; j++) {
      for (let i = 0; i < W; i++) {
        const px = x0 + i / res
        const py = y0 + j / res
        // warp the lookup so coastlines and forest edges stop following the tile grid
        const ch = charAt(
          Math.floor(px + (fbm(px * 0.62 + 3, py * 0.62, 3) - 0.5) * 1.5),
          Math.floor(py + (fbm(px * 0.62 + 31, py * 0.62 + 7, 3) - 0.5) * 1.5)
        )
        h[j * W + i] = heights[ch] ?? heights[outside]
        if (masks[ch]) masks[ch][j * W + i] = 1
      }
    }
    blur(h, W, Math.max(1, Math.round(res * 0.5)))
    blur(h, W, Math.max(1, Math.round(res * 0.4)))
    for (const m of Object.values(masks)) {
      blur(m, W, Math.max(1, Math.round(res * 0.5)))
      blur(m, W, Math.max(1, Math.round(res * 0.25)))
    }
    const raster = { h: crop(h), masks: {} }
    for (const [ch, m] of Object.entries(masks)) raster.masks[ch] = crop(m)
    for (let j = 0; j < inner; j++) {
      for (let i = 0; i < inner; i++) {
        const k = j * inner + i
        const wet = raster.masks['~'][k]
        const X = cx * CHUNK + i / res
        const Z = cy * CHUNK + j / res
        let v = raster.h[k] + (fbm(X * reliefFreq, Z * reliefFreq, 4) - 0.5) * relief * (1 - wet * 0.8)
        v = lerp(v, Math.max(v, water + floor), smooth(clamp01((0.62 - wet) / 0.32)))
        raster.h[k] = v
      }
    }
    return raster
  }
  let lastX = null
  let lastY = null
  let last = null
  const rasterAt = (cx, cy) => {
    if (cx === lastX && cy === lastY && last) return last
    const key = `${cx},${cy}`
    let r = rasters.get(key)
    if (!r) rasters.set(key, (r = build(cx, cy)))
    lastX = cx
    lastY = cy
    last = r
    return r
  }
  const sample = (pick, X, Z) => {
    const cx = Math.floor(X / CHUNK)
    const cy = Math.floor(Z / CHUNK)
    const arr = pick(rasterAt(cx, cy))
    const fx = Math.min(inner - 1.001, (X - cx * CHUNK) * res)
    const fy = Math.min(inner - 1.001, (Z - cy * CHUNK) * res)
    const ix = Math.floor(fx)
    const iy = Math.floor(fy)
    const u = fx - ix
    const v = fy - iy
    return lerp(lerp(arr[iy * inner + ix], arr[iy * inner + ix + 1], u), lerp(arr[(iy + 1) * inner + ix], arr[(iy + 1) * inner + ix + 1], u), v)
  }
  const heightOf = r => r.h
  const heightAt = (X, Z) => sample(heightOf, X, Z)
  return {
    res, water, charAt, heightAt,
    groundAt: (X, Z) => Math.max(heightAt(X, Z), water + 0.04),
    maskAt: (ch, X, Z) => sample(r => r.masks[ch], X, Z),
    add(land) {
      for (const [key, tiles] of Object.entries(land)) {
        if (rows.has(key)) continue
        rows.set(key, tiles)
        const [cx, cy] = key.split(',').map(Number)
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) rasters.delete(`${cx + dx},${cy + dy}`)
      }
      last = null
    },
    forget(cx, cy) { // the raster is rebuilt from the tiles if anyone comes back
      rasters.delete(`${cx},${cy}`)
      last = null
    }
  }
}

export function lumpy(geometry, amount, freq, seed = 0) {
  const p = geometry.attributes.position
  const n = geometry.attributes.normal
  for (let i = 0; i < p.count; i++) {
    const a = p.getX(i) + p.getZ(i) * 0.7
    const b = p.getY(i) - p.getZ(i) * 0.4
    const d = (fbm(a * freq + seed, b * freq + seed * 0.7, 3) - 0.5) * 2 * amount
    p.setXYZ(i, p.getX(i) + n.getX(i) * d, p.getY(i) + n.getY(i) * d, p.getZ(i) + n.getZ(i) * d)
  }
  geometry.computeVertexNormals()
  return geometry
}

export function part(parent, geometry, material, px = 0, py = 0, pz = 0, sx = 1, sy = sx, sz = sx) {
  const o = new Mesh(geometry, material)
  o.position.set(px, py, pz)
  o.scale.set(sx, sy, sz)
  parent.add(o)
  return o
}

export function pivot(parent, px, py, pz) {
  const g = new Group()
  g.position.set(px, py, pz)
  parent.add(g)
  return g
}

/** Collects instances of one mesh type, then builds a single InstancedMesh. */
export class Batch {
  constructor(geometry, material, opts = {}) {
    this.geometry = geometry
    this.material = material
    this.opts = opts
    this.items = []
    this.dummy = new Object3D()
  }

  add(x, y, z, sx = 1, sy = sx, sz = sx, ry = 0, color = null, rx = 0, rz = 0) {
    this.items.push({ x, y, z, sx, sy, sz, ry, rx, rz, color })
  }

  build(parent) {
    if (!this.items.length) return null
    const mesh = new InstancedMesh(this.geometry, this.material, this.items.length)
    const col = new Color()
    this.items.forEach((it, i) => {
      this.dummy.position.set(it.x, it.y, it.z)
      this.dummy.scale.set(it.sx, it.sy, it.sz)
      this.dummy.rotation.set(it.rx, it.ry, it.rz)
      this.dummy.updateMatrix()
      mesh.setMatrixAt(i, this.dummy.matrix)
      if (it.color !== null) mesh.setColorAt(i, col.set(it.color))
    })
    mesh.castShadow = this.opts.cast ?? true
    mesh.receiveShadow = this.opts.receive ?? true
    parent.add(mesh)
    this.mesh = mesh
    return mesh
  }
}

export function canvas(w, h = w) {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

export function colorTexture(c) {
  const t = new CanvasTexture(c)
  t.colorSpace = SRGBColorSpace
  t.anisotropy = 4
  return t
}

export function dataTexture(c, repeat = 1) {
  const t = new CanvasTexture(c)
  t.wrapS = t.wrapT = RepeatWrapping
  t.repeat.set(repeat, repeat)
  t.anisotropy = 4
  return t
}

/** Name tags, "+2 wood" floats and speech bubbles, in the theme's own lettering. */
export function drawLabel(kind, text, style) {
  const bubble = kind === 'bubble'
  const c = canvas(bubble ? 640 : 256, bubble ? 88 : 64)
  const g = c.getContext('2d')
  g.textAlign = 'center'
  g.textBaseline = 'middle'
  const shape = (x, y, w, h, r) => {
    g.beginPath()
    if (style.rough) {
      const n = 10
      const pts = []
      for (let i = 0; i < n; i++) pts.push([x + (w * i) / (n - 1), y + rnd(i, text.length, 1) * 6])
      for (let i = 0; i < n; i++) pts.push([x + w - (w * i) / (n - 1), y + h - rnd(i, text.length, 2) * 6])
      pts.forEach(([px, py], i) => (i ? g.lineTo(px, py) : g.moveTo(px, py)))
      g.closePath()
    } else {
      g.roundRect(x, y, w, h, r)
    }
  }
  if (bubble) {
    let size = 30
    g.font = `${style.weight ?? ''} ${size}px ${style.font}`
    while (size > 14 && g.measureText(text).width > c.width - 44) {
      size -= 2
      g.font = `${style.weight ?? ''} ${size}px ${style.font}`
    }
    const tw = Math.min(c.width - 8, g.measureText(text).width + 44)
    g.fillStyle = style.bubbleFill
    g.strokeStyle = style.bubbleStroke
    g.lineWidth = 3
    shape((c.width - tw) / 2, 4, tw, c.height - 8, 20)
    g.fill()
    g.stroke()
    g.fillStyle = style.bubbleText
    g.fillText(text, c.width / 2, c.height / 2 + 1)
  } else {
    g.font = `${style.weight ?? 'bold'} 30px ${style.font}`
    const tw = Math.min(c.width - 8, g.measureText(text).width + 28)
    if (style.tagFill) {
      g.fillStyle = style.tagFill
      g.strokeStyle = style.tagStroke
      g.lineWidth = 2
      shape((c.width - tw) / 2, 9, tw, c.height - 18, 10)
      g.fill()
      g.stroke()
    }
    g.fillStyle = style.tagText
    g.fillText(text, c.width / 2, c.height / 2 + 1)
  }
  return colorTexture(c)
}

const FinishShader = {
  uniforms: {
    tDiffuse: { value: null },
    vignette: { value: 0.3 },
    grain: { value: 0.02 },
    time: { value: 0 }
  },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform float vignette, grain, time; varying vec2 vUv;
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec4 c = texture2D(tDiffuse, vUv);
      vec2 d = vUv - 0.5;
      c.rgb *= 1.0 - vignette * smoothstep(0.25, 0.8, length(d) * 1.2);
      c.rgb += (hash(vUv * 917.0 + fract(time)) - 0.5) * grain * c.rgb;
      gl_FragColor = c;
    }`
}

// The ink look: the finished picture redrawn as blue pen on white paper. Tone becomes hatching,
// edges become outlines, and land nobody has seen is left as blank paper.
const InkShader = {
  uniforms: { tDiffuse: { value: null }, res: { value: new Vector2(1, 1) } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
  fragmentShader: `
    uniform sampler2D tDiffuse; uniform vec2 res; varying vec2 vUv;
    float lum(vec2 uv){ return dot(texture2D(tDiffuse, uv).rgb, vec3(0.299, 0.587, 0.114)); }
    float stroke(float v, float width){ return 1.0 - smoothstep(width - 0.12, width + 0.12, abs(fract(v) - 0.5) * 2.0); }
    void main(){
      vec2 px = 1.0 / res;
      // the scene is lit by a day that turns to night; a drawing is not, so the tone is levelled first
      float mean = 0.0;
      for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) mean += lum(vec2(0.2 + 0.3 * float(i), 0.2 + 0.3 * float(j)));
      float gain = clamp(0.62 / max(mean / 9.0, 0.02), 1.0, 6.0);
      vec3 col = texture2D(tDiffuse, vUv).rgb;
      float raw = dot(col, vec3(0.299, 0.587, 0.114));
      float l = clamp(raw * gain, 0.0, 1.0);
      float known = smoothstep(0.004, 0.02, raw);
      float tl = lum(vUv + px * vec2(-1.0, 1.0)), t = lum(vUv + px * vec2(0.0, 1.0)), tr = lum(vUv + px * vec2(1.0, 1.0));
      float ml = lum(vUv + px * vec2(-1.0, 0.0)), mr = lum(vUv + px * vec2(1.0, 0.0));
      float bl = lum(vUv + px * vec2(-1.0, -1.0)), b = lum(vUv + px * vec2(0.0, -1.0)), br = lum(vUv + px * vec2(1.0, -1.0));
      float gx = (tr + 2.0 * mr + br) - (tl + 2.0 * ml + bl);
      float gy = (tl + 2.0 * t + tr) - (bl + 2.0 * b + br);
      float edge = smoothstep(0.09, 0.30, length(vec2(gx, gy)) * gain);
      vec2 fc = gl_FragCoord.xy;
      float pitch = max(6.0, res.y / 150.0);
      // water is drawn as a few long wave lines, never as shade
      float wet = smoothstep(0.0, 0.07, min(col.g, col.b) - col.r * 1.22) * known;
      float wave = stroke((fc.y + sin(fc.x / (pitch * 2.2)) * pitch * 0.55) / (pitch * 2.6), 0.14);
      float dark = 1.0 - smoothstep(0.08, 0.72, l);
      float h1 = stroke((fc.x + fc.y) / pitch, 0.50 * smoothstep(0.34, 0.70, dark));
      float h2 = stroke((fc.x - fc.y) / pitch, 0.55 * smoothstep(0.62, 0.90, dark));
      float h3 = step(0.93, dark);
      float shade = max(h1 * step(0.34, dark), max(h2 * step(0.62, dark), h3));
      float ink = max(edge, mix(shade, wave, wet)) * known;
      gl_FragColor = vec4(mix(vec3(0.992, 0.992, 1.0), vec3(0.090, 0.090, 0.878), clamp(ink, 0.0, 1.0)), 1.0);
    }`
}

/** Multisampled post stack: scene -> theme passes -> vignette and grain -> tone mapping -> ink, if chosen. */
export function makePost(renderer, scene, camera, passes = [], finish = {}) {
  const size = renderer.getDrawingBufferSize(new Vector2())
  const target = new WebGLRenderTarget(size.x || 1, size.y || 1, { type: HalfFloatType, samples: 4 })
  const composer = new EffectComposer(renderer, target)
  composer.addPass(new RenderPass(scene, camera))
  for (const p of passes) composer.addPass(p)
  const finishPass = new ShaderPass(FinishShader)
  finishPass.uniforms.vignette.value = finish.vignette ?? 0.3
  finishPass.uniforms.grain.value = finish.grain ?? 0.02
  composer.addPass(finishPass)
  composer.addPass(new OutputPass())
  const inkPass = new ShaderPass(InkShader)
  inkPass.enabled = false
  inkPass.uniforms.res.value.copy(size)
  composer.addPass(inkPass)
  return {
    setInk(on) {
      inkPass.enabled = !!on
      // a pen drawing has no film grain and no dark corners, and both would be inked as noise
      finishPass.uniforms.grain.value = on ? 0 : finish.grain ?? 0.02
      finishPass.uniforms.vignette.value = on ? 0 : finish.vignette ?? 0.3
    },
    render(tt = 0) {
      finishPass.uniforms.time.value = tt
      composer.render()
    },
    resize(w, h) {
      composer.setPixelRatio(renderer.getPixelRatio())
      composer.setSize(w, h)
      inkPass.uniforms.res.value.copy(renderer.getDrawingBufferSize(new Vector2()))
    },
    dispose() {
      composer.dispose()
      target.dispose()
    }
  }
}
