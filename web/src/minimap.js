// The map of what the villagers have seen. Land nobody has seen stays dark, so it grows as they explore.
// One pixel per tile on a small canvas, redrawn only when the land changes; the dots on top are cheap.

export const MINIMAP_SIZE = 132
const MIN_SPAN = 32
const COLORS = {
  '.': [122, 139, 72], T: [46, 92, 52], b: [120, 96, 60], '~': [58, 120, 138], R: [128, 124, 116]
}
const FALLBACK = [110, 120, 80]

export function createMinimap(canvas, onLook) {
  const SIZE = MINIMAP_SIZE
  const ctx = canvas.getContext('2d')
  const land = document.createElement('canvas')
  let rev = null
  let box = { x: 0, y: 0, w: 1, h: 1 }
  let frame = { cx: 0, cy: 0, span: MIN_SPAN }

  function paint(view) {
    const keys = Object.keys(view?.seen ?? {})
    if (!keys.length) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const key of keys) {
      const [kx, ky] = key.split(',').map(Number)
      x0 = Math.min(x0, kx * 16); y0 = Math.min(y0, ky * 16)
      x1 = Math.max(x1, kx * 16 + 16); y1 = Math.max(y1, ky * 16 + 16)
    }
    box = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
    land.width = box.w
    land.height = box.h
    const pen = land.getContext('2d')
    const image = pen.createImageData(box.w, box.h)
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const key of keys) {
      const [kx, ky] = key.split(',').map(Number)
      const seen = view.seen[key]
      const chars = view.land[key] ?? ''
      for (let i = 0; i < 256; i++) {
        if (seen[i] !== '1') continue
        const x = kx * 16 + (i & 15)
        const y = ky * 16 + (i >> 4)
        const at = ((y - box.y) * box.w + (x - box.x)) * 4
        const [r, g, b] = COLORS[chars[i]] ?? FALLBACK
        image.data[at] = r; image.data[at + 1] = g; image.data[at + 2] = b; image.data[at + 3] = 255
        minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y)
      }
    }
    pen.putImageData(image, 0, 0)
    frame = { cx: (minX + maxX + 1) / 2, cy: (minY + maxY + 1) / 2, span: Math.max(MIN_SPAN, Math.max(maxX - minX, maxY - minY) * 1.15 + 8) }
  }

  const toMap = (x, y) => [((x - frame.cx) / frame.span + 0.5) * SIZE, ((y - frame.cy) / frame.span + 0.5) * SIZE]

  function dot(x, y, r, fill) {
    const [mx, my] = toMap(x, y)
    ctx.beginPath()
    ctx.arc(mx, my, r, 0, Math.PI * 2)
    ctx.fillStyle = '#000'
    ctx.fill()
    ctx.beginPath()
    ctx.arc(mx, my, r - 0.8, 0, Math.PI * 2)
    ctx.fillStyle = fill
    ctx.fill()
  }

  /** `people` is { name: {x, y} }; `look` is the tile the camera is on, if the scene is up. */
  function draw(world, people, look, selected) {
    const view = world?.land_view
    if (view && view.rev !== rev) {
      rev = view.rev
      paint(view)
    }
    ctx.fillStyle = '#05060c'
    ctx.fillRect(0, 0, SIZE, SIZE)
    ctx.imageSmoothingEnabled = false
    const [lx, ly] = toMap(box.x, box.y)
    const scale = SIZE / frame.span
    ctx.drawImage(land, lx, ly, box.w * scale, box.h * scale)
    if (look) {
      const [mx, my] = toMap(look.x, look.y)
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)'
      ctx.lineWidth = 1
      ctx.strokeRect(Math.round(mx) - 6.5, Math.round(my) - 6.5, 13, 13)
    }
    if (world?.camp) {
      const [mx, my] = toMap(world.camp[0], world.camp[1])
      ctx.fillStyle = '#000'
      ctx.fillRect(mx - 3, my - 3, 6, 6)
      ctx.fillStyle = '#e6b450'
      ctx.fillRect(mx - 2, my - 2, 4, 4)
    }
    for (const h of world?.resources?.herds ?? []) dot(h.x, h.y, 2, '#d98a5a')
    for (const [name, p] of Object.entries(people ?? {})) dot(p.x, p.y, name === selected ? 3.4 : 2.6, name === selected ? '#e6b450' : '#fff')
  }

  const onClick = e => {
    const r = canvas.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width - 0.5) * frame.span + frame.cx
    const y = ((e.clientY - r.top) / r.height - 0.5) * frame.span + frame.cy
    onLook(Math.round(x), Math.round(y))
  }
  canvas.addEventListener('click', onClick)
  return { draw, dispose() { canvas.removeEventListener('click', onClick) } }
}
