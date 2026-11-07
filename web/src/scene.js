// three.js scene for the village.
// createScene(container) -> { update(world), setPlayback(world, getClock), select(name|null), dispose() }
// getClock() returns { slot, dayT }: the render loop drives every villager and building from playback.js.
import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Sprite, SpriteMaterial,
  BufferGeometry, Vector3, Vector2, LineLoop, LineBasicMaterial, Raycaster
} from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { poseAt, idlePose, buildStateAt } from './playback.js'
import { CHUNK, wx, wz, clamp01, smooth, lerp, drawLabel } from './themes/util.js'
import { createMiniature } from './themes/miniature.js'

const VISION = 4 // Chebyshev radius
const BLEND_MS = 500
const SPREAD = { Ash: [-0.24, -0.1], Bryn: [0.24, -0.1], Coll: [0, 0.2] }
const BUILD_SPOT = new Vector2(0.5, 0.4) // where a builder stands relative to the site centre
const wrapAngle = a => Math.atan2(Math.sin(a), Math.cos(a))
const trunc = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

export function createScene(container) {
  const renderer = new WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'high-performance' })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75))
  renderer.domElement.style.display = 'block'
  container.appendChild(renderer.domElement)

  const scene = new Scene()
  const camera = new PerspectiveCamera(40, 1, 0.1, 250)
  const controls = new OrbitControls(camera, renderer.domElement)
  const theme = createMiniature({ renderer, scene, camera })
  const view = theme.view
  camera.fov = view.fov
  camera.position.set(view.offset[0], view.offset[1], view.offset[2])
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.maxPolarAngle = view.maxPolar
  controls.minDistance = view.minDistance
  controls.maxDistance = view.maxDistance
  controls.target.set(0, 0.3, 0)
  controls.update()

  const lineMat = new LineBasicMaterial({ color: theme.ringColor, transparent: true, opacity: 0.7, depthTest: false })

  // ---- ref-counted label textures, so changing speech never leaks canvases
  const texCache = new Map() // key -> { tex, n }
  function makeSprite(kind, text, mul = 1) {
    const key = `${kind}|${text}`
    let e = texCache.get(key)
    if (!e) {
      e = { tex: drawLabel(kind, text, theme.labels), n: 0 }
      texCache.set(key, e)
    }
    e.n++
    const s = new Sprite(new SpriteMaterial({ map: e.tex, depthTest: false, transparent: true }))
    if (kind === 'bubble') s.scale.set((640 / 230) * mul, (88 / 230) * mul, 1)
    else s.scale.set(1.6 * mul, 0.4 * mul, 1)
    s.renderOrder = 10
    s.raycast = () => {}
    s.userData.texKey = key
    return s
  }
  function disposeSprite(s) {
    if (!s) return
    s.parent?.remove(s)
    s.material.dispose()
    const e = texCache.get(s.userData.texKey)
    if (e && --e.n <= 0) {
      e.tex.dispose()
      texCache.delete(s.userData.texKey)
    }
  }

  // ---- terrain: chunks arrive as the land is seen; a new village starts it over
  const terrain = new Group()
  scene.add(terrain)
  let landId = null
  let landRev = null
  let field = null

  const buildings = new Map() // "kind@x,y" -> record
  let fireSpot = null
  // ---- fog of war: unknown land is dark, explored land is dim, and what villagers can see now is clear.
  // The day is resolved in advance, so tiles it will reveal stay dark until someone actually walks there.
  const fogChunks = new Map() // "cx,cy" -> { seen, vis, level } for every tile of that chunk
  const lit = [] // chunks someone can see into right now
  let fogRev = null
  let fogClock = 1
  const fogChunk = (cx, cy) => {
    const key = `${cx},${cy}`
    let rec = fogChunks.get(key)
    if (!rec) {
      const cells = CHUNK * CHUNK
      rec = { cx, cy, seen: new Uint8Array(cells), vis: new Uint8Array(cells), level: new Float32Array(cells), any: 0 }
      fogChunks.set(key, rec)
    }
    return rec
  }
  const cellOf = (x, y) => (y & (CHUNK - 1)) * CHUNK + (x & (CHUNK - 1))
  const isLit = (x, y) => fogChunks.get(`${x >> 4},${y >> 4}`)?.vis[cellOf(x, y)] === 1
  function syncExplored(w) {
    const view = w.land_view
    if (view.rev === fogRev) return
    fogRev = view.rev
    for (const rec of fogChunks.values()) {
      rec.seen.fill(0)
      rec.any = 0
    }
    for (const [key, mask] of Object.entries(view.seen)) {
      const [cx, cy] = key.split(',').map(Number)
      const rec = fogChunk(cx, cy)
      for (let i = 0; i < mask.length; i++) {
        if (mask[i] === '1') {
          rec.seen[i] = 1
          rec.any++
        }
      }
    }
    for (const key of w.current?.revealed ?? []) {
      const [x, y] = key.split(',').map(Number)
      const rec = fogChunk(x >> 4, y >> 4)
      const i = cellOf(x, y)
      if (rec.seen[i]) {
        rec.seen[i] = 0
        rec.any--
      }
    }
    fogClock = 1
  }
  function syncFog(dt) {
    if (!field) return
    fogClock += dt
    if (fogClock < 0.1) return
    const step = 1 - Math.exp(-fogClock * 5)
    fogClock = 0
    const reach = world?.vision ?? VISION
    for (const rec of lit) rec.vis.fill(0)
    lit.length = 0
    for (const vi of world?.villagers ?? []) {
      const v = villagers.get(vi.name)
      if (!v || !v.group.visible) continue
      const cx = Math.floor(v.pos.x)
      const cy = Math.floor(v.pos.z)
      for (let y = cy - reach; y <= cy + reach; y++) {
        for (let x = cx - reach; x <= cx + reach; x++) {
          const rec = fogChunk(x >> 4, y >> 4)
          const i = cellOf(x, y)
          rec.vis[i] = 1
          if (!rec.seen[i]) {
            rec.seen[i] = 1
            rec.any++
          }
          if (!lit.includes(rec)) lit.push(rec)
        }
      }
    }
    const far = theme.reach(camera, controls) + CHUNK
    const { x: tx, z: tz } = controls.target
    const cells = theme.fogStart()
    const side = theme.fogSide
    const wrap = side - 1
    for (const rec of fogChunks.values()) {
      const x0 = rec.cx * CHUNK
      const y0 = rec.cy * CHUNK
      if (Math.hypot(x0 + CHUNK / 2 - tx, y0 + CHUNK / 2 - tz) > far) continue
      if (rec.any) theme.showChunk(rec.cx, rec.cy)
      for (let i = 0; i < rec.level.length; i++) {
        const goal = rec.vis[i] ? 1 : rec.seen[i] ? 0.6 : 0 // unknown land shows nothing at all
        rec.level[i] += (goal - rec.level[i]) * step
        const y = y0 + (i >> 4)
        const x = x0 + (i & (CHUNK - 1))
        cells[(y & wrap) * side + (x & wrap)] = rec.level[i] * 255
      }
    }
    theme.fogEnd()
  }

  let storeGroup = null
  let framed = false
  function syncStore(w) {
    if (!w.store_at || !field) return
    if (!storeGroup) {
      storeGroup = theme.campStore()
      scene.add(storeGroup)
    }
    const x = wx(w.store_at[0])
    const z = wz(w.store_at[1])
    storeGroup.position.set(x, field.groundAt(x, z), z)
    if (!framed) { // start the camera on the camp, wherever it is on the map
      framed = true
      controls.target.set(x, 0.3, z)
      camera.position.set(x + view.offset[0], view.offset[1], z + view.offset[2])
      controls.update()
    }
  }

  // ---- animals appear only once a villager has seen where they are
  const herdBeasts = new Map() // "kind:n" -> { group, legs, pos, yaw }
  function syncAnimals(dt, tt) {
    const want = new Set()
    const herds = world?.resources?.herds ?? []
    const taken = {}
    for (const h of herds) {
      for (let i = 0; i < h.count; i++) {
        const n = (taken[h.kind] = (taken[h.kind] ?? 0) + 1)
        const key = `${h.kind}:${n}`
        want.add(key)
        let b = herdBeasts.get(key)
        const a = i * 2.4
        const r = 0.28 + i * 0.17
        const tx = wx(h.x) + Math.cos(a) * r
        const tz = wz(h.y) + Math.sin(a) * r
        if (!b) {
          b = { ...theme.animal(h.kind), x: tx, z: tz, yaw: a }
          b.group.position.set(tx, 0, tz)
          scene.add(b.group)
          herdBeasts.set(key, b)
        }
        const dx = tx - b.x
        const dz = tz - b.z
        const moving = Math.hypot(dx, dz) > 0.04
        const step = 1 - Math.exp(-dt * 0.9)
        b.x += dx * step
        b.z += dz * step
        if (moving) b.yaw = Math.atan2(dx, dz)
        b.group.rotation.y = b.yaw
        b.group.position.set(b.x, field.groundAt(b.x, b.z), b.z)
        b.group.visible = isLit(h.x, h.y)
        b.legs.forEach((leg, j) => { leg.rotation.x = moving ? Math.sin(tt * 9 + j * 2) * 0.5 : 0 })
      }
    }
    for (const [key, b] of herdBeasts) {
      if (!want.has(key)) {
        scene.remove(b.group)
        herdBeasts.delete(key)
      }
    }
  }

  const graves = new Map() // name -> grave group; appears the evening someone dies
  function syncGraves(slot, spd) {
    const today = world?.current?.day
    const want = new Set()
    for (const d of world?.dead ?? []) {
      if (d.day === today && slot < spd) continue
      want.add(d.name)
      if (!graves.has(d.name)) {
        const x = wx(d.x) + 0.25
        const z = wz(d.y) - 0.25
        const g = theme.grave(x, z, field.groundAt(x, z))
        scene.add(g)
        graves.set(d.name, g)
      }
    }
    for (const [name, g] of graves) {
      if (!want.has(name)) {
        scene.remove(g)
        graves.delete(name)
      }
    }
  }

  function syncBuildings(states, tt, night) {
    const want = new Set()
    fireSpot = null
    for (const b of states) {
      if (b.progress <= 0) continue
      const key = `${b.kind}@${b.x},${b.y}`
      want.add(key)
      let rec = buildings.get(key)
      if (!rec) {
        rec = theme.building(b.kind, b.x, b.y)
        rec.group.position.set(wx(b.x), field.groundAt(wx(b.x), wz(b.y)), wz(b.y))
        scene.add(rec.group)
        buildings.set(key, rec)
      }
      const p = smooth(clamp01(b.progress))
      const done = b.progress >= 1
      rec.body.scale.set(lerp(0.7, 1, p), lerp(0.06, 1, p), lerp(0.7, 1, p))
      rec.scaffold.visible = !done
      if (done && rec.kind === 'fire_pit') {
        fireSpot = rec
        const f = 0.85 + 0.15 * Math.sin(tt * 13 + 1) + 0.08 * Math.sin(tt * 29)
        rec.flames.forEach((m, i) => {
          const base = m.userData.base ?? (m.userData.base = m.scale.clone())
          m.scale.set(base.x * (1 - 0.12 * i), base.y * f * (1 + 0.25 * Math.sin(tt * (9 + 3 * i) + i)), base.z * (1 - 0.12 * i))
        })
      }
    }
    for (const [key, rec] of buildings) {
      if (!want.has(key)) {
        scene.remove(rec.group)
        buildings.delete(key)
      }
    }
    theme.fire(fireSpot, tt, night)
  }

  // ---- villagers: articulated low-poly bodies
  const villagers = new Map() // name -> record
  const floats = [] // rising "+2 wood" sprites
  let selected = null
  let hovered = null
  let colorIdx = 0

  function makeVillager(name) {
    const { group, rig, legL, legR, armL, armR, head, tool, bundle, setCarry, labelY } = theme.villager(name, colorIdx++)
    group.userData.name = name
    const label = makeSprite('label', name, theme.labels.scale ?? 1)
    label.position.y = labelY
    group.add(label)

    const ringGeo = new BufferGeometry().setFromPoints([
      new Vector3(-VISION - 0.5, 0, -VISION - 0.5), new Vector3(VISION + 0.5, 0, -VISION - 0.5),
      new Vector3(VISION + 0.5, 0, VISION + 0.5), new Vector3(-VISION - 0.5, 0, VISION + 0.5)
    ])
    const ring = new LineLoop(ringGeo, lineMat)
    ring.visible = false
    ring.raycast = () => {}
    scene.add(ring) // world-space outline, positioned each frame
    scene.add(group)
    return {
      group, rig, legL, legR, armL, armR, head, tool, bundle, setCarry, labelY, label, ring, ringGeo,
      status: null, statusKey: null,
      pos: new Vector3(), blendFrom: new Vector3(), blendT0: -1e9, gy: 0.3, yaw: 0, init: false,
      doneKey: undefined, off: 0,
      cur: { aL: 0, aR: 0, lL: 0, lR: 0, headY: 0, drop: 0, lean: 0, bob: 0 }
    }
  }
  function disposeVillager(v) {
    scene.remove(v.group)
    scene.remove(v.ring)
    v.ringGeo.dispose()
    disposeSprite(v.status)
    disposeSprite(v.label)
  }
  function syncVillagers(world) {
    const seen = new Set()
    for (const vi of world.villagers ?? []) {
      seen.add(vi.name)
      if (!villagers.has(vi.name)) villagers.set(vi.name, makeVillager(vi.name))
    }
    for (const [name, v] of villagers) {
      if (!seen.has(name)) {
        disposeVillager(v)
        villagers.delete(name)
      }
    }
  }

  function setStatus(v, key) {
    if (key === v.statusKey) return
    disposeSprite(v.status)
    v.status = null
    v.statusKey = key
    if (!key) return
    const i = key.indexOf('|')
    const kind = key.slice(0, i)
    const s = makeSprite(kind, key.slice(i + 1), kind === 'bubble' ? 0.8 : 0.66)
    s.position.y = v.labelY + (kind === 'bubble' ? 0.34 : 0.27)
    v.group.add(s)
    v.status = s
  }

  function spawnFloat(text, x, y, z) {
    const s = makeSprite('label', text, 0.7)
    scene.add(s)
    floats.push({ s, t0: performance.now(), x, y, z })
  }

  // ---- world + clock
  let world = null
  let getClock = null
  let playDay = null
  function update(w) {
    if (!w?.land_view) return
    if (w.land_id !== landId) {
      landId = w.land_id
      landRev = null
      fogChunks.clear()
      lit.length = 0
      fogRev = null
      framed = false
      field = theme.terrain(w.camp, terrain)
      for (const rec of buildings.values()) scene.remove(rec.group)
      buildings.clear()
    }
    world = w
    if (w.land_view.rev !== landRev) {
      landRev = w.land_view.rev
      field.add(w.land_view.land)
      theme.stocks(w.land_view.stocks, w.stock_full)
    }
    syncVillagers(w)
    syncExplored(w)
    syncStore(w)
  }
  function setPlayback(w, clockFn) {
    const day = w?.current?.day ?? null
    if (playDay !== null && day !== playDay) {
      // a new day arrived (council or skip): glide villagers to their new places instead of snapping
      const now = performance.now()
      for (const v of villagers.values()) {
        v.blendFrom.copy(v.pos)
        v.blendT0 = now
        v.doneKey = undefined
      }
    }
    playDay = day
    if (clockFn) getClock = clockFn
    update(w)
  }

  // ---- camera follow: clicking a card focuses and follows until deselected or the user drags
  let following = false
  let watching = true // default view drifts with the group until the user takes the camera
  const goal = new Vector3()
  const delta = new Vector3()
  function select(name) {
    selected = name && villagers.has(name) ? name : null
    following = !!selected
    if (!selected) watching = true
  }
  function watch() {
    following = !!selected
    watching = true
  }
  const onCtrlStart = () => { following = false; watching = false }
  controls.addEventListener('start', onCtrlStart)

  // ---- hover picking
  const raycaster = new Raycaster()
  const ndc = new Vector2()
  const onMove = e => {
    const r = renderer.domElement.getBoundingClientRect()
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    raycaster.setFromCamera(ndc, camera)
    const hit = raycaster.intersectObjects([...villagers.values()].map(v => v.group), true)[0]
    let o = hit?.object
    while (o && !o.userData.name) o = o.parent
    hovered = o?.userData.name ?? null
  }
  const onLeave = () => { hovered = null }
  renderer.domElement.addEventListener('pointermove', onMove)
  renderer.domElement.addEventListener('pointerleave', onLeave)

  // ---- sizing
  const resize = () => {
    const w = Math.max(1, container.clientWidth)
    const h = Math.max(1, container.clientHeight)
    renderer.setSize(w, h)
    theme.resize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
  }
  const ro = new ResizeObserver(resize)
  ro.observe(container)
  resize()

  // ---- per-villager animation
  function animate(v, vi, pose, slot, tt, dt) {
    const c = v.cur
    const T = { aL: 0, aR: 0, lL: 0, lR: 0, headY: 0, drop: 0, lean: 0, bob: 0 }
    const st = pose.step
    const a = st?.action ?? {}
    let face = null // world-space yaw to turn toward
    let status = null
    let tool = false
    let building = false

    const faceTile = (tx, ty) => {
      const dx = wx(tx) - wx(pose.x)
      const dz = wz(ty) - wz(pose.y)
      if (Math.abs(dx) + Math.abs(dz) > 0.01) face = Math.atan2(dx, dz)
    }
    const faceVillager = tn => {
      const o = villagers.get(tn)
      if (!o) return
      const dx = o.pos.x - v.pos.x
      const dz = o.pos.z - v.pos.z
      if (Math.abs(dx) + Math.abs(dz) > 0.01) face = Math.atan2(dx, dz)
    }

    if (pose.asleep) {
      T.drop = 0.14
      T.lL = T.lR = -1.4
      T.aL = T.aR = -0.25
      status = 'label|z z'
    } else if (!st || !pose.ok) {
      const s = Math.sin(tt * 1.6 + vi.name.length)
      T.aL = 0.04 + 0.03 * s
      T.aR = -0.04 - 0.03 * s
      if (st && !pose.ok) {
        T.headY = Math.sin(tt * 14) * 0.5
        status = 'label|?'
      }
    } else {
      switch (pose.verb) {
        case 'walk': {
          const s = Math.sin(tt * 11)
          T.lL = s * 0.7
          T.lR = -s * 0.7
          T.aL = -s * 0.5
          T.aR = s * 0.5
          T.bob = Math.abs(s) * 0.035
          if (pose.heading) face = Math.atan2(pose.heading[0], pose.heading[1])
          break
        }
        case 'gather': {
          if (st.source) faceTile(st.source[0], st.source[1])
          if (a.item === 'food' || a.item === 'water') {
            T.drop = 0.1
            T.lean = 0.55
            T.lL = T.lR = -0.5
            T.aR = -1.0 + Math.sin(tt * 8) * 0.5
            T.aL = -0.8 + Math.cos(tt * 8) * 0.4
          } else {
            tool = true
            T.aR = -1.3 + Math.sin(tt * 7) * 0.9
            T.aL = -0.3
            T.lean = 0.12
          }
          break
        }
        case 'build': {
          building = true
          tool = true
          T.aR = -1.2 + Math.sin(tt * 9) * 0.75
          T.aL = -0.4
          T.lean = 0.15
          face = Math.atan2(-BUILD_SPOT.x, -BUILD_SPOT.y)
          break
        }
        case 'rest':
          T.drop = 0.14
          T.lL = T.lR = -1.4
          T.aL = T.aR = -0.25
          status = 'label|z z'
          break
        case 'look':
          T.headY = Math.sin(tt * 2.2) * 0.9
          T.aL = T.aR = 0.03
          break
        case 'talk':
          if (st.target) faceVillager(st.target)
          T.aR = -0.6 + Math.sin(tt * 6) * 0.4
          T.aL = 0.05
          if (st.say) status = `bubble|${trunc(String(st.say), 40)}`
          break
        case 'hunt': {
          tool = true
          if (st.source) faceTile(st.source[0], st.source[1])
          T.aR = -1.5 + Math.sin(tt * 8) * 0.7
          T.aL = -0.5
          T.lean = 0.25
          break
        }
        case 'deposit':
        case 'take':
          T.drop = 0.05
          T.lean = 0.4
          T.aL = T.aR = -0.9
          break
        case 'experiment': {
          tool = true
          T.aR = -1.0 + Math.sin(tt * 6) * 0.5
          T.aL = -0.8 + Math.cos(tt * 5) * 0.4
          T.lean = 0.2
          T.headY = Math.sin(tt * 1.7) * 0.4
          status = 'label|hmm...'
          break
        }
        case 'teach':
          if (st.target) faceVillager(st.target)
          T.aR = -0.9 + Math.sin(tt * 4) * 0.2
          T.aL = -0.5
          status = `label|teaching ${a.item ?? ''}`.trim()
          break
        case 'trade':
          if (st.target) faceVillager(st.target)
          T.aL = T.aR = -1.0 + Math.sin(tt * 3) * 0.1
          status = 'label|trade'
          break
        default:
          break
      }
    }

    // smooth everything so step changes never pop
    const k = 1 - Math.exp(-dt * 12)
    for (const key of Object.keys(T)) c[key] += (T[key] - c[key]) * k
    v.off += ((building ? 1 : 0) - v.off) * (1 - Math.exp(-dt * 6))
    if (face !== null) v.yaw += wrapAngle(face - v.yaw) * (1 - Math.exp(-dt * 10))
    v.legL.rotation.x = c.lL
    v.legR.rotation.x = c.lR
    v.armL.rotation.x = c.aL
    v.armR.rotation.x = c.aR
    v.head.rotation.y = c.headY
    v.rig.position.y = -c.drop
    v.rig.rotation.x = c.lean
    v.tool.visible = tool
    const inv = pose.inv ?? {}
    const wood = inv.wood ?? 0
    const stone = inv.stone ?? 0
    v.bundle.visible = wood > 0 || stone > 0
    if (v.bundle.visible) v.setCarry(stone > wood ? 'stone' : 'wood')
    setStatus(v, status)
    if (v.status) v.status.position.y = v.labelY + (v.statusKey.startsWith('bubble') ? 0.34 : 0.27) + (v.statusKey === 'label|z z' ? 0.05 * Math.sin(tt * 2.5) : 0)

    // "+2 wood" when a gather step has just completed
    const key = `${playDay}:${pose.lastIndex}`
    if (key !== v.doneKey) {
      v.doneKey = key
      const s = pose.last
      if (s && s.ok && s.gain && slot - (s.at + s.slots) < 0.6) {
        let i = 0
        for (const [item, n] of Object.entries(s.gain)) {
          spawnFloat(`+${n} ${item}`, v.group.position.x, v.group.position.y + 1.1 + 0.25 * i, v.group.position.z)
          i++
        }
      }
    }
  }

  // ---- loop (runs only while the document is visible)
  let raf = 0
  let disposed = false
  let lastNow = 0
  function frame() {
    raf = 0
    if (disposed || document.hidden) return
    const now = performance.now()
    const dt = Math.min(0.05, Math.max(0, (now - (lastNow || now)) / 1000))
    lastNow = now
    const tt = now / 1000
    const clock = getClock?.(world)
    const spd = world?.slots_per_day ?? 8
    const slot = clock ? clock.slot : spd
    const dayT = clock ? clock.dayT : 0.4
    syncFog(dt)
    const night = theme.light(dayT, controls.target, camera)
    theme.tick(tt, dt, camera, controls, night)
    theme.seasonLook(world?.season, dt)

    syncBuildings(world ? buildStateAt(world, slot) : [], tt, night)
    if (field) {
      syncGraves(slot, spd)
      syncAnimals(dt, tt)
    }

    const byName = new Map()
    for (const e of world?.current?.villagers ?? []) byName.set(e.name, e)
    for (const vi of world?.villagers ?? []) {
      const v = villagers.get(vi.name)
      if (!v) continue
      v.group.visible = !(vi.dying && slot >= spd) // the day plays out before anyone learns how it ended
      const entry = byName.get(vi.name)
      const pose = entry ? poseAt(entry, slot, spd) : idlePose(vi)
      const off = v.off
      const tx = wx(pose.x) + BUILD_SPOT.x * off
      const tz = wz(pose.y) + BUILD_SPOT.y * off
      if (!v.init) {
        v.init = true
        v.pos.set(tx, 0, tz)
        v.gy = field.groundAt(v.pos.x, v.pos.z)
      } else {
        const b = clamp01((now - v.blendT0) / BLEND_MS)
        if (b < 1) {
          const e = smooth(b)
          v.pos.set(lerp(v.blendFrom.x, tx, e), 0, lerp(v.blendFrom.z, tz, e))
        } else {
          v.pos.set(tx, 0, tz)
        }
        v.gy += (field.groundAt(v.pos.x, v.pos.z) - v.gy) * (1 - Math.exp(-dt * 15))
      }
      animate(v, vi, pose, slot, tt, dt)
      const spread = SPREAD[vi.name] ?? [0, 0] // villagers sharing a tile stand side by side
      const gap = theme.spread ?? 1
      v.group.position.set(v.pos.x + spread[0] * gap, v.gy + v.cur.bob, v.pos.z + spread[1] * gap)
      v.group.rotation.y = v.yaw
      v.ring.visible = vi.name === hovered || vi.name === selected
      if (v.ring.visible) v.ring.position.set(v.pos.x, v.gy + 0.3, v.pos.z)
    }

    for (let i = floats.length - 1; i >= 0; i--) {
      const f = floats[i]
      const age = (now - f.t0) / 1500
      if (age >= 1) {
        disposeSprite(f.s)
        floats.splice(i, 1)
      } else {
        f.s.position.set(f.x, f.y + age * 0.7, f.z)
        f.s.material.opacity = 1 - age * age
      }
    }

    if (following && selected && villagers.has(selected)) {
      const p = villagers.get(selected).pos
      goal.set(p.x, 0.4, p.z)
      delta.copy(goal).sub(controls.target).multiplyScalar(1 - Math.exp(-dt * 5))
      controls.target.add(delta)
      camera.position.add(delta)
    } else if (watching && villagers.size) {
      goal.set(0, 0.4, 0)
      for (const v of villagers.values()) goal.add(v.pos)
      goal.x /= villagers.size
      goal.z /= villagers.size
      delta.copy(goal).sub(controls.target).multiplyScalar(1 - Math.exp(-dt * 0.8))
      controls.target.add(delta)
      camera.position.add(delta)
    }
    controls.update()
    theme.render(tt)
    raf = requestAnimationFrame(frame)
  }
  const start = () => { if (!raf && !disposed && !document.hidden) raf = requestAnimationFrame(frame) }
  const onVis = () => {
    if (document.hidden) {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    } else {
      lastNow = 0
      start()
    }
  }
  document.addEventListener('visibilitychange', onVis)
  start()

  return {
    watch,
    update,
    setPlayback,
    select,
    dispose() {
      disposed = true
      if (raf) cancelAnimationFrame(raf)
      raf = 0
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVis)
      renderer.domElement.removeEventListener('pointermove', onMove)
      renderer.domElement.removeEventListener('pointerleave', onLeave)
      controls.removeEventListener('start', onCtrlStart)
      for (const f of floats) disposeSprite(f.s)
      floats.length = 0
      for (const v of villagers.values()) disposeVillager(v)
      villagers.clear()
      for (const rec of buildings.values()) scene.remove(rec.group)
      buildings.clear()
      for (const g of graves.values()) scene.remove(g)
      graves.clear()
      for (const e of texCache.values()) e.tex.dispose()
      texCache.clear()
      controls.dispose()
      theme.dispose()
      lineMat.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }
}
