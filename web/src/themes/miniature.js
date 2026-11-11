// "Handmade miniature": a clay and felt world, shot like a tabletop model.
import {
  ACESFilmicToneMapping, PCFShadowMap, Color, Group, Mesh, Fog, HemisphereLight, DirectionalLight, PointLight,
  BufferGeometry, Float32BufferAttribute, PlaneGeometry, SphereGeometry, CylinderGeometry, ConeGeometry,
  TorusGeometry, LatheGeometry, Vector2, MeshStandardMaterial, MeshPhysicalMaterial, MeshBasicMaterial, PMREMGenerator, Sprite, SpriteMaterial,
  AdditiveBlending, DoubleSide, Vector3, Matrix4, Points, PointsMaterial, BufferAttribute,
  DataTexture, RedFormat, LinearFilter, RepeatWrapping
} from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { HorizontalTiltShiftShader } from 'three/addons/shaders/HorizontalTiltShiftShader.js'
import { VerticalTiltShiftShader } from 'three/addons/shaders/VerticalTiltShiftShader.js'
import {
  CHUNK, wx, wz, clamp01, smooth, lerp, rnd, fbm, createField, lumpy, part, pivot, Batch,
  canvas, colorTexture, dataTexture, makePost
} from './util.js'

// Wayfarers, as a woodblock print would draw them: a slim figure in a long robe of undyed cloth whose
// hem and cuffs have been dipped in one dye. The dye and one trait (a straw hat, a topknot, a beard and
// staff, long hair, a hood) are all that tell them apart, so each reads from far above.
const DYES = { indigo: 0x24408f, madder: 0xb23a2a, ochre: 0xcf8f1c, celadon: 0x3f8f76, plum: 0x7b3a72, slate: 0x2f5f78 }
const CLOTH = 0xece2cc
const LOOKS = {
  Ash: { skin: 0xe9b98a, hair: 0x2a1c16, dye: 'indigo', style: 'kasa' },
  Bryn: { skin: 0xb97c56, hair: 0x1c1412, dye: 'madder', style: 'knot' },
  Coll: { skin: 0xf0d3bb, hair: 0xeeeae2, dye: 'ochre', style: 'elder' }
}
const SPARE = [
  { skin: 0xd9a57c, hair: 0x231814, dye: 'celadon', style: 'long' },
  { skin: 0xf0cfae, hair: 0x3a2418, dye: 'plum', style: 'hood' },
  { skin: 0xa86e4c, hair: 0x18110f, dye: 'slate', style: 'kasa' },
  { skin: 0xe6bd97, hair: 0x4a2f1c, dye: 'madder', style: 'long' },
  { skin: 0xc48d66, hair: 0x1c1412, dye: 'indigo', style: 'knot' }
]
const FOG_SIDE = 512 // tiles; wider than twice the furthest chunk that can be drawn
const WATER_TILE = 32 // the ripple pattern repeats this often, so the water can follow in steps without jumping
const WATER_SIZE = 1024
const DROP_BEYOND = 170 // chunks past this are thrown away; the longest view is about 133
const DETAIL_WITHIN = 56
const CHUNKS_PER_FRAME = 2
const pick = (list, i) => list[((i % list.length) + list.length) % list.length] // chunk seeds can be negative
const UP = new Vector3(0, 1, 0)
const DIR = new Vector3()
const FOLIAGE = [0x47692f, 0x557a35, 0x66873a, 0x3a5a30, 0x7d8c3c]
const AUTUMN = [0xb5802c, 0xbb5f2a]
const THATCH = [0xc2a254, 0xb49347, 0xd0b265]

// One unbroken cycle: the last stop matches the first, so night runs straight into dawn.
const NIGHT = { sun: 0x7f95e0, si: 0.8, sky: 0x8b9be0, gnd: 0x3a3a55, hi: 0.26, env: 0.1, fog: 0x0e1119 }
const STOPS = [
  { t: 0, ...NIGHT },
  { t: 0.1, sun: 0xffa56e, si: 2.4, sky: 0xffcfae, gnd: 0x5c4436, hi: 0.28, env: 0.13, fog: 0x241a18 },
  { t: 0.2, sun: 0xffd0a0, si: 3.4, sky: 0xffe6cc, gnd: 0x705a40, hi: 0.34, env: 0.16, fog: 0x241f1b },
  { t: 0.45, sun: 0xfff8ec, si: 4.1, sky: 0xeaf1ff, gnd: 0x705a40, hi: 0.38, env: 0.2, fog: 0x25261f },
  { t: 0.68, sun: 0xffcc8a, si: 3.6, sky: 0xffe0c0, gnd: 0x6a5238, hi: 0.32, env: 0.17, fog: 0x261f18 },
  { t: 0.8, sun: 0xff8a4c, si: 2.8, sky: 0xffae86, gnd: 0x5c4436, hi: 0.24, env: 0.12, fog: 0x241813 },
  { t: 0.9, ...NIGHT },
  { t: 1, ...NIGHT }
]
const stopColors = STOPS.map(s => ({ sun: new Color(s.sun), sky: new Color(s.sky), gnd: new Color(s.gnd), fog: new Color(s.fog) }))

function clayBump() {
  const c = canvas(256)
  const g = c.getContext('2d')
  const img = g.createImageData(256, 256)
  for (let y = 0; y < 256; y++) {
    for (let x = 0; x < 256; x++) {
      const a = (Math.sin(x * 0.03) + 1) * 0.5 // wraps closely enough at these scales
      const v = 120 + 110 * fbm(x * 0.05, y * 0.05, 3) + 22 * Math.sin((x + y * 0.4) * 0.9 + a * 4)
      const i = (y * 256 + x) * 4
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v
      img.data[i + 3] = 255
    }
  }
  g.putImageData(img, 0, 0)
  return c
}

function feltBump() {
  const c = canvas(512)
  const g = c.getContext('2d')
  g.fillStyle = '#808080'
  g.fillRect(0, 0, 512, 512)
  for (let i = 0; i < 16000; i++) {
    const x = rnd(i, 1) * 512
    const y = rnd(i, 2) * 512
    const a = rnd(i, 3) * Math.PI * 2
    const l = 5 + rnd(i, 4) * 14
    const v = 60 + rnd(i, 5) * 150 | 0
    g.strokeStyle = `rgba(${v},${v},${v},0.55)`
    g.lineWidth = 0.8 + rnd(i, 6) * 0.9
    g.beginPath()
    g.moveTo(x, y)
    g.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l)
    g.stroke()
  }
  return c
}

function snowDot() {
  const c = canvas(32)
  const g = c.getContext('2d')
  const r = g.createRadialGradient(16, 16, 0, 16, 16, 16)
  r.addColorStop(0, 'rgba(255,255,255,1)')
  r.addColorStop(0.6, 'rgba(255,255,255,0.8)')
  r.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = r
  g.fillRect(0, 0, 32, 32)
  return colorTexture(c)
}

function glowTexture() {
  const c = canvas(128)
  const g = c.getContext('2d')
  const r = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  r.addColorStop(0, 'rgba(255,190,110,0.9)')
  r.addColorStop(0.35, 'rgba(255,130,50,0.32)')
  r.addColorStop(1, 'rgba(255,90,20,0)')
  g.fillStyle = r
  g.fillRect(0, 0, 128, 128)
  return colorTexture(c)
}

export function createMiniature({ renderer, scene, camera }) {
  renderer.toneMapping = ACESFilmicToneMapping
  renderer.toneMappingExposure = 0.84
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = PCFShadowMap

  const owned = new Set()
  // fog of war is painted into every lit material, so trees, rocks and buildings fade with the ground
  // the texture wraps, so it covers endless land: a tile lands at (x mod side, y mod side), and it is
  // repainted around the camera ten times a second. It only has to be wider than the render distance.
  const fogCells = new Uint8Array(FOG_SIDE * FOG_SIDE)
  const fogTex = new DataTexture(fogCells, FOG_SIDE, FOG_SIDE, RedFormat)
  fogTex.minFilter = fogTex.magFilter = LinearFilter
  fogTex.wrapS = fogTex.wrapT = RepeatWrapping
  fogTex.needsUpdate = true
  const fogMap = { value: fogTex }
  const fogSpan = { value: FOG_SIDE }
  const fogDark = { value: new Color(0.006, 0.008, 0.012) } // what unseen land is painted: near black, or paper in the ink look
  const fogInject = shader => {
    shader.uniforms.uHvFog = fogMap
    shader.uniforms.uHvSpan = fogSpan
    shader.uniforms.uHvDark = fogDark
    shader.vertexShader = `varying vec2 vHvFog;\n${shader.vertexShader}`.replace('#include <project_vertex>', `#include <project_vertex>
      vec4 hvFogPos = vec4(transformed, 1.0);
      #ifdef USE_INSTANCING
        hvFogPos = instanceMatrix * hvFogPos;
      #endif
      vHvFog = (modelMatrix * hvFogPos).xz;`)
    shader.fragmentShader = `uniform sampler2D uHvFog;\nuniform float uHvSpan;\nuniform vec3 uHvDark;\nvarying vec2 vHvFog;\n${shader.fragmentShader}`.replace('#include <dithering_fragment>', `#include <dithering_fragment>
      gl_FragColor.rgb = mix(uHvDark, gl_FragColor.rgb, texture2D(uHvFog, vHvFog / uHvSpan).r);`)
  }
  const own = x => {
    owned.add(x)
    if (x.isMeshStandardMaterial) {
      x.onBeforeCompile = fogInject
      x.customProgramCacheKey = () => 'hermes-village-fog2'
    }
    return x
  }
  const terrainOwned = new Set()
  const chunks = new Map() // "cx,cy" -> built chunk
  const wanted = new Map() // chunks to build, nearest first, a few each frame
  let land = null
  let lastStocks = null
  const tileParts = new Map() // "x,y" -> { ch, pieces: [[[batch, index], ...], ...] }; each piece hides as the tile empties
  const piece = (x, y, ch, parts) => {
    const key = `${x},${y}`
    if (!tileParts.has(key)) tileParts.set(key, { ch, pieces: [] })
    tileParts.get(key).pieces.push(parts)
  }

  const pmrem = new PMREMGenerator(renderer)
  const room = new RoomEnvironment()
  const envRT = pmrem.fromScene(room, 0.04)
  room.dispose?.()
  pmrem.dispose()
  scene.environment = envRT.texture
  scene.fog = new Fog(0x24241f, 60, 170)
  scene.background = new Color(0x24241f)

  const hemi = new HemisphereLight(0xeaf1ff, 0x705a40, 0.6)
  const sun = new DirectionalLight(0xfff0d6, 3.4)
  sun.castShadow = true
  sun.shadow.mapSize.set(2048, 2048)
  sun.shadow.radius = 4
  sun.shadow.bias = -0.0005
  sun.shadow.normalBias = 0.025
  Object.assign(sun.shadow.camera, { left: -21, right: 21, top: 21, bottom: -21, near: 2, far: 80 })
  scene.add(hemi, sun, sun.target)
  const fireLight = new PointLight(0xff8f3c, 0, 8, 1.6)
  fireLight.castShadow = false
  fireLight.position.set(0, -10, 0)
  scene.add(fireLight)

  const clayTex = own(dataTexture(clayBump(), 2))
  const feltTex = own(dataTexture(feltBump(), 1))
  const groundFelt = own(dataTexture(feltTex.image, 3)) // per chunk: one repeat is about 5 tiles
  const rippleTex = own(dataTexture(feltTex.image, WATER_SIZE / WATER_TILE))
  const glowTex = own(glowTexture())

  const clay = (color, extra = {}) => own(new MeshStandardMaterial({ color, roughness: 0.72, bumpMap: clayTex, bumpScale: 1.4, ...extra }))
  const felt = (color, extra = {}) => own(new MeshStandardMaterial({ color, roughness: 1, bumpMap: feltTex, bumpScale: 2.6, ...extra }))

  const geo = {
    blob: own(lumpy(new SphereGeometry(1, 14, 10), 0.13, 1.7, 2)),
    blobB: own(lumpy(new SphereGeometry(1, 14, 10), 0.17, 2.3, 9)),
    pebble: own(lumpy(new SphereGeometry(1, 12, 8), 0.26, 1.3, 5)),
    pebbleB: own(lumpy(new SphereGeometry(1, 12, 8), 0.3, 1.1, 14)),
    tier: own(lumpy(new ConeGeometry(1, 1, 12, 4, true), 0.07, 2.4, 3)),
    stick: own(lumpy(new CylinderGeometry(1, 1.15, 1, 7, 3), 0.1, 3, 1)),
    trunk: own(lumpy(new CylinderGeometry(0.72, 1, 1, 8, 3), 0.12, 2.1, 4)),
    tuft: own(new ConeGeometry(1, 1, 5)),
    bead: own(new SphereGeometry(1, 8, 6)),
    egg: own(new SphereGeometry(1, 32, 24)),
    flame: own(lumpy(new ConeGeometry(0.09, 0.42, 8, 3), 0.018, 8, 7))
  }
  geo.tuft.translate(0, 0.5, 0)
  geo.tier.translate(0, 0.5, 0)

  const mat = {
    land: own(new MeshStandardMaterial({ vertexColors: true, roughness: 1, bumpMap: groundFelt, bumpScale: 3 })),
    water: own(new MeshStandardMaterial({ color: 0x5ea69f, roughness: 0.06, metalness: 0, transparent: true, opacity: 0.58, bumpMap: rippleTex, bumpScale: 0.35 })),
    foliage: felt(0xffffff),
    trunk: clay(0x6d4a2d),
    pine: felt(0xffffff, { side: DoubleSide }),
    tuft: felt(0xffffff),
    bead: clay(0xffffff, { roughness: 0.45 }),
    berry: clay(0xbd2a35, { roughness: 0.32 }),
    rock: clay(0xffffff, { roughness: 0.82 }),
    wood: clay(0x8a5f38),
    darkWood: clay(0x5e3e26),
    thatch: felt(0xc2a254),
    thatchB: felt(0xa98a42),
    wall: clay(0xb48a5e),
    hide: felt(0x8a6a45),
    hideDark: felt(0x4a3324),
    strip: clay(0xa8603a),
    stripB: clay(0xd2b078),
    ash: clay(0x3f3a36),
    stone: clay(0x95908a),
    cotton: own(new MeshStandardMaterial({ color: 0xe8e4dc, roughness: 1, bumpMap: feltTex, bumpScale: 4, transparent: true, opacity: 0.85 })),
    flame: own(new MeshBasicMaterial({ color: new Color(0xff7a14).multiplyScalar(2.2) })),
    flameCore: own(new MeshBasicMaterial({ color: new Color(0xffd34a).multiplyScalar(2.6) })),
    eyeGloss: own(new MeshPhysicalMaterial({ color: 0x15131a, roughness: 0.08, clearcoat: 1, clearcoatRoughness: 0.05 })),
    spark: own(new MeshBasicMaterial({ color: 0xffffff })),
    cheek: own(new MeshStandardMaterial({ color: 0xf2a09a, roughness: 0.7 })),
    foot: own(new MeshStandardMaterial({ color: 0x4a3a33, roughness: 0.5 })),
    soil: felt(0x5c4028),
    crop: felt(0x88a83e)
  }

  const tilt = [new ShaderPass(HorizontalTiltShiftShader), new ShaderPass(VerticalTiltShiftShader)]
  tilt.forEach(p => { p.uniforms.r.value = 0.52 })
  const post = makePost(renderer, scene, camera, tilt, { vignette: 0.34, grain: 0.022 })

  // ---- terrain
  const dummyCol = new Color()
  const C = {
    grassA: new Color(0x6c8138), grassB: new Color(0x8b9344), dry: new Color(0xa8944c), forest: new Color(0x41582c),
    rock: new Color(0x8f8676), sand: new Color(0xc2a874), bed: new Color(0x5f8c7e), deep: new Color(0x204a54),
    bare: new Color(0x8f7846)
  }

  function colourTerrain(geometry, field) {
    const p = geometry.attributes.position
    const out = new Float32Array(p.count * 3)
    for (let i = 0; i < p.count; i++) {
      const x = p.getX(i)
      const z = p.getZ(i)
      const h = p.getY(i)
      const n = fbm(x * 0.33 + 40, z * 0.33 + 40, 3)
      dummyCol.copy(C.grassA).lerp(C.grassB, smooth(clamp01((n - 0.32) * 2.6)))
      dummyCol.lerp(C.dry, smooth(clamp01((fbm(x * 0.17, z * 0.17, 2) - 0.56) * 6)) * 0.75)
      dummyCol.lerp(C.bare, smooth(clamp01(1 - Math.hypot(x - wx(land.camp[0]), z - wz(land.camp[1])) / 5.5)) * 0.42 * (0.5 + n))
      dummyCol.lerp(C.forest, clamp01(field.maskAt('T', x, z) * 1.15))
      dummyCol.lerp(C.rock, clamp01(field.maskAt('R', x, z) * 1.3))
      const shore = smooth(clamp01((0.15 - h) / 0.13))
      dummyCol.lerp(C.sand, shore)
      dummyCol.lerp(C.bed, smooth(clamp01((0.02 - h) / 0.05)))
      dummyCol.lerp(C.deep, smooth(clamp01(-h / 0.3)))
      const speck = (rnd(Math.round(x * 3), Math.round(z * 3), 3) - 0.5) * 0.05 // by place, so chunk edges agree
      out[i * 3] = dummyCol.r + speck
      out[i * 3 + 1] = dummyCol.g + speck
      out[i * 3 + 2] = dummyCol.b + speck
    }
    geometry.setAttribute('color', new Float32BufferAttribute(out, 3))
  }

  function plantTree(trees, x, y, k, field) {
    const parts = []
    const add = (batch, ...args) => {
      parts.push([batch, batch.items.length])
      batch.add(...args)
    }
    const ox = (rnd(x, y, 10 + k) - 0.5) * 0.7
    const oz = (rnd(x, y, 20 + k) - 0.5) * 0.7
    const X = wx(x) + ox
    const Z = wz(y) + oz
    const g = field.heightAt(X, Z)
    const size = 0.72 + rnd(x, y, 30 + k) * 0.5
    const hue = rnd(x, y, 35 + k)
    const leaf = hue > 0.93 ? AUTUMN[(hue * 100 | 0) % 2] : FOLIAGE[(hue * 50 | 0) % FOLIAGE.length]
    if (rnd(x, y, 3 + k) > 0.45) {
      add(trees.trunk, X, g + 0.2 * size, Z, 0.09 * size, 0.42 * size, 0.09 * size, rnd(x, y, 5))
      const blobs = 3 + (rnd(x, y, 6 + k) > 0.5 ? 1 : 0)
      for (let b = 0; b < blobs; b++) {
        const a = rnd(x, y, 40 + k * 7 + b) * Math.PI * 2
        const r = b ? 0.17 * size : 0
        const s = (b ? 0.25 : 0.34) * size * (0.9 + rnd(x, y, 50 + b) * 0.3)
        const batch = b % 2 ? trees.blobB : trees.blob
        add(batch, X + Math.cos(a) * r, g + (b ? 0.52 : 0.68) * size, Z + Math.sin(a) * r, s, s * 0.92, s, a, leaf)
      }
    } else {
      add(trees.trunk, X, g + 0.12 * size, Z, 0.06 * size, 0.26 * size, 0.06 * size, 0)
      const col = FOLIAGE[3 + (hue * 20 | 0) % 2]
      for (let t = 0; t < 4; t++) {
        const r = (0.34 - t * 0.065) * size
        add(trees.tier, X, g + (0.16 + t * 0.24) * size, Z, r, 0.4 * size, r, t * 1.3 + hue * 6, col)
      }
    }
    piece(x, y, 'T', parts)
  }

  function groundGeometry(cx, cy, field) {
    const seg = CHUNK * field.res
    const g = new PlaneGeometry(CHUNK, CHUNK, seg, seg)
    g.rotateX(-Math.PI / 2)
    g.translate(cx * CHUNK + CHUNK / 2, 0, cy * CHUNK + CHUNK / 2)
    const p = g.attributes.position
    const n = g.attributes.normal
    const e = 0.12
    for (let i = 0; i < p.count; i++) { // normals from the field, not the mesh, or every chunk edge would show
      const x = p.getX(i)
      const z = p.getZ(i)
      p.setY(i, field.heightAt(x, z))
      const dx = field.heightAt(x - e, z) - field.heightAt(x + e, z)
      const dz = field.heightAt(x, z - e) - field.heightAt(x, z + e)
      const len = Math.hypot(dx, 2 * e, dz)
      n.setXYZ(i, dx / len, (2 * e) / len, dz / len)
    }
    colourTerrain(g, field)
    return g
  }

  function terrain(camp, group) {
    for (const c of [...group.children]) {
      group.remove(c)
      c.traverse?.(o => {
        if (o.isInstancedMesh) o.dispose()
        else if (o.isMesh) o.geometry.dispose()
      })
    }
    terrainOwned.forEach(x => x.dispose())
    terrainOwned.clear()
    const field = createField({
      heights: { '~': -0.34, '.': 0.16, b: 0.17, T: 0.2, R: 0.42 },
      res: 3, relief: 0.13, reliefFreq: 0.42, outside: '.', water: 0
    })
    fogCells.fill(0)
    fogTex.needsUpdate = true
    chunks.clear()
    wanted.clear()
    tileParts.clear()
    lastStocks = null

    const tableGeo = new PlaneGeometry(WATER_SIZE, WATER_SIZE)
    tableGeo.rotateX(-Math.PI / 2)
    terrainOwned.add(tableGeo)
    const table = new Mesh(tableGeo, own(new MeshStandardMaterial({ color: 0x2b2a27, roughness: 0.9 })))
    table.receiveShadow = true
    group.add(table)

    const waterGeo = new PlaneGeometry(WATER_SIZE, WATER_SIZE, 1, 1)
    waterGeo.rotateX(-Math.PI / 2)
    terrainOwned.add(waterGeo)
    const water = new Mesh(waterGeo, mat.water)
    water.receiveShadow = true
    group.add(water)

    land = { field, group, camp, table, water }
    return field
  }

  function showChunk(cx, cy) {
    const key = `${cx},${cy}`
    if (land && !chunks.has(key)) wanted.set(key, { cx, cy, key })
  }

  function buildChunk(cx, cy, key) {
    const { field, group } = land
    const x0 = cx * CHUNK
    const y0 = cy * CHUNK
    const trees = {
      trunk: new Batch(geo.trunk, mat.trunk),
      blob: new Batch(geo.blob, mat.foliage),
      blobB: new Batch(geo.blobB, mat.foliage),
      tier: new Batch(geo.tier, mat.pine)
    }
    const bushes = new Batch(geo.blobB, mat.foliage)
    const berries = new Batch(geo.bead, mat.berry, { cast: false })
    const rocks = new Batch(geo.pebble, mat.rock)
    const rocksB = new Batch(geo.pebbleB, mat.rock)
    const tufts = new Batch(geo.tuft, mat.tuft, { cast: false })
    const beads = new Batch(geo.bead, mat.bead, { cast: false })
    const greys = [0x9b968e, 0x8a8682, 0xa8a196, 0x7f7a74]

    for (let y = y0; y < y0 + CHUNK; y++) {
      for (let x = x0; x < x0 + CHUNK; x++) {
        const ch = field.charAt(x, y)
        if (ch === 'T') {
          const n = 2 + (rnd(x, y, 3) > 0.45 ? 1 : 0)
          for (let k = 0; k < n; k++) plantTree(trees, x, y, k, field)
        } else if (ch === 'b') {
          for (let k = 0; k < 3; k++) {
            const X = wx(x) + (rnd(x, y, 60 + k) - 0.5) * 0.62
            const Z = wz(y) + (rnd(x, y, 70 + k) - 0.5) * 0.62
            const g = field.heightAt(X, Z)
            const s = 0.2 + rnd(x, y, 80 + k) * 0.08
            bushes.add(X, g + s * 0.72, Z, s, s * 0.82, s, rnd(x, y, 85 + k) * 6, pick(FOLIAGE.slice(0, 3), k + x))
            for (let b = 0; b < 8; b++) {
              const a = rnd(x + b, y, 90 + k) * Math.PI * 2
              const e = rnd(x, y + b, 95 + k) * 1.1
              const r = s * 1.03
              piece(x, y, 'b', [[berries, berries.items.length]])
              berries.add(X + Math.cos(a) * Math.cos(e) * r, g + s * 0.72 + Math.sin(e) * r * 0.82, Z + Math.sin(a) * Math.cos(e) * r, 0.033)
            }
          }
        } else if (ch === 'R') {
          const n = 2 + (rnd(x, y, 4) * 3 | 0)
          for (let k = 0; k < n; k++) {
            const X = wx(x) + (rnd(x, y, 100 + k) - 0.5) * 0.8
            const Z = wz(y) + (rnd(x, y, 110 + k) - 0.5) * 0.8
            const s = 0.14 + rnd(x, y, 120 + k) * 0.26
            const b = k % 2 ? rocks : rocksB
            piece(x, y, 'R', [[b, b.items.length]])
            b.add(X, field.heightAt(X, Z) + s * 0.34, Z, s, s * 0.74, s * 0.9, rnd(x, y, 130 + k) * 6, greys[k % 4])
          }
        }
      }
    }

    // ground dressing: felt tufts, wildflowers, reeds and pebbles
    const seedBase = cx * 7919 + cy * 104729
    for (let n = 0; n < 600; n++) {
      const i = seedBase + n
      const X = wx(x0) - 0.5 + rnd(i, 1, 7) * CHUNK
      const Z = wz(y0) - 0.5 + rnd(i, 2, 7) * CHUNK
      const h = field.heightAt(X, Z)
      if (h < 0.07) continue
      const rocky = field.maskAt('R', X, Z)
      if (rocky > 0.45) {
        if (i % 3 === 0) rocks.add(X, h + 0.01, Z, 0.035, 0.024, 0.03, i, pick(greys, i))
        continue
      }
      const reed = h < 0.14
      const s = reed ? 0.024 : 0.02 + rnd(i, 3, 7) * 0.016
      const tall = reed ? 0.24 + rnd(i, 4, 7) * 0.2 : 0.07 + rnd(i, 4, 7) * 0.08
      const col = reed ? 0x7f9446 : pick(FOLIAGE, i)
      for (let b = 0; b < (reed ? 2 : 4); b++) {
        const lean = () => (rnd(i, b + 20, 7) - 0.5) * 0.9
        const ox = (rnd(i, b + 30, 7) - 0.5) * 0.09
        const oz = (rnd(i, b + 40, 7) - 0.5) * 0.09
        tufts.add(X + ox, h - 0.01, Z + oz, s, tall * (0.7 + rnd(i, b + 50, 7) * 0.5), s, i + b, col, lean(), (rnd(i, b + 60, 7) - 0.5) * 0.9)
      }
      if (i % 17 === 0 && !reed) {
        const bloom = pick([0xf3ecd8, 0xe7c04a, 0xd98aa0, 0xf3ecd8], i)
        beads.add(X, h + tall, Z, 0.022, 0.018, 0.022, 0, bloom)
      }
    }
    const chunk = new Group()
    const ground = groundGeometry(cx, cy, field)
    const groundMesh = new Mesh(ground, mat.land)
    groundMesh.receiveShadow = true
    chunk.add(groundMesh)
    for (const b of [trees.trunk, trees.blob, trees.blobB, trees.tier, bushes, berries, rocks, rocksB, tufts, beads]) {
      const mesh = b.build(chunk)
      if (mesh) mesh.userData.full = mesh.instanceMatrix.array.slice()
    }
    group.add(chunk)
    const tiles = []
    for (let y = y0; y < y0 + CHUNK; y++) for (let x = x0; x < x0 + CHUNK; x++) tiles.push(`${x},${y}`)
    const detail = [tufts.mesh, beads.mesh].filter(Boolean)
    chunks.set(key, { chunk, ground, tiles, detail, cx, cy, x: x0 + CHUNK / 2, z: y0 + CHUNK / 2 })
    if (lastStocks) stocks(lastStocks.map, lastStocks.full, tiles)
  }

  function dropChunk(key, rec) {
    land.group.remove(rec.chunk)
    rec.chunk.traverse(o => o.isInstancedMesh && o.dispose())
    rec.ground.dispose()
    rec.tiles.forEach(t => tileParts.delete(t))
    land.field.forget(rec.cx, rec.cy)
    chunks.delete(key)
  }


  // ---- buildings
  const shadows = g => g.traverse(o => {
    if (o.isMesh) {
      o.castShadow = true
      o.receiveShadow = true
    }
  })
  const log = (parent, x0, y0, z0, x1, y1, z1, r = 0.03, m = mat.wood) => {
    const dx = x1 - x0
    const dy = y1 - y0
    const dz = z1 - z0
    const len = Math.hypot(dx, dy, dz)
    const o = part(parent, geo.stick, m, (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, r, len, r)
    o.quaternion.setFromUnitVectors(UP, DIR.set(dx / len, dy / len, dz / len))
    return o
  }

  function building(kind, x, y) {
    const group = new Group()
    const body = new Group()
    group.add(body)
    const flames = []
    let glow = null
    const puffs = []
    if (kind === 'lean_to') {
      log(body, -0.42, 0, 0.3, -0.42, 0.62, 0.3, 0.035)
      log(body, 0.42, 0, 0.3, 0.42, 0.62, 0.3, 0.035)
      log(body, -0.52, 0.6, 0.3, 0.52, 0.6, 0.3, 0.032)
      for (let i = 0; i < 9; i++) {
        const px = -0.42 + i * 0.105
        log(body, px, 0.64, 0.34, px + (rnd(x, y, i) - 0.5) * 0.05, 0.01, -0.46, 0.022, i % 2 ? mat.wood : mat.darkWood)
      }
      for (let r = 0; r < 4; r++) {
        for (let i = 0; i < 7; i++) {
          const f = (r + 0.5) / 4
          const px = -0.42 + i * 0.14 + (r % 2) * 0.05
          const sheaf = part(body, geo.blobB, i % 2 ? mat.thatch : mat.thatchB, px, lerp(0.66, 0.03, f), lerp(0.3, -0.44, f), 0.09, 0.03, 0.17)
          sheaf.rotation.x = -0.68
          sheaf.rotation.z = (rnd(x + i, y, r) - 0.5) * 0.3
        }
      }
      group.rotation.y = (rnd(x, y, 7) - 0.5) * 0.7
    } else if (kind === 'fire_pit') {
      part(body, geo.bead, mat.ash, 0, 0.012, 0, 0.27, 0.02, 0.27)
      for (let i = 0; i < 10; i++) {
        const a = (i / 10) * Math.PI * 2
        const s = 0.07 + rnd(x + i, y, 8) * 0.025
        const r = part(body, i % 2 ? geo.pebble : geo.pebbleB, mat.stone, Math.cos(a) * 0.29, s * 0.55, Math.sin(a) * 0.29, s, s * 0.8, s)
        r.rotation.y = i * 1.7
      }
      for (let i = 0; i < 4; i++) {
        const a = (i / 4) * Math.PI * 2 + 0.3
        log(body, Math.cos(a) * 0.2, 0.02, Math.sin(a) * 0.2, Math.cos(a) * 0.02, 0.24, Math.sin(a) * 0.02, 0.024, mat.darkWood)
      }
      const f1 = part(body, geo.flame, mat.flame, 0, 0.26, 0)
      const f2 = part(body, geo.flame, mat.flame, 0.07, 0.21, -0.05, 0.7, 0.75, 0.7)
      const f3 = part(body, geo.flame, mat.flameCore, -0.02, 0.19, 0.05, 0.55, 0.62, 0.55)
      flames.push(f1, f2, f3)
      glow = new Sprite(own(new SpriteMaterial({ map: glowTex, blending: AdditiveBlending, depthWrite: false, transparent: true })))
      glow.position.y = 0.32
      glow.scale.setScalar(1.8)
      body.add(glow)
      for (let i = 0; i < 6; i++) {
        const p = part(body, geo.blob, mat.cotton, 0, 0.5, 0, 0.08)
        puffs.push(p)
      }
    } else if (kind === 'drying_rack') {
      for (const sx of [-0.42, 0.42]) {
        log(body, sx - 0.1, 0, 0.08, sx, 0.72, 0, 0.026)
        log(body, sx + 0.08, 0, -0.1, sx, 0.72, 0, 0.026)
      }
      log(body, -0.5, 0.7, 0, 0.5, 0.7, 0, 0.024)
      log(body, -0.5, 0.48, 0.02, 0.5, 0.46, 0.02, 0.018)
      for (let i = 0; i < 6; i++) {
        const s = part(body, geo.blob, i % 3 === 1 ? mat.stripB : mat.strip, -0.3 + i * 0.12, 0.54, 0, 0.042, 0.135, 0.012)
        s.rotation.z = (rnd(x, y, 110 + i) - 0.5) * 0.22
      }
      group.rotation.y = (rnd(x, y, 7) - 0.5) * 0.9
    } else if (kind === 'storehouse') {
      part(body, geo.blob, mat.wall, 0, 0.2, 0, 0.42, 0.2, 0.36)
      for (let t = 0; t < 2; t++) {
        const r = 0.54 - t * 0.2
        part(body, geo.tier, t ? mat.thatchB : mat.thatch, 0, 0.3 + t * 0.2, 0, r, 0.34, r * 0.86)
      }
      for (let i = 0; i < 4; i++) {
        const a = -0.9 + i * 0.6
        const pot = part(body, geo.egg, mat.strip, Math.sin(a) * 0.48, 0.1, Math.cos(a) * 0.42, 0.075, 0.1, 0.075)
        pot.rotation.y = i
        part(body, geo.bead, mat.hideDark, Math.sin(a) * 0.48, 0.2, Math.cos(a) * 0.42, 0.04, 0.012, 0.04)
      }
    } else if (kind === 'stone_house') {
      for (let ring = 0; ring < 4; ring++) {
        for (let i = 0; i < 12; i++) {
          const a = (i / 12) * Math.PI * 2 + ring * 0.26
          if (Math.abs(a - Math.PI / 2) < 0.2 && ring < 2) continue
          const r = 0.46 - ring * 0.02
          const s = part(body, i % 2 ? geo.pebble : geo.pebbleB, mat.stone, Math.sin(a) * r, 0.07 + ring * 0.115, Math.cos(a) * r, 0.1, 0.07, 0.09)
          s.rotation.y = a
        }
      }
      for (let t = 0; t < 3; t++) {
        const r = 0.6 - t * 0.14
        part(body, geo.tier, t % 2 ? mat.thatchB : mat.thatch, 0, 0.44 + t * 0.2, 0, r, 0.42, r)
      }
      part(body, geo.blob, mat.hideDark, 0, 0.14, 0.44, 0.1, 0.15, 0.03)
      group.rotation.y = (rnd(x, y, 7) - 0.5) * 1.3
    } else if (kind === 'depot') {
      part(body, geo.egg, mat.soil, 0, 0.01, 0, 0.3, 0.04, 0.28)
      for (let i = 0; i < 3; i++) log(body, -0.12 + i * 0.12, 0.07, -0.16, -0.12 + i * 0.12, 0.07, 0.16, 0.05, i % 2 ? mat.wood : mat.darkWood)
      part(body, geo.egg, mat.thatchB, 0.05, 0.2, 0, 0.11, 0.1, 0.11)
      part(body, geo.bead, mat.hideDark, 0.05, 0.3, 0, 0.07, 0.015, 0.07)
    } else if (kind === 'woodlot') {
      part(body, geo.egg, mat.soil, 0, 0, 0, 0.46, 0.04, 0.44)
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * Math.PI * 2
        const px = Math.cos(a) * 0.27
        const pz = Math.sin(a) * 0.27
        part(body, geo.trunk, mat.trunk, px, 0.06, pz, 0.06, 0.12, 0.06)
        log(body, px, 0.1, pz, px + Math.cos(a) * 0.05, 0.42, pz + Math.sin(a) * 0.05, 0.012, mat.darkWood)
        part(body, geo.blob, mat.foliage, px + Math.cos(a) * 0.05, 0.46, pz + Math.sin(a) * 0.05, 0.075)
      }
    } else if (kind === 'field') {
      part(body, geo.egg, mat.soil, 0, 0.0, 0, 0.48, 0.05, 0.46)
      for (let row = 0; row < 3; row++) {
        for (let i = 0; i < 5; i++) {
          const leaf = part(body, geo.tuft, mat.crop, -0.28 + i * 0.14, 0.02, -0.24 + row * 0.24, 0.028, 0.15 + rnd(x + i, y + row, 3) * 0.08, 0.028)
          leaf.rotation.z = (rnd(x + i, y, row) - 0.5) * 0.5
        }
      }
    } else if (kind === 'hut') {
      const wallGeo = own(lumpy(new CylinderGeometry(0.42, 0.46, 0.46, 18, 3), 0.018, 5, 6))
      part(body, wallGeo, mat.wall, 0, 0.23, 0)
      for (let i = 0; i < 16; i++) {
        const a = (i / 16) * Math.PI * 2
        if (Math.abs(a - Math.PI / 2) < 0.24) continue
        log(body, Math.sin(a) * 0.47, 0, Math.cos(a) * 0.47, Math.sin(a) * 0.43, 0.48, Math.cos(a) * 0.43, 0.018, mat.darkWood)
      }
      for (let t = 0; t < 3; t++) {
        const r = 0.62 - t * 0.15
        const tier = part(body, geo.tier, t % 2 ? mat.thatchB : mat.thatch, 0, 0.42 + t * 0.19, 0, r, 0.44, r)
        tier.rotation.y = t
      }
      part(body, geo.blob, mat.thatch, 0, 1.0, 0, 0.09, 0.07, 0.09)
      const door = part(body, geo.blob, mat.hideDark, 0.0, 0.15, 0.43, 0.11, 0.17, 0.035)
      door.rotation.y = 0
      log(body, -0.13, 0, 0.45, -0.12, 0.33, 0.44, 0.02)
      log(body, 0.13, 0, 0.45, 0.12, 0.33, 0.44, 0.02)
      log(body, -0.16, 0.32, 0.45, 0.16, 0.32, 0.45, 0.02)
      group.rotation.y = (rnd(x, y, 7) - 0.5) * 1.3
    } else {
      part(body, geo.pebble, mat.wood, 0, 0.2, 0, 0.3)
    }
    const scaffold = new Group()
    for (const sx of [-0.48, 0.48]) for (const sz of [-0.48, 0.48]) log(scaffold, sx, 0, sz, sx * 0.94, 0.86, sz * 0.94, 0.022)
    log(scaffold, -0.52, 0.66, 0.47, 0.52, 0.66, 0.47, 0.018)
    log(scaffold, -0.52, 0.66, -0.47, 0.52, 0.66, -0.47, 0.018)
    log(scaffold, 0.47, 0.42, -0.52, 0.47, 0.42, 0.52, 0.018)
    group.add(scaffold)
    shadows(group)
    if (glow) glow.castShadow = false
    puffs.forEach(p => { p.castShadow = false })
    return { group, body, scaffold, flames, kind, x, y, glow, puffs }
  }

  // ---- the camp store: stacked logs, stones and baskets anyone can draw on
  function campStore() {
    const group = new Group()
    part(group, geo.egg, mat.soil, 0, 0.01, 0, 0.5, 0.05, 0.46)
    for (let row = 0; row < 3; row++) {
      for (let i = 0; i < 4 - row; i++) {
        log(group, -0.3 + i * 0.12 + row * 0.06, 0.07 + row * 0.1, -0.24, -0.3 + i * 0.12 + row * 0.06, 0.07 + row * 0.1, 0.14, 0.05, i % 2 ? mat.wood : mat.darkWood)
      }
    }
    for (let i = 0; i < 3; i++) {
      const basket = part(group, geo.egg, mat.thatchB, 0.22 + (i % 2) * 0.1, 0.11, -0.2 + i * 0.2, 0.1, 0.12, 0.1)
      basket.rotation.y = i
      part(group, geo.bead, mat.hideDark, 0.22 + (i % 2) * 0.1, 0.22, -0.2 + i * 0.2, 0.07, 0.015, 0.07)
    }
    shadows(group)
    return group
  }

  // ---- wild animals, in the same soft egg style as the villagers
  const animalMats = { deer: clay(0xa8784c, { roughness: 0.55 }), boar: clay(0x5a4436, { roughness: 0.55 }), pale: clay(0xe6d6bd) }
  function animal(kind) {
    const group = new Group()
    const rig = new Group()
    group.add(rig)
    const coat = animalMats[kind]
    const deer = kind === 'deer'
    const height = deer ? 0.26 : 0.17
    part(rig, geo.egg, coat, 0, height, 0, deer ? 0.13 : 0.16, deer ? 0.12 : 0.14, deer ? 0.21 : 0.23)
    const head = pivot(rig, 0, height + (deer ? 0.13 : 0.03), deer ? 0.19 : 0.2)
    part(head, geo.egg, coat, 0, 0, 0.02, deer ? 0.07 : 0.09, deer ? 0.075 : 0.085, deer ? 0.1 : 0.11)
    for (const sx of [-1, 1]) {
      part(head, geo.bead, mat.eyeGloss, sx * 0.05, 0.03, 0.06, 0.013)
      if (deer) {
        log(head, sx * 0.03, 0.05, -0.02, sx * 0.09, 0.2, -0.04, 0.008, mat.darkWood)
        log(head, sx * 0.065, 0.13, -0.03, sx * 0.13, 0.17, 0.02, 0.006, mat.darkWood)
        part(rig, geo.bead, animalMats.pale, sx * 0.1, height + 0.03, -0.08, 0.016)
      } else {
        const tusk = part(head, geo.tuft, animalMats.pale, sx * 0.055, -0.04, 0.09, 0.012, 0.06, 0.012)
        tusk.rotation.x = 0.3
      }
    }
    const legs = []
    for (const [lx, lz] of [[-0.08, 0.12], [0.08, 0.12], [-0.08, -0.12], [0.08, -0.12]]) {
      const leg = pivot(rig, lx, height - 0.04, lz)
      part(leg, geo.stick, coat, 0, -(height - 0.04) / 2, 0, 0.02, height - 0.04, 0.02)
      legs.push(leg)
    }
    shadows(group)
    return { group, legs }
  }

  function fire(rec, tt, night) {
    if (!rec) {
      fireLight.intensity = 0
      return
    }
    const p = rec.group.position
    fireLight.position.set(p.x, p.y + 0.55, p.z)
    const f = 0.88 + 0.12 * Math.sin(tt * 13) + 0.06 * Math.sin(tt * 31 + 2)
    fireLight.intensity = (4 + 22 * night) * f
    rec.glow.material.opacity = (0.35 + 0.6 * night) * f
    rec.puffs.forEach((m, i) => {
      const age = (tt * 0.22 + i / rec.puffs.length) % 1
      m.position.set(Math.sin(age * 7 + i) * 0.07 + age * 0.22, 0.42 + age * 1.3, Math.cos(age * 5 + i) * 0.05)
      m.scale.setScalar(0.05 + age * 0.12 * (1 - age * 0.35))
    })
  }

  // ---- villagers: chunky clay figures on the same rig the animations drive
  const skinMats = new Map()
  const lookMat = (color, make = clay) => {
    const key = `${color}:${make === clay}`
    if (!skinMats.has(key)) skinMats.set(key, make(color))
    return skinMats.get(key)
  }
  const plainMat = color => lookMat(color, c => own(new MeshStandardMaterial({ color: c, roughness: 0.78 })))
  // cloth that has been dipped: undyed above `to`, full dye below `from`
  const dipped = (geometry, dye, from, to) => {
    const pos = geometry.attributes.position
    const cols = new Float32Array(pos.count * 3)
    const cloth = new Color(CLOTH)
    const deep = new Color(dye)
    const c = new Color()
    for (let i = 0; i < pos.count; i++) {
      c.copy(deep).lerp(cloth, smooth(clamp01((pos.getY(i) - from) / (to - from))))
      cols.set([c.r, c.g, c.b], i * 3)
    }
    geometry.setAttribute('color', new Float32BufferAttribute(cols, 3))
    return own(geometry)
  }
  const ROBE = [[0.166, 0.02], [0.16, 0.07], [0.14, 0.18], [0.112, 0.31], [0.09, 0.415], [0.096, 0.485], [0.103, 0.53], [0.084, 0.575], [0.04, 0.604], [0, 0.61]]
  const robes = new Map()
  const robeFor = dye => {
    if (!robes.has(dye)) {
      const sleeve = new CylinderGeometry(0.03, 0.064, 0.31, 12, 5)
      sleeve.translate(0, -0.155, 0)
      robes.set(dye, {
        body: dipped(new LatheGeometry(ROBE.map(([r, y]) => new Vector2(r, y)), 24), DYES[dye], 0.08, 0.36),
        sleeve: dipped(sleeve, DYES[dye], -0.29, -0.12)
      })
    }
    return robes.get(dye)
  }
  const sashGeo = own(new TorusGeometry(0.094, 0.017, 8, 24))
  sashGeo.rotateX(Math.PI / 2)
  const hatGeo = own(new ConeGeometry(0.215, 0.1, 28, 1))
  const cloth = own(new MeshStandardMaterial({ vertexColors: true, roughness: 0.94, bumpMap: feltTex, bumpScale: 0.5 }))

  function villager(name, index) {
    const look = LOOKS[name] ?? SPARE[index % SPARE.length]
    const skin = plainMat(look.skin)
    const hair = plainMat(look.hair)
    const dye = plainMat(DYES[look.dye])
    const robe = robeFor(look.dye)
    const group = new Group()
    const rig = new Group()
    rig.scale.setScalar(1.12)
    group.add(rig)

    // feet swing from inside the robe, so a step shows at the hem
    const legL = pivot(rig, -0.06, 0.2, 0)
    const legR = pivot(rig, 0.06, 0.2, 0)
    for (const leg of [legL, legR]) part(leg, geo.bead, mat.foot, 0, -0.172, 0.035, 0.04, 0.026, 0.062)

    part(rig, robe.body, cloth, 0, 0, 0, 1, 1, 0.84)
    part(rig, sashGeo, dye, 0, 0.42, 0, 1, 1, 0.84)

    // long sleeves hang from the shoulders and hide the arms; only the hands show
    const armL = pivot(rig, -0.11, 0.538, 0)
    const armR = pivot(rig, 0.11, 0.538, 0)
    const sleeves = [armL, armR].map((arm, i) => {
      const sleeve = pivot(arm, 0, 0, 0)
      sleeve.rotation.z = (i ? 1 : -1) * 0.2
      part(sleeve, robe.sleeve, cloth, 0, 0, 0, 0.72, 1, 1)
      part(sleeve, geo.bead, skin, 0, -0.323, 0.006, 0.026)
      return sleeve
    })
    const tool = pivot(sleeves[1], 0, -0.31, 0.02)
    part(tool, geo.stick, mat.wood, 0, -0.02, 0.03, 0.016, 0.22, 0.016)
    part(tool, geo.pebble, mat.stone, 0, -0.13, 0.055, 0.044, 0.036, 0.07)
    tool.visible = false

    // a small head with two quiet eyes; everything worn on it turns with it
    const head = pivot(rig, 0, 0.705, 0)
    part(head, geo.egg, skin, 0, 0, 0, 0.097, 0.102, 0.095)
    for (const sx of [-1, 1]) {
      const eye = part(head, geo.egg, mat.eyeGloss, sx * 0.037, 0.002, 0.087, 0.0115, 0.018, 0.008)
      eye.rotation.y = sx * 0.4
    }
    if (look.style !== 'hood') part(head, geo.egg, hair, 0, 0.024, -0.016, 0.103, 0.098, 0.102)
    if (look.style === 'kasa') {
      const hat = part(head, hatGeo, mat.thatch, 0, 0.118, -0.012)
      hat.rotation.x = -0.16
      part(head, geo.bead, mat.thatchB, 0, 0.172, -0.02, 0.02, 0.012, 0.02)
      part(head, geo.egg, hair, 0, -0.07, -0.082, 0.04, 0.085, 0.03)
    } else if (look.style === 'knot') {
      part(head, geo.bead, hair, 0, 0.138, -0.03, 0.043, 0.04, 0.043)
      part(head, sashGeo, dye, 0, 0.108, -0.026, 0.32, 0.5, 0.38)
      for (const sx of [-1, 1]) part(head, geo.egg, hair, sx * 0.088, -0.045, 0.02, 0.017, 0.075, 0.026)
    } else if (look.style === 'elder') {
      const beard = part(head, geo.tuft, hair, 0, -0.04, 0.078, 0.05, 0.17, 0.034)
      beard.rotation.x = Math.PI - 0.12
      part(head, geo.bead, hair, 0, 0.12, -0.05, 0.03)
      part(sleeves[0], geo.stick, mat.darkWood, -0.02, -0.2, 0.07, 0.0125, 0.74, 0.0125)
    } else if (look.style === 'long') {
      part(head, geo.egg, hair, 0, -0.11, -0.07, 0.082, 0.18, 0.04)
      part(head, geo.bead, dye, 0, -0.2, -0.085, 0.022)
    } else {
      part(head, geo.egg, dye, 0, 0.014, -0.022, 0.115, 0.116, 0.113)
      const peak = part(head, geo.tuft, dye, 0, 0.1, -0.06, 0.05, 0.09, 0.05)
      peak.rotation.x = -0.7
      part(head, geo.egg, hair, 0, 0.03, 0.03, 0.09, 0.07, 0.07)
    }

    const bundle = new Group()
    bundle.position.set(0, 0.46, -0.16)
    const woodPack = new Group()
    for (let i = 0; i < 3; i++) {
      const l = part(woodPack, geo.stick, i % 2 ? mat.wood : mat.darkWood, 0, -0.035 + i * 0.03, i % 2 ? 0.018 : -0.012, 0.024, 0.34, 0.024)
      l.rotation.z = Math.PI / 2
    }
    const stonePack = new Group()
    part(stonePack, geo.blob, mat.hide, 0, -0.02, 0, 0.1, 0.09, 0.07)
    part(stonePack, geo.pebble, mat.stone, 0, 0.06, 0, 0.066)
    bundle.add(woodPack, stonePack)
    bundle.visible = false
    rig.add(bundle)
    shadows(group)
    return {
      group, rig, legL, legR, armL, armR, head, tool, bundle, labelY: 1.2,
      setCarry(kind) {
        woodPack.visible = kind !== 'stone'
        stonePack.visible = kind === 'stone'
      }
    }
  }

  // ---- light
  function light(dayT, target) {
    const t = clamp01(dayT)
    let i = 0
    while (i < STOPS.length - 2 && t > STOPS[i + 1].t) i++
    const a = STOPS[i]
    const b = STOPS[i + 1]
    const k = clamp01((t - a.t) / (b.t - a.t))
    sun.color.lerpColors(stopColors[i].sun, stopColors[i + 1].sun, k)
    sun.intensity = lerp(a.si, b.si, k)
    hemi.color.lerpColors(stopColors[i].sky, stopColors[i + 1].sky, k)
    hemi.groundColor.lerpColors(stopColors[i].gnd, stopColors[i + 1].gnd, k)
    hemi.intensity = lerp(a.hi, b.hi, k)
    scene.environmentIntensity = lerp(a.env, b.env, k)
    scene.fog.color.lerpColors(stopColors[i].fog, stopColors[i + 1].fog, k)
    scene.background.copy(scene.fog.color)
    // the sun crosses by day; overnight it sweeps back at its lowest, unseen, so nothing jumps at dawn
    const up = clamp01((t - 0.04) / 0.82)
    const az = t >= 0.86 ? lerp(1.25, 0, (t - 0.86) / 0.14) : t < 0.04 ? lerp(0, -1.25, t / 0.04) : -1.25 + 2.5 * up
    const el = 0.26 + 0.86 * Math.sin(Math.PI * up)
    const sx = Math.round(target.x / 4) * 4 // snapped, so shadows don't crawl as the camera drifts
    const sz = Math.round(target.z / 4) * 4
    sun.target.position.set(sx, 0, sz)
    sun.position.set(sx + Math.sin(az) * Math.cos(el) * 40, Math.sin(el) * 40, sz + Math.cos(az) * Math.cos(el) * 40)
    flakes.position.set(target.x, 0, target.z)
    return t < 0.1 ? smooth(1 - t / 0.1) : smooth(clamp01((t - 0.72) / 0.14))
  }

  // ---- what the seasons and the harvest change
  const hidden = new Matrix4().makeScale(0, 0, 0)
  function stocks(map, full, keys = tileParts.keys()) {
    if (!map || !full) return
    lastStocks = { map, full }
    const touched = new Set()
    for (const key of keys) {
      const spot = tileParts.get(key)
      if (!spot || !full[spot.ch]) continue
      const { ch, pieces } = spot
      const keep = Math.ceil((Math.min(full[ch], map[key] ?? 0) / full[ch]) * pieces.length)
      pieces.forEach((parts, n) => {
        for (const [batch, id] of parts) {
          const mesh = batch.mesh
          if (!mesh) continue
          touched.add(mesh)
          const source = n < keep ? mesh.userData.full.subarray(id * 16, id * 16 + 16) : hidden.elements
          mesh.instanceMatrix.array.set(source, id * 16)
        }
      })
    }
    for (const mesh of touched) mesh.instanceMatrix.needsUpdate = true
  }

  function grave(x, z, y) {
    const group = new Group()
    part(group, geo.egg, mat.soil, 0, 0.02, 0, 0.28, 0.09, 0.36)
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2
      part(group, i % 2 ? geo.pebble : geo.pebbleB, mat.stone, Math.cos(a) * 0.26, 0.05, Math.sin(a) * 0.32, 0.055 + (i % 3) * 0.01)
    }
    log(group, 0, 0, -0.2, 0, 0.42, -0.2, 0.018, mat.darkWood)
    log(group, -0.12, 0.3, -0.2, 0.12, 0.3, -0.2, 0.016, mat.darkWood)
    shadows(group)
    group.position.set(x, y, z)
    return group
  }

  const FLAKES = 900
  const flakeSpots = new Float32Array(FLAKES * 3)
  for (let i = 0; i < FLAKES; i++) {
    flakeSpots[i * 3] = (rnd(i, 1, 9) - 0.5) * 30
    flakeSpots[i * 3 + 1] = rnd(i, 2, 9) * 14
    flakeSpots[i * 3 + 2] = (rnd(i, 3, 9) - 0.5) * 30
  }
  const flakeGeo = own(new BufferGeometry())
  flakeGeo.setAttribute('position', new BufferAttribute(flakeSpots, 3))
  const flakes = new Points(flakeGeo, own(new PointsMaterial({ color: 0xffffff, size: 0.15, transparent: true, opacity: 0.95, map: own(snowDot()), depthWrite: false })))
  flakes.frustumCulled = false
  flakes.visible = false
  scene.add(flakes)
  let winterMix = 0
  const frost = new Color(1.32, 1.4, 1.55)
  const plain = new Color(1, 1, 1)
  const chill = new Color(0xcfe0ff)
  const frosted = [mat.foliage, mat.pine, mat.rock, mat.thatch, mat.thatchB].map(m => [m, m.color.clone()])
  function seasonLook(name, dt) {
    winterMix += ((name === 'winter' ? 1 : 0) - winterMix) * (1 - Math.exp(-dt * 1.2))
    // snow settles as a pale cover: lift the shadows on everything outdoors and cool the sun
    mat.land.color.lerpColors(plain, frost, winterMix)
    mat.land.emissive.setRGB(0.62, 0.68, 0.8)
    mat.land.emissiveIntensity = 0.62 * winterMix
    for (const [m, base] of frosted) {
      m.color.lerpColors(base, frost, winterMix * 0.5)
      m.emissive.setRGB(0.6, 0.66, 0.78)
      m.emissiveIntensity = 0.3 * winterMix
    }
    sun.color.lerp(chill, winterMix * 0.55)
    flakes.visible = winterMix > 0.05
    if (flakes.visible) {
      const p = flakeGeo.attributes.position
      for (let i = 0; i < FLAKES; i++) {
        let y = p.getY(i) - dt * (0.9 + rnd(i, 4, 9) * 0.7)
        if (y < 0) y += 14
        p.setY(i, y)
      }
      p.needsUpdate = true
    }
  }

  function fogStart() {
    fogCells.fill(0)
    wanted.clear()
    return fogCells
  }
  function fogEnd() {
    fogTex.needsUpdate = true
  }
  // Render distance, Minecraft style: what is near is drawn, what is further sits out, and what is
  // far away is thrown away and rebuilt from the tiles if anyone comes back.
  const reach = (cam, controls) => 34 + cam.position.distanceTo(controls.target) * 1.1
  const nearest = (a, b) => a.d - b.d

  function tick(tt, dt, cam, controls) {
    const { x, z } = controls.target
    const far = reach(cam, controls)
    for (const [key, c] of chunks) {
      const d = Math.hypot(c.x - x, c.z - z)
      if (d > DROP_BEYOND) dropChunk(key, c)
      else {
        c.chunk.visible = d < far
        for (const mesh of c.detail) mesh.visible = d < DETAIL_WITHIN // grass is thousands of specks at this range
      }
    }
    if (land && wanted.size) {
      const queue = [...wanted.values()].map(c => ({ ...c, d: Math.hypot(c.cx * CHUNK + CHUNK / 2 - x, c.cy * CHUNK + CHUNK / 2 - z) })).sort(nearest)
      for (const c of queue.slice(0, CHUNKS_PER_FRAME)) {
        buildChunk(c.cx, c.cy, c.key)
        wanted.delete(c.key)
      }
    }
    if (land) { // the water and the dark under it go wherever the camera goes
      land.table.position.set(x, -2.2, z)
      land.water.position.set(Math.round(x / WATER_TILE) * WATER_TILE, land.field.water, Math.round(z / WATER_TILE) * WATER_TILE)
    }
    mat.water.opacity = 0.56 + 0.03 * Math.sin(tt * 1.3)
    rippleTex.offset.set(tt * 0.006, tt * 0.004)
  }

  return {
    view: { fov: 30, offset: [12.5, 11.5, 12.5], maxPolar: Math.PI / 2 - 0.16, minDistance: 6, maxDistance: 90 },
    ringColor: 0xfff4dc,
    labels: {
      font: "Georgia, 'Times New Roman', serif", weight: 'bold',
      scale: 0.72, tagFill: 'rgba(247,239,221,0.96)', tagStroke: 'rgba(92,66,40,0.55)', tagText: '#4a3324',
      bubbleFill: 'rgba(250,244,230,0.97)', bubbleStroke: 'rgba(92,66,40,0.5)', bubbleText: '#3a2a1c'
    },
    spread: 1.5,
    terrain,
    building,
    villager,
    fire,
    light,
    tick,
    stocks,
    showChunk,
    reach,
    fogSide: FOG_SIDE,
    fogStart,
    fogEnd,
    grave,
    seasonLook,
    campStore,
    animal,
    render: tt => post.render(tt),
    setInk: on => {
      tilt.forEach(p => { p.enabled = !on })
      if (on) fogDark.value.setRGB(1.4, 1.4, 1.4) // paper, in either drawn look
      else fogDark.value.setRGB(0.006, 0.008, 0.012)
      post.setInk(on)
    },
    resize(w, h) {
      post.resize(w, h)
      tilt[0].uniforms.h.value = 2.4 / w
      tilt[1].uniforms.v.value = 2.4 / h
    },
    dispose() {
      post.dispose()
      tilt.forEach(p => p.dispose?.())
      terrainOwned.forEach(x => x.dispose())
      owned.forEach(x => x.dispose())
      fogTex.dispose()
      envRT.dispose()
      fireLight.dispose?.()
      sun.dispose?.()
      hemi.dispose?.()
    }
  }
}

