// Pure replay helpers (no three.js, no DOM). They turn the backend's `world.current` day report plus a
// slot clock (0..slots_per_day) into what each villager is doing right now.

const lerp = (a, b, t) => a + (b - a) * t
const clamp01 = n => (n < 0 ? 0 : n > 1 ? 1 : n)
const endOf = s => (s.at ?? 0) + (s.slots ?? 1)

function idleFrom(p) {
  return { x: p.x, y: p.y, energy: p.energy, inv: p.inv ?? {} }
}

// Position a fraction of the way along a polyline of tile coords (constant speed), plus segment heading.
function along(path, frac) {
  let total = 0
  const lens = []
  for (let i = 1; i < path.length; i++) {
    const l = Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
    lens.push(l)
    total += l
  }
  if (total <= 0) return { x: path[path.length - 1][0], y: path[path.length - 1][1], heading: null }
  let d = clamp01(frac) * total
  for (let i = 0; i < lens.length; i++) {
    if (d <= lens[i] || i === lens.length - 1) {
      const t = lens[i] > 0 ? clamp01(d / lens[i]) : 1
      const [ax, ay] = path[i]
      const [bx, by] = path[i + 1]
      return { x: lerp(ax, bx, t), y: lerp(ay, by, t), heading: lens[i] > 0 ? [(bx - ax) / lens[i], (by - ay) / lens[i]] : null }
    }
    d -= lens[i]
  }
  return { x: path[0][0], y: path[0][1], heading: null }
}

/** Pose of one villager entry (from world.current.villagers) at `slot`. */
export function poseAt(entry, slot, slotsPerDay = 8) {
  const steps = entry?.steps ?? []
  const dusk = slot >= slotsPerDay
  let base = idleFrom(entry?.start ?? { x: 0, y: 0, energy: 0, inv: {} })
  let last = null
  let lastIndex = -1
  let cur = null
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i]
    if (endOf(s) <= slot) {
      base = idleFrom(s.after ?? base)
      last = s
      lastIndex = i
    } else {
      if ((s.at ?? 0) <= slot) cur = s
      break
    }
  }
  if (dusk) {
    cur = null
    if (entry?.night) base = idleFrom(entry.night)
  }
  const asleep = dusk || slot < 0
  const pose = { x: base.x, y: base.y, verb: asleep ? 'rest' : 'idle', ok: true, progress: 0, step: cur, energy: base.energy, inv: base.inv, heading: null, dusk, asleep, last, lastIndex }
  if (cur) {
    pose.verb = cur.action?.verb ?? 'idle'
    pose.ok = cur.ok !== false
    pose.progress = clamp01((slot - cur.at) / Math.max(1e-6, cur.slots))
    if (pose.ok && Array.isArray(cur.path) && cur.path.length > 1) {
      const p = along(cur.path, pose.progress)
      pose.x = p.x
      pose.y = p.y
      pose.heading = p.heading
    }
  }
  return pose
}

/** Pose for a villager with no replay entry: standing at its end-of-day position. */
export function idlePose(v) {
  return { x: v.x, y: v.y, verb: 'idle', ok: true, progress: 0, step: null, energy: v.energy, inv: v.inv ?? {}, heading: null, dusk: false, last: null, lastIndex: -1 }
}

const keyOf = b => `${b.kind}@${b.x},${b.y}`

/** world.built, each with a build progress 0..1 (0 = not started yet, 1 = complete). */
export function buildStateAt(world, slot) {
  const steps = new Map()
  for (const e of world?.current?.villagers ?? []) {
    for (const s of e.steps ?? []) if (s.built) steps.set(keyOf(s.built), s)
  }
  return (world?.built ?? []).map(b => {
    const s = steps.get(keyOf(b))
    let progress = 1
    if (s && endOf(s) > slot) progress = slot <= s.at ? 0 : clamp01((slot - s.at) / Math.max(1e-6, s.slots))
    return { ...b, progress }
  })
}

/** world.built minus buildings whose build step has not completed yet. */
export function builtAt(world, slot) {
  const done = new Set(buildStateAt(world, slot).filter(b => b.progress >= 1).map(keyOf))
  return (world?.built ?? []).filter(b => done.has(keyOf(b)))
}

/** Completed step events, newest first: [{ name, text, ok }]. */
export function feedAt(world, slot, limit = 6) {
  const events = []
  let seq = 0
  for (const e of world?.current?.villagers ?? []) {
    for (const s of e.steps ?? []) {
      seq++
      if (endOf(s) <= slot) events.push({ name: e.name, text: s.result ?? String(s.action?.verb ?? ''), ok: s.ok !== false, t: endOf(s), seq })
    }
  }
  events.sort((a, b) => b.t - a.t || b.seq - a.seq)
  return events.slice(0, limit).map(({ name, text, ok }) => ({ name, text, ok }))
}

/** Short present-tense phrase for a pose, for the villager cards. */
export function describePose(pose) {
  const st = pose.step
  if (pose.asleep) return 'Asleep'
  if (!st) return 'Idle'
  const a = st.action ?? {}
  if (!pose.ok) return `Can't ${a.verb ?? 'act'}`
  switch (pose.verb) {
    case 'walk': return 'Walking'
    case 'gather': return `Gathering ${a.item ?? 'resources'}`
    case 'build': return `Building ${String(a.item ?? 'something').replace(/_/g, ' ')}`
    case 'rest': return 'Resting'
    case 'look': return 'Looking around'
    case 'talk': return st.target ? `Talking to ${st.target}` : 'Talking'
    case 'teach': return st.target ? `Teaching ${st.target}` : 'Teaching'
    case 'trade': return st.target ? `Trading with ${st.target}` : 'Trading'
    case 'experiment': return `Trying ${a.item ?? 'an idea'}`
    case 'hunt': return `Hunting ${a.item ?? 'game'}`
    case 'deposit': return `Storing ${a.item ?? 'goods'}`
    case 'take': return `Taking ${a.item ?? 'goods'} from the store`
    default: return 'Idle'
  }
}

/** Day clock from server time: { dayT 0..1, slot, phase }. Work slots span dayT 0..work_fraction. */
export function clockAt(world, serverNow) {
  const dayS = world?.day_seconds || 120
  const wf = world?.work_fraction || 0.85
  const dawn = world?.dawn_fraction ?? 0
  const spd = world?.slots_per_day || 8
  const at = world?.paused_at ?? serverNow
  const dayT = clamp01(((at - (world?.day_started_at ?? at)) * (world?.speed || 1)) / dayS)
  const slot = ((dayT - dawn) / (wf - dawn)) * spd
  const phase = dayT >= 0.9 ? 'Night' : dayT >= wf ? 'Dusk' : dayT < dawn ? 'Dawn' : dayT < 0.45 ? 'Morning' : 'Afternoon'
  return { dayT, slot, phase, evening: dayT >= wf }
}
