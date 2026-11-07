// Run with: node web/src/playback.test.mjs   (not bundled)
import assert from 'node:assert/strict'
import { poseAt, builtAt, buildStateAt, feedAt, clockAt, describePose } from './playback.js'

const near = (a, b, m) => assert.ok(Math.abs(a - b) < 1e-6, `${m}: ${a} != ${b}`)
const walk = { action: { verb: 'walk', x: 4, y: 2 }, ok: true, result: 'walked to (4,2)', at: 0, slots: 2, after: { x: 4, y: 2, energy: 5, inv: {} }, path: [[0, 0], [2, 0], [2, 2], [4, 2]] }
const gather = { action: { verb: 'gather', item: 'wood' }, ok: true, result: 'gathered 2 wood', at: 2, slots: 2, after: { x: 4, y: 2, energy: 4, inv: { wood: 2 } }, gain: { wood: 2 }, source: [5, 2] }
const bad = { action: { verb: 'trade', target: 'Bryn' }, ok: false, result: 'Bryn is too far away to trade', at: 4, slots: 1, after: { x: 4, y: 2, energy: 4, inv: { wood: 2 } } }
const build = { action: { verb: 'build', item: 'lean_to' }, ok: true, result: 'built a lean_to', at: 5, slots: 3, after: { x: 4, y: 2, energy: 3, inv: {} }, built: { kind: 'lean_to', x: 4, y: 2, by: 'Ash', day: 3 } }
const rest = { action: { verb: 'rest' }, ok: true, result: 'rested', at: 0, slots: 1, after: { x: 1, y: 1, energy: 9, inv: {} } }
const world = {
  built: [{ kind: 'lean_to', x: 4, y: 2, by: 'Ash', day: 3 }, { kind: 'hut', x: 9, y: 9, by: 'Coll', day: 1 }],
  current: {
    day: 3,
    villagers: [
      { name: 'Ash', start: { x: 0, y: 0, energy: 6, inv: {} }, night: { ate: true, x: 4, y: 2, energy: 8, inv: {} }, steps: [walk, gather, bad, build] },
      { name: 'Bryn', start: { x: 1, y: 1, energy: 7, inv: {} }, night: { ate: true, x: 1, y: 1, energy: 9, inv: {} }, steps: [rest] }
    ]
  },
  day_seconds: 120, work_fraction: 0.85, slots_per_day: 8, day_started_at: 1000
}
const ash = world.current.villagers[0]

// walking: constant speed along the polyline (total length 6)
let p = poseAt(ash, 0)
near(p.x, 0, 'x0'); near(p.energy, 6, 'e0'); assert.equal(p.verb, 'walk'); assert.equal(p.last, null); assert.equal(p.lastIndex, -1)
p = poseAt(ash, 1) // halfway = 3 along: 2 on the first leg, 1 down the second
near(p.x, 2, 'x1'); near(p.y, 1, 'y1'); assert.deepEqual(p.heading, [0, 1]); near(p.progress, 0.5, 'progress')
p = poseAt(ash, 0.5)
near(p.x, 1.5, 'x.5'); near(p.y, 0, 'y.5'); assert.deepEqual(p.heading, [1, 0])

// after the walk: position and energy come from `after`
p = poseAt(ash, 2.5)
near(p.x, 4, 'x2.5'); near(p.y, 2, 'y2.5'); near(p.energy, 5, 'e2.5')
assert.equal(p.verb, 'gather'); assert.equal(p.lastIndex, 0); near(p.progress, 0.25, 'gather progress')
assert.equal(describePose(p), 'Gathering wood')

// a rejected step
p = poseAt(ash, 4)
assert.equal(p.inv.wood, 2); assert.equal(p.ok, false); assert.equal(p.verb, 'trade')
assert.equal(describePose(p), "Can't trade")

// dusk uses `night`, and everyone sleeps; after the last step a villager is idle
p = poseAt(ash, 8)
assert.equal(p.dusk, true); assert.equal(p.verb, 'rest'); assert.equal(p.step, null); near(p.energy, 8, 'night energy')
p = poseAt(world.current.villagers[1], 3)
assert.equal(p.verb, 'idle'); near(p.energy, 9, 'idle energy'); near(p.x, 1, 'idle x')

// buildings
assert.deepEqual(builtAt(world, 4).map(b => b.kind), ['hut'])
assert.deepEqual(builtAt(world, 6).map(b => b.kind), ['hut'])
assert.deepEqual(builtAt(world, 8).map(b => b.kind), ['lean_to', 'hut'])
const st = buildStateAt(world, 6.5)
near(st.find(b => b.kind === 'lean_to').progress, 0.5, 'build progress')
near(st.find(b => b.kind === 'hut').progress, 1, 'older building complete')
assert.equal(buildStateAt(world, 5).find(b => b.kind === 'lean_to').progress, 0)

// feed: completed steps only, newest first
assert.deepEqual(feedAt(world, 0.5), [])
const feed = feedAt(world, 4.5)
assert.deepEqual(feed.map(f => f.text), ['gathered 2 wood', 'walked to (4,2)', 'rested'])
assert.equal(feed[0].text, 'gathered 2 wood'); assert.equal(feed[0].name, 'Ash'); assert.equal(feed[0].ok, true)
const later = feedAt(world, 5.5)
assert.equal(later[0].ok, false); assert.equal(later[0].text, 'Bryn is too far away to trade')
assert.equal(feedAt(world, 8, 2).length, 2)
assert.equal(feedAt(world, 8)[0].text, 'built a lean_to')

// clock
let c = clockAt(world, 1000)
near(c.dayT, 0, 'dayT0'); near(c.slot, 0, 'slot0'); assert.equal(c.phase, 'Morning')
{
  const dawn = { ...world, dawn_fraction: 0.1, work_fraction: 0.8 }
  const early = clockAt(dawn, 1000 + 120 * 0.05)
  assert.equal(early.phase, 'Dawn'); assert.ok(early.slot < 0, 'nobody works before dawn ends')
  assert.equal(poseAt({ start: { x: 1, y: 2, energy: 5, inv: {} }, steps: [] }, early.slot).asleep, true)
  near(clockAt(dawn, 1000 + 120 * 0.8).slot, 8, 'work ends with the last slot')
  assert.equal(clockAt(dawn, 1000 + 120 * 0.95).phase, 'Night')
}
c = clockAt(world, 1000 + (120 * 0.85) / 2)
near(c.slot, 4, 'slot mid'); assert.equal(c.phase, 'Morning')
assert.equal(clockAt(world, 1000 + 120 * 0.6).phase, 'Afternoon')
c = clockAt(world, 1000 + 120 * 0.87)
assert.equal(c.phase, 'Dusk')
near(clockAt(world, 5000).dayT, 1, 'clamped high')
near(clockAt(world, 900).dayT, 0, 'clamped low')

console.log('playback tests passed')
