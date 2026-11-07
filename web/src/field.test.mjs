// Chunks are built at different times from different neighbours; they must still meet exactly.
import assert from 'node:assert/strict'
import { createField, CHUNK } from './themes/util.js'

const tiles = (cx, cy) => {
  let out = ''
  for (let y = 0; y < CHUNK; y++) {
    for (let x = 0; x < CHUNK; x++) {
      const h = Math.sin((cx * CHUNK + x) * 0.31) + Math.cos((cy * CHUNK + y) * 0.27)
      out += h > 1 ? 'R' : h > 0.3 ? 'T' : h < -1.1 ? '~' : '.'
    }
  }
  return out
}
const make = () => createField({ heights: { '~': -0.34, '.': 0.16, b: 0.17, T: 0.2, R: 0.42 }, res: 3, relief: 0.13, reliefFreq: 0.42 })
const area = (x0, y0, x1, y1) => {
  const land = {}
  for (let cy = y0; cy <= y1; cy++) for (let cx = x0; cx <= x1; cx++) land[`${cx},${cy}`] = tiles(cx, cy)
  return land
}

const field = make()
field.add(area(-3, -3, 3, 3))
for (const [x, z] of [[0, 3.3], [16, -7.7], [-16, 9.1], [-32, -15.4]]) { // along vertical chunk borders
  assert.ok(Math.abs(field.heightAt(x - 1e-6, z) - field.heightAt(x, z)) < 1e-3, `seam at ${x},${z}`)
}
for (const [x, z] of [[4.2, 0], [-9.9, 16], [13.1, -16]]) { // along horizontal ones
  assert.ok(Math.abs(field.heightAt(x, z - 1e-6) - field.heightAt(x, z)) < 1e-3, `seam at ${x},${z}`)
}

// the land near a chunk must not depend on the order the chunks arrived in
const late = make()
late.add(area(0, 0, 0, 0))
assert.equal(typeof late.heightAt(4, 4), 'number') // built once with its neighbours missing
late.add(area(-1, -1, 1, 1))
const early = make()
early.add(area(-1, -1, 1, 1))
for (const [x, z] of [[0.5, 0.5], [15.5, 8], [8, 15.9], [2, 2]]) {
  assert.ok(Math.abs(late.heightAt(x, z) - early.heightAt(x, z)) < 1e-9, `order matters at ${x},${z}`)
}

// forgetting a chunk's raster loses nothing
const before = field.heightAt(5.5, 5.5)
field.forget(0, 0)
assert.equal(field.heightAt(5.5, 5.5), before)

// negative tiles land in the right chunk
assert.equal(field.charAt(-1, -1), tiles(-1, -1)[CHUNK * CHUNK - 1])
assert.equal(field.charAt(-16, -16), tiles(-1, -1)[0])
console.log('field tests passed')
