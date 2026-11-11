import * as sdk from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { makeApi, errText, fmtTokens } from './api.js'
import { createScene } from './scene.js'
import { SKIN_CSS } from './skins.js'
import { createMinimap, MINIMAP_SIZE } from './minimap.js'
import { createSound } from './sound.js'
import { poseAt, idlePose, describePose, feedAt, clockAt } from './playback.js'

const { host } = sdk

// The page is always dark: the village fills the view and everything else docks around it.
const C = {
  glass: 'rgba(14, 16, 20, 0.86)', solid: '#111317', raised: 'rgba(255, 255, 255, 0.06)', line: 'rgba(255, 255, 255, 0.09)',
  text: '#ece9e2', mid: 'var(--hv-mid, #a9a69e)', low: 'var(--hv-low, #74726b)', gold: '#e6b450', red: '#e8695a', green: '#86c172'
}
const line = { borderWidth: 1, borderStyle: 'solid', borderColor: C.line }
const glass = { background: C.glass, backdropFilter: 'blur(10px)', ...line, borderRadius: 10 }
const TOP = 46
const DOCK = 46
const RAIL = 62

const S = {
  root: { position: 'relative', width: '100%', height: '100%', minHeight: 420, overflow: 'hidden', background: C.solid, color: C.text, fontSize: 13, lineHeight: 1.35 },
  canvas: { position: 'absolute', inset: 0, overflow: 'hidden' },
  top: { ...glass, position: 'absolute', top: 8, left: 8, right: 8, height: TOP, boxSizing: 'border-box', padding: '0 14px', display: 'flex', alignItems: 'center', gap: 16 },
  stat: { display: 'flex', alignItems: 'baseline', gap: 5, whiteSpace: 'nowrap' },
  rail: { ...glass, position: 'absolute', top: TOP + 16, right: 8, width: RAIL, boxSizing: 'border-box', padding: 4, display: 'flex', flexDirection: 'column', gap: 2 },
  drawer: { ...glass, position: 'absolute', top: TOP + 16, right: RAIL + 16, bottom: DOCK + 16, width: 300, maxWidth: 'calc(100% - 100px)', boxSizing: 'border-box', display: 'flex', flexDirection: 'column' },
  drawerBody: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 12px 12px', display: 'flex', flexDirection: 'column', gap: 10 },
  dock: { ...glass, position: 'absolute', left: 8, right: 8, bottom: 8, height: DOCK, boxSizing: 'border-box', padding: '0 8px', display: 'flex', alignItems: 'center' },
  person: { width: '100%', minHeight: 40, flexShrink: 0, boxSizing: 'border-box', background: C.raised, ...line, borderRadius: 8, padding: '5px 8px', color: C.text, font: 'inherit', textAlign: 'left', cursor: 'pointer', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1 },
  bar: { display: 'flex', alignItems: 'center', gap: 6, flex: 1, minWidth: 0 },
  clip: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  h: { fontSize: 11, fontWeight: 600, letterSpacing: 0.5, textTransform: 'uppercase', color: C.low },
  mid: { color: C.mid },
  low: { color: C.low, fontSize: 12 },
  row: { display: 'flex', gap: 8, alignItems: 'center' },
  left: { position: 'absolute', top: TOP + 16, left: 8, width: 'min(320px, 45%)', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8, pointerEvents: 'none' },
  stock: { ...glass, boxSizing: 'border-box', padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 1, pointerEvents: 'auto' },
  feed: { paddingLeft: 4, display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12, textShadow: '0 1px 3px rgba(0,0,0,0.9)' },
  mini: { ...glass, position: 'absolute', right: 8, bottom: DOCK + 16, padding: 4, lineHeight: 0, overflow: 'hidden' },
  welcome: { ...glass, position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: 'min(440px, 80%)', maxHeight: 'calc(100% - 40px)', overflowY: 'auto', boxSizing: 'border-box', padding: 18, display: 'flex', flexDirection: 'column', gap: 10, borderColor: C.gold },
  card: { ...glass, position: 'absolute', left: 8, bottom: DOCK + 16, width: 300, maxWidth: 'calc(100% - 100px)', boxSizing: 'border-box', padding: 12, display: 'flex', flexDirection: 'column', gap: 6 },
  notice: { ...glass, position: 'absolute', top: TOP + 16, left: '50%', transform: 'translateX(-50%)', width: 'min(380px, 60%)', boxSizing: 'border-box', padding: 12, display: 'flex', flexDirection: 'column', gap: 8, borderColor: C.gold },
  input: { width: '100%', boxSizing: 'border-box', background: C.raised, color: C.text, ...line, borderRadius: 8, padding: '6px 8px', font: 'inherit', resize: 'none' }
}

function Btn({ primary, on, style, className = '', ...props }) {
  const look = primary ? { background: C.gold, color: '#1a1408', borderColor: C.gold, fontWeight: 600 }
    : on ? { background: 'rgba(230, 180, 80, 0.18)', color: C.gold, borderColor: C.gold } : { background: C.raised, color: C.text, borderColor: C.line }
  return (
    <button type="button" {...props} className={`hv-btn${primary ? ' hv-primary' : ''} ${className}`} data-on={on ? 'true' : undefined} style={{ font: 'inherit', fontSize: 12, borderWidth: 1, borderStyle: 'solid', borderRadius: 7, padding: '5px 10px', whiteSpace: 'nowrap', cursor: props.disabled ? 'default' : 'pointer', opacity: props.disabled ? 0.4 : 1, ...look, ...style }} />
  )
}

function Hearts({ value, max }) {
  return (
    <span aria-label={`health ${value} of ${max}`} style={{ color: value <= 2 ? C.red : C.gold, fontSize: 11, letterSpacing: 0.5 }}>
      {'♥'.repeat(Math.max(0, value))}<span style={{ opacity: 0.22 }}>{'♥'.repeat(Math.max(0, max - value))}</span>
    </span>
  )
}

function Meter({ value, max, color = C.gold, width = 54 }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0
  return (
    <span className="hv-meter" style={{ display: 'inline-block', width, height: 4, borderRadius: 2, background: C.line, overflow: 'hidden', alignSelf: 'center' }}>
      <span style={{ display: 'block', width: `${pct}%`, height: '100%', background: color }} />
    </span>
  )
}

function DayBar({ dayT, wf }) {
  const pct = Math.max(0, Math.min(1, dayT ?? 0)) * 100
  return (
    <div className="hv-meter" style={{ position: 'relative', flex: 1, minWidth: 40, height: 4, borderRadius: 2, background: C.line }}>
      <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: C.gold, opacity: 0.6 }} />
      <div style={{ position: 'absolute', left: `${wf * 100}%`, top: -2, width: 1, height: 8, background: C.low }} />
    </div>
  )
}

function Person({ v, live, selected, onSelect, gone, maxHealth, way }) {
  if (gone) {
    return <div className="hv-card" style={{ ...S.person, cursor: 'default', opacity: 0.55 }}><strong style={S.clip}>{v.name}</strong><span style={{ ...S.low, ...S.clip }}>died of {v.dying}</span></div>
  }
  return (
    <button type="button" className="hv-card" data-selected={selected ? 'true' : undefined} onClick={() => onSelect(v.name)} style={{ ...S.person, borderColor: selected ? C.gold : C.line }}>
      <span style={{ ...S.bar, justifyContent: 'space-between' }}>
        <strong style={S.clip}>{v.name}</strong>
        <Hearts value={v.dying ? v.health + 1 : v.health} max={maxHealth} />
      </span>
      <span style={{ ...S.low, ...S.clip }}>{v.hungry > 0 && !v.dying ? <span style={{ color: C.red }}>Hungry · </span> : null}{live?.doing ?? 'Idle'}</span>
      {way?.length > 0 && <span style={{ ...S.clip, fontSize: 11, color: C.low }} title="Their way: what they keep doing on days without a council, first need first">{way.join(' → ')}</span>}
    </button>
  )
}

function PersonCard({ v, live, maxHealth, onClose, way, goals }) {
  const inv = Object.entries(live?.inv ?? v.inv ?? {}).filter(([, n]) => n > 0)
  const energy = live?.energy ?? v.energy
  return (
    <div className="hv-panel" style={S.card}>
      <div style={S.row}>
        <strong style={{ fontSize: 15 }}>{v.name}</strong>
        <Hearts value={v.health} max={maxHealth} />
        <button type="button" aria-label="Close" onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 0, color: C.low, cursor: 'pointer', font: 'inherit' }}>✕</button>
      </div>
      <div style={S.low}>{v.trait}</div>
      <div style={S.row}><span style={S.low}>Energy {energy}/10</span><Meter value={energy} max={10} /></div>
      {v.thought && <div style={{ ...S.mid, fontStyle: 'italic' }}>"{v.thought}"</div>}
      {inv.length > 0 && <div style={S.mid}>Carrying {inv.map(([k, n]) => `${n} ${k}`).join(', ')}</div>}
      {(v.skills ?? []).length > 0 && <div style={S.low}>Knows {v.skills.join(', ')}</div>}
      {way?.length > 0 && <div style={S.low} title="A council can change this. It costs nothing to follow.">Way: {way.map(g => goals?.[g] ?? g).join(', then ')}</div>}
      {(v.feedback ?? []).slice(0, 3).map((f, i) => <div key={i} style={S.low}>{f}</div>)}
    </div>
  )
}

// What everyone is doing, counted: the first word of each villager's current activity.
function activity(doing) {
  const word = String(doing ?? 'Idle').split(' ')[0]
  return word === "Can't" ? 'Stuck' : word
}

function PeopleTab({ world, live, selected, onPick, dusk }) {
  const everyone = world?.villagers ?? []
  const alive = everyone.filter(v => !v.dying)
  const hungry = alive.filter(v => v.hungry > 0).length
  const counts = {}
  for (const v of alive) {
    const what = activity(live?.villagers?.[v.name]?.doing)
    counts[what] = (counts[what] ?? 0) + 1
  }
  return (
    <>
      <div style={S.mid}>
        <strong style={{ color: C.text, fontSize: 15 }}>{alive.length}</strong> named {alive.length === 1 ? 'villager' : 'villagers'}
        {hungry > 0 && <span style={{ color: C.red }}> · {hungry} hungry</span>}
      </div>
      {alive.length > 0 && <div style={S.low}>{Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(' · ')}</div>}
      <div style={S.low}>Each follows a way of life for free. A council lets them rethink it.</div>
      {(world?.folk ?? 0) > 0 && <div style={S.mid}><strong style={{ color: C.text }}>{big(world.folk)}</strong> folk live and work around them, in homes for {big(world.homes)}.</div>}
      <div style={S.h}>Villagers</div>
      {everyone.map(v => (
        <Person key={v.name} v={v} live={live?.villagers?.[v.name]} selected={selected === v.name} onSelect={onPick}
          gone={!!v.dying && dusk} maxHealth={world?.max_health ?? 5} way={world?.ways?.[v.name]} />
      ))}
    </>
  )
}

function Item({ title, note, tip, children }) {
  return (
    <div title={tip}>
      <div style={{ ...S.row, justifyContent: 'space-between' }}><strong style={S.clip}>{title}</strong>{children}</div>
      {note && <div style={S.low}>{note}</div>}
    </div>
  )
}

const big = n => {
  n = Number(n) || 0
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`
  if (n >= 1e4) return `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k`
  return Math.round(n).toLocaleString('en-US')
}

const NODE_W = 132
const NODE_H = 62
const TREE_W = 600

// Ideas laid out as a tree: one row per era, each idea under what it builds on.
function treeLayout(ideas, eras) {
  const rows = eras.map(era => Object.keys(ideas).filter(k => ideas[k].era === era)).filter(r => r.length)
  const at = {}
  let y = 0
  const bands = []
  rows.forEach(row => {
    const lines = Math.ceil(row.length / 4)
    bands.push({ era: ideas[row[0]].era, y })
    y += 22
    for (let l = 0; l < lines; l++) {
      const part = row.slice(l * 4, l * 4 + 4)
      const gap = (TREE_W - part.length * NODE_W) / (part.length + 1)
      part.forEach((k, i) => { at[k] = { x: gap + i * (NODE_W + gap), y } })
      y += NODE_H + 26
    }
  })
  return { at, bands, height: y }
}

function IdeasTab({ guide, idle, run, api, eras }) {
  const { at, bands, height } = useMemo(() => treeLayout(guide.ideas, eras ?? []), [guide.ideas, eras])
  const boosts = idea => Object.entries(idea.boost ?? {}).filter(([k]) => k !== 'fish' && k !== 'water_range').map(([k, n]) => `×${n} ${k}`).join(' · ')
  return (
    <>
      <div style={{ ...S.row, justifyContent: 'space-between' }}>
        <span style={S.low}>Plant an idea with Insight. They still have to work it out, and each one changes what the whole village can do.</span>
        <Btn on={guide.auto} disabled={idle} title="Plant the cheapest idea within reach each day, even while you are away" onClick={() => void run('auto', () => api.auto(!guide.auto))}>{guide.auto ? 'Auto on' : 'Auto off'}</Btn>
      </div>
      <div style={{ position: 'relative', width: TREE_W, height, flexShrink: 0 }}>
        <svg width={TREE_W} height={height} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
          {Object.entries(guide.ideas).flatMap(([key, idea]) => idea.needs.filter(n => at[n] && at[key]).map(n => {
            const x1 = at[n].x + NODE_W / 2, y1 = at[n].y + NODE_H, x2 = at[key].x + NODE_W / 2, y2 = at[key].y
            const lit = guide.known.includes(n)
            return <path key={`${n}-${key}`} d={`M${x1},${y1} C${x1},${y1 + 18} ${x2},${y2 - 18} ${x2},${y2}`} fill="none" stroke={lit ? C.gold : C.line} strokeWidth={lit ? 2 : 1.5} opacity={lit ? 0.9 : 1} />
          }))}
        </svg>
        {bands.map(b => <div key={b.era} style={{ ...S.h, position: 'absolute', left: 0, top: b.y, color: b.era === guide.era ? C.gold : C.low }}>{b.era}</div>)}
        {Object.entries(guide.ideas).map(([key, idea]) => {
          const known = guide.known.includes(key)
          const planted = guide.planted.includes(key)
          const ready = idea.needs.every(n => guide.known.includes(n))
          const can = ready && !planted && guide.insight >= idea.cost
          const tries = guide.attempts?.[key] ?? 0
          return (
            <button key={key} type="button" className="hv-card" data-selected={known ? 'true' : undefined} disabled={idle || !can}
              title={`${idea.hint}. ${idea.history}`} onClick={() => void run('plant', () => api.plant(key))}
              style={{ position: 'absolute', left: at[key].x, top: at[key].y, width: NODE_W, height: NODE_H, boxSizing: 'border-box', padding: '5px 7px', textAlign: 'left', font: 'inherit', color: C.text, borderRadius: 8, borderWidth: 1, borderStyle: 'solid',
                borderColor: known ? C.gold : can ? C.text : C.line, background: 'var(--hv-node, #10131c)', zIndex: 1, opacity: known || planted || ready ? 1 : 0.5, cursor: can ? 'pointer' : 'default', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <span style={{ ...S.row, justifyContent: 'space-between', gap: 4 }}>
                <strong style={{ ...S.clip, fontSize: 12 }}>{idea.name}</strong>
                <span style={{ fontSize: 11, color: known ? C.green : planted ? C.gold : can ? C.gold : C.low, whiteSpace: 'nowrap' }}>{known ? '✓' : planted ? `trying${tries ? ` ${tries}` : ''}` : idea.cost}</span>
              </span>
              <span style={{ fontSize: 10.5, lineHeight: 1.2, color: C.mid, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{boosts(idea) || idea.unlocks}</span>
            </button>
          )
        })}
      </div>
    </>
  )
}

function UpgradesTab({ guide, idle, run, api }) {
  return Object.entries(guide.upgrades_for_sale).map(([key, u]) => (
    <Item key={key} title={u.name} note={u.effect}>
      {guide.upgrades.includes(key)
        ? <span style={{ ...S.low, color: C.green }}>Owned</span>
        : <Btn disabled={idle || guide.insight < u.cost} onClick={() => void run('upgrade', () => api.upgrade(key))}>Buy · {u.cost}</Btn>}
    </Item>
  ))
}

function LegacyTab({ legacy, idle, run, api }) {
  if (!legacy) return null
  return (
    <>
      <div style={S.mid}><strong style={{ color: C.gold }}>{legacy.points}</strong> Legacy to spend. Starting a new village banks {legacy.would_earn} more.</div>
      {Object.entries(legacy.perks_for_sale).map(([key, p]) => (
        <Item key={key} title={p.name} note={p.effect}>
          {legacy.perks.includes(key)
            ? <span style={{ ...S.low, color: C.green }}>Owned</span>
            : <Btn disabled={idle || legacy.points < p.cost} onClick={() => void run('perk', () => api.perk(key))}>Buy · {p.cost}</Btn>}
        </Item>
      ))}
      {(legacy.villages ?? []).length > 0 && <div style={S.h}>Past villages</div>}
      {(legacy.villages ?? []).map((v, i) => (
        <div key={i} style={S.low}>{v.days} days, {v.era}, {v.dead} lost, {v.fallen ? 'fell' : 'left behind'}, +{v.earned}</div>
      ))}
    </>
  )
}

function BuildTab({ buildings, built }) {
  return Object.entries(buildings ?? {}).map(([name, b]) => {
    const have = (built ?? []).filter(x => x.kind === name).length
    const cost = Object.entries(b.cost ?? {}).map(([k, n]) => `${n} ${k}`).join(', ')
    return (
      <Item key={name} title={name.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())} note={`${cost}. ${b.effect}`}>
        <span style={S.low}>{have}/{b.max}</span>
      </Item>
    )
  })
}

function StoryTab({ story, log }) {
  return (
    <>
      {(story ?? []).map((n, i) => (
        <div key={`${n.day}-${i}`} style={{ display: 'flex', gap: 8 }}>
          <span style={{ ...S.low, flex: '0 0 44px' }}>Day {n.day}</span>
          <span style={{ color: DARK.test(n.text) ? C.red : C.text }}>{n.text}</span>
        </div>
      ))}
      {log?.length > 0 && <div style={{ ...S.h, marginTop: 6 }}>Recent days</div>}
      <LogTab log={log} />
    </>
  )
}

function LogTab({ log }) {
  return [...(log ?? [])].reverse().map((d, i) => (
    <details key={`${d.day}-${i}`}>
      <summary style={{ cursor: 'pointer' }}>Day {d.day} <span style={S.low}>{d.source === 'model' ? 'council' : 'free day'}{d.rejected ? ` · ${d.rejected} failed` : ''}</span></summary>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 0 0 8px' }}>
        {(d.events ?? []).map(e => <div key={e}><strong>{plain(e)}</strong></div>)}
        {(d.villagers ?? []).map(vl => (
          <div key={vl.name}>
            <strong>{vl.name}</strong>
            {vl.thought && <div style={{ ...S.mid, fontStyle: 'italic' }}>"{vl.thought}"</div>}
            {(vl.steps ?? []).map((st, j) => <div key={j} style={st.ok ? S.mid : S.low}>{st.ok ? '✓' : '✗'} {plain(st.result ?? st.action?.verb)}</div>)}
          </div>
        ))}
      </div>
    </details>
  ))
}

const DARK = /died of|has fallen|fire went out/
const plain = text => String(text ?? '').replace(/lean_to/g, 'lean-to').replace(/_/g, ' ')

// The rules speak in tiles. Nobody playing thinks in coordinates, so a walk is told by where it ends.
function feedText(text, camp) {
  const walk = /^walked to \((-?\d+),(-?\d+)\)/.exec(text ?? '')
  if (!walk || !camp) return plain(text).replace(/ (of|at|near) \(-?\d+,-?\d+\)/g, '')
  const dx = Number(walk[1]) - camp[0]
  const dy = Number(walk[2]) - camp[1]
  const far = Math.round(Math.hypot(dx, dy))
  if (far <= 3) return 'walked back to camp'
  const side = (Math.abs(dy) > Math.abs(dx) * 2 ? '' : dx > 0 ? 'east' : 'west')
  const facing = (Math.abs(dx) > Math.abs(dy) * 2 ? '' : dy > 0 ? 'south' : 'north') + side
  return `walked ${far} tiles ${facing || side} of camp`
}

// How long until the year turns against them, worked out from the calendar the page already has.
function outlook(world) {
  const days = world.season_days
  if (!days || !world.day) return null
  const year = days * 4
  const today = (world.day - 1) % year
  const winter = days * 3
  if (today >= winter) { const left = year - today; return { text: `Winter: ${left} ${left === 1 ? 'day' : 'days'} to go`, bad: true } }
  const until = winter - today
  return { text: `Winter in ${until} ${until === 1 ? 'day' : 'days'}`, bad: until <= days }
}

function fmtItems(o) {
  return Object.entries(o ?? {}).filter(([, n]) => n > 0).map(([k, n]) => `+${n} ${k}`).join(', ')
}

function Resources({ res, people, world, folk }) {
  if (!res) return null
  const ahead = outlook(world)
  const meals = people > 0 ? Math.floor(res.held.food / people) : 0
  const herds = {}
  for (const h of res.herds ?? []) herds[h.kind] = (herds[h.kind] ?? 0) + h.count
  const animals = Object.entries(herds).map(([k, n]) => `${n} ${k}`).join(', ')
  const rows = [
    ['Food', res.held.food, `${res.wild.food} wild`, res.held.food < people * 2],
    ['Wood', res.held.wood, `${res.wild.wood} left`, res.wild.wood < 10],
    ['Stone', res.held.stone, res.wild.stone > 0 ? 'plenty' : 'none found', false]
  ]
  const stored = Object.entries(res.stored ?? {}).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k}`).join(', ')
  return (
    <div className="hv-panel" style={S.stock} title={`Camp store: ${stored || 'empty'}`}>
      {rows.map(([name, held, wild, low]) => (
        <div key={name} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ ...S.low, width: 40 }}>{name}</span>
          <strong style={{ color: low ? C.red : C.text, minWidth: 22, textAlign: 'right' }}>{held}</strong>
          <span style={{ ...S.low, whiteSpace: 'nowrap' }}>{wild}</span>
        </div>
      ))}
      <div style={{ ...S.low, whiteSpace: 'nowrap' }}>{animals ? `Seen: ${animals}` : 'No animals found'}</div>
      {res.fire_out && <div style={{ color: C.red, fontSize: 12 }}>The fire is out</div>}
      {ahead && <div style={{ fontSize: 12, marginTop: 3, color: ahead.bad ? C.gold : C.mid, whiteSpace: 'nowrap' }}>{ahead.text}</div>}
      <div style={{ fontSize: 12, color: meals < 2 ? C.red : C.mid, whiteSpace: 'nowrap' }} title="Food held, divided by everyone alive">Food lasts {meals} {meals === 1 ? 'day' : 'days'}</div>
      {folk?.folk > 0 && (
        <div style={{ fontSize: 12, marginTop: 3, color: C.mid, whiteSpace: 'nowrap' }} title="What the folk gathered yesterday, working the land around the store">
          Folk brought <span style={{ color: C.green }}>+{big(folk.food)}</span> food, <span style={{ color: C.green }}>+{big(folk.wood)}</span> wood
          <div>Homes {big(folk.folk)} / {big(folk.homes)}{folk.built?.length ? ` · built ${folk.built.length}` : ''}</div>
        </div>
      )}
    </div>
  )
}

const TABS = [['people', '☺', 'People'], ['ideas', '✦', 'Tree'], ['upgrades', '▲', 'Upgrades'], ['legacy', '◆', 'Legacy'], ['build', '⌂', 'Build'], ['speak', '✎', 'Speak'], ['story', '≡', 'Story'], ['settings', '⚙', 'Settings']]

const SKINS = [['print', 'Colour print'], ['ink', 'Blue ink'], ['ps1', 'PS1 blue'], ['wood', 'RPG wood']]

function remembered(key) {
  try { return localStorage.getItem(key) } catch { return null }
}

function remember(key, value) {
  try { localStorage.setItem(key, value) } catch { /* it just won't be remembered */ }
}

function Welcome({ onBegin }) {
  return (
    <div className="hv-panel" style={S.welcome}>
      <strong style={{ fontSize: 17 }}>You are not their god.</strong>
      <div>Ash, Bryn and Coll are three people at the start of history. Hermes plays them: they think, argue and decide for themselves. You can only guide.</div>
      <div style={S.mid}><strong style={{ color: C.text }}>Focus</strong> urges them on free days, if they trust you.</div>
      <div style={S.mid}><strong style={{ color: C.text }}>Ideas</strong> cost Insight and plant a thought. They still have to work it out.</div>
      <div style={S.mid}><strong style={{ color: C.text }}>Hold council</strong> makes one model call: they plan tomorrow and rethink their way of life, which they then follow for free.</div>
      <div style={S.mid}>Around them the folk multiply as homes and food allow, clearing the land as they go. It keeps growing while you are away.</div>
      <div style={S.mid}>Everything is limited and winter kills. The land has no edge and starts dark, so what they need next is always further away.</div>
      <div><Btn primary onClick={onBegin}>Begin</Btn></div>
    </div>
  )
}

function savedSkin() {
  try {
    const value = localStorage.getItem('hermes-village.skin')
    return SKINS.some(([key]) => key === value) ? value : 'print'
  } catch {
    return 'print'
  }
}

export function VillagePage({ ctx, skin: startSkin }) {
  const api = useMemo(() => makeApi(ctx), [ctx])
  const [world, setWorld] = useState(null)
  const [budget, setBudget] = useState(null)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState('')
  const [selected, setSelected] = useState(null)
  const [guideText, setGuideText] = useState('')
  const [budgetText, setBudgetText] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const boxRef = useRef(null)
  const sceneRef = useRef(null)
  const [legacy, setLegacy] = useState(null)
  const [story, setStory] = useState([])
  const [welcome, setWelcome] = useState(() => !remembered('hermes-village.welcomed'))
  const [sound, setSound] = useState(() => remembered('hermes-village.sound') === 'on')
  const soundRef = useRef(null)
  const miniCanvas = useRef(null)
  const miniRef = useRef(null)
  const selectedRef = useRef(null)
  const cued = useRef('')
  const [tab, setTab] = useState(null)
  const [skin, setSkin] = useState(() => startSkin ?? savedSkin())
  const chooseSkin = key => {
    setSkin(key)
    try { localStorage.setItem('hermes-village.skin', key) } catch { /* the choice just won't persist */ }
  }
  const mounted = useRef(true)
  const worldRef = useRef(null)
  const offsetRef = useRef(0) // serverNow - Date.now()/1000
  const lastFetch = useRef(0)
  const liveSig = useRef('')
  const [live, setLive] = useState(null)

  // the scene passes the world it is drawing, so a new day's clock can never meet the old day's data
  const getClock = useCallback((w = worldRef.current) => clockAt(w, Date.now() / 1000 + offsetRef.current), [])

  // live card/feed values from the replay, sampled at ~4 Hz (never per frame)
  const sampleLive = useCallback(() => {
    const w = worldRef.current
    if (!w || !mounted.current) return
    const clock = getClock()
    const spd = w.slots_per_day ?? 8
    const entries = new Map((w.current?.villagers ?? []).map(e => [e.name, e]))
    const villagers = {}
    for (const vi of w.villagers ?? []) {
      const e = entries.get(vi.name)
      const pose = e ? poseAt(e, clock.slot, spd) : idlePose(vi)
      villagers[vi.name] = { x: Math.round(pose.x), y: Math.round(pose.y), energy: pose.energy, inv: pose.inv, doing: describePose(pose) }
    }
    const next = { dayT: Math.round(clock.dayT * 500) / 500, phase: clock.phase, evening: clock.evening, villagers, feed: feedAt(w, clock.slot, 6) }
    const sig = JSON.stringify(next)
    if (sig !== liveSig.current) { liveSig.current = sig; setLive(next) }
    miniRef.current?.draw(w, villagers, sceneRef.current?.lookingAt(), selectedRef.current)
    soundRef.current?.tick({ phase: clock.phase, season: w.season, paused: !!w.paused_at })
    if (clock.evening) { // the bell goes when the day's report is read out, not when the day was worked out
      const said = (w.current?.events ?? []).join('|')
      const mark = `${w.day}:${said}`
      if (mark !== cued.current) {
        cued.current = mark
        if (/died of/.test(said)) soundRef.current?.cue('death')
        else if (/worked out|has begun/.test(said)) soundRef.current?.cue('learn')
      }
    }
  }, [getClock])

  const apply = useCallback(res => {
    if (!mounted.current || !res) return
    if (res.world) {
      if (typeof res.world.now === 'number') offsetRef.current = res.world.now - Date.now() / 1000
      // the land changes once a day at most, so most polls leave it out and this keeps what we hold
      const next = res.world.land_view ? res.world : { ...res.world, land_view: worldRef.current?.land_view }
      worldRef.current = next
      setWorld(next)
      sampleLive()
    }
    if (res.budget) setBudget(res.budget)
    if (res.legacy) setLegacy(res.legacy)
    if (res.chronicle) setStory(res.chronicle)
  }, [sampleLive])

  const refresh = useCallback(async () => {
    lastFetch.current = Date.now()
    try {
      apply(await api.state(worldRef.current?.land_view?.rev))
      if (mounted.current) setError('')
    } catch (e) {
      if (mounted.current) setError(errText(e))
    }
  }, [api, apply])

  const run = useCallback(async (label, fn) => {
    setBusy(label)
    setError('')
    try {
      const res = await fn()
      apply(res)
      return res
    } catch (e) {
      if (mounted.current) setError(errText(e))
    } finally {
      if (mounted.current) setBusy('')
    }
  }, [apply])

  // mount: initial fetch, live event, visibility-aware poll
  useEffect(() => {
    mounted.current = true
    void refresh()
    const offEvent = ctx.onEvent?.('plugin.hermes-village.state.updated', () => { void refresh() })
    let tick = 0
    const timer = ctx.setInterval(() => {
      if (!mounted.current || document.visibilityState !== 'visible') return
      tick++
      sampleLive()
      const w = worldRef.current
      const dayOver = w && !w.paused_at && getClock().dayT >= 1
      // the server only starts the next day when /state is fetched: ask when the clock runs out
      if (dayOver && Date.now() - lastFetch.current >= (w.speed > 2 ? 400 : 2000)) void refresh()
      else if (tick % 20 === 0) void refresh()
    }, 250)
    return () => {
      mounted.current = false
      if (typeof offEvent === 'function') offEvent()
      if (typeof timer === 'function') timer()
      else if (timer != null) ctx.clearInterval?.(timer)
    }
  }, [ctx, refresh, sampleLive, getClock])

  // 3D scene lifecycle
  useEffect(() => {
    if (!boxRef.current) return undefined
    let sc
    try {
      sc = createScene(boxRef.current, { onPick: name => setSelected(s => (s === name ? null : name)) })
    } catch (e) {
      setError(`3D view unavailable: ${errText(e)}`)
      return undefined
    }
    sceneRef.current = sc
    if (worldRef.current) sc.setPlayback(worldRef.current, getClock)
    return () => { sceneRef.current = null; sc.dispose() }
  }, [getClock])

  useEffect(() => { if (world) sceneRef.current?.setPlayback(world, getClock) }, [world, getClock])
  useEffect(() => { selectedRef.current = selected; sceneRef.current?.select(selected) }, [selected])
  useEffect(() => { sceneRef.current?.setInk(skin === 'ink' || skin === 'print' ? skin : false) }, [skin, world?.land_id])

  useEffect(() => {
    if (!miniCanvas.current) return undefined
    const mini = createMinimap(miniCanvas.current, (x, y) => sceneRef.current?.lookAt(x, y))
    miniRef.current = mini
    return () => { miniRef.current = null; mini.dispose() }
  }, [])

  useEffect(() => {
    const s = createSound()
    soundRef.current = s
    return () => { soundRef.current = null; s.dispose() }
  }, [])

  // a browser will not start audio on its own, so a remembered "on" waits for the first press
  useEffect(() => {
    if (!sound) { soundRef.current?.set(false); return undefined }
    const begin = () => soundRef.current?.set(true)
    begin()
    window.addEventListener('pointerdown', begin, { once: true })
    return () => window.removeEventListener('pointerdown', begin)
  }, [sound])

  const toggleSound = () => setSound(on => {
    remember('hermes-village.sound', on ? 'off' : 'on')
    return !on
  })

  const goHome = useCallback(() => {
    const camp = worldRef.current?.camp
    if (camp) sceneRef.current?.lookAt(camp[0], camp[1])
  }, [])

  // RimWorld's keys. They only count while the page has the focus, so typing in chat is never caught.
  useEffect(() => {
    const onKey = e => {
      const at = e.target
      if (e.ctrlKey || e.metaKey || e.altKey || at?.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(at?.tagName ?? '')) return
      if (!(at === document.body || boxRef.current?.closest('.hv')?.contains(at))) return
      const w = worldRef.current
      if (!w) return
      const go = n => void run('speed', () => api.speed(n))
      if (e.code === 'Space') go(w.paused_at ? w.speed : 0)
      else if (/^Digit[1-5]$/.test(e.code) && w.speeds?.[Number(e.code.slice(5)) - 1]) go(w.speeds[Number(e.code.slice(5)) - 1])
      else if (e.key === 'c' || e.key === 'C') goHome()
      else if (e.key === 'f' || e.key === 'F') sceneRef.current?.watch()
      else if (e.key === 'p' || e.key === 'P') setTab(t => (t === 'people' ? null : 'people'))
      else if (e.key === 'Escape') { setTab(null); setSelected(null) }
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [api, run, goHome])

  useEffect(() => { if (world && guideText === '') setGuideText(world.guidance ?? '') }, [world?.guidance]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (budget) setBudgetText(String(budget.daily_tokens)) }, [budget?.daily_tokens]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSelect = name => setSelected(s => (s === name ? null : name))
  const pickFromList = name => {
    if (selected !== name) {
      const at = live?.villagers?.[name]
      if (at) sceneRef.current?.lookAt(at.x, at.y)
    }
    onSelect(name)
  }

  const planDay = async () => {
    setHint('')
    setError('')
    try {
      const sid = host.state?.focusedSessionId?.get?.()
      if (!sid) throw new Error('no session')
      setBusy('plan')
      await host.request('slash.exec', { session_id: sid, command: '/village plan' })
      await refresh()
      setBusy('')
      return
    } catch {
      setBusy('')
    }
    try {
      await host.composer.setDraft(null, '/village plan')
      host.composer.focus?.(null)
      setHint('Press Enter in chat to let the villagers plan (uses model tokens)')
    } catch {
      setHint('Type /village plan in chat')
    }
  }

  const saveBudget = () => {
    const n = Math.round(Number(budgetText))
    if (!Number.isFinite(n) || n < 0) { setError('Enter a non-negative number of tokens'); return }
    void run('budget', () => api.budget(n))
  }

  const lastCall = budget?.last_call
  const plans = budget?.calls_today ?? 0
  const estLabel = budget ? ` · ~${fmtTokens(budget.est_call_tokens)}` : ''
  const planning = !!budget?.planning
  const away = world?.away
  const wf = world?.work_fraction ?? 0.85

  const guide = world?.guide
  const idle = busy !== ''
  const spd = world?.season ? `${world.season[0].toUpperCase()}${world.season.slice(1)}` : ''
  const tokensLeft = budget ? `${fmtTokens(budget.used_today)} / ${fmtTokens(budget.daily_tokens)}` : '-'
  const reasons = world?.council_reasons ?? []
  const shown = (world?.villagers ?? []).find(v => v.name === selected)
  const dusk = !!live?.evening
  const paused = !!world?.paused_at
  const alive = (world?.villagers ?? []).filter(v => !v.dying)
  const hungry = alive.filter(v => v.hungry > 0).length
  const fs = world?.folk_stats
  const change = fs ? (fs.born ?? 0) - (fs.starved ?? 0) : 0
  const affordable = guide ? Object.entries(guide.ideas).some(([k, i]) => !guide.planted.includes(k) && i.needs.every(n => guide.known.includes(n)) && guide.insight >= i.cost) : false

  return (
    <div className="hv" data-skin={skin === 'print' ? 'ink' : skin} style={S.root}>
      <style>{SKIN_CSS}</style>
      <div ref={boxRef} style={S.canvas} />

      <div className="hv-panel" style={S.top}>
        <strong style={{ fontSize: 15, whiteSpace: 'nowrap' }}>{world ? `${world.settlement ?? 'Camp'} · Day ${world.day ?? '-'}` : 'Loading…'}</strong>
        <span className="hv-w3" style={{ ...S.low, whiteSpace: 'nowrap' }}>{spd}{live?.phase ? ` · ${live.phase}` : ''}{paused ? ' · Paused' : ''}</span>
        <DayBar dayT={live?.dayT} wf={wf} />
        {world && (
          <button type="button" onClick={() => setTab(t => (t === 'people' ? null : 'people'))} title={`${alive.length} villagers and ${(world.folk ?? 0).toLocaleString('en-US')} folk, with homes for ${(world.homes ?? 0).toLocaleString('en-US')}. Open People (P)`}
            style={{ ...S.stat, background: 'none', border: 0, padding: 0, color: C.text, font: 'inherit', cursor: 'pointer' }}>
            <strong style={{ fontSize: 19, color: hungry ? C.red : C.gold }}>{big(world.population ?? alive.length)}</strong><span className="hv-w2" style={S.low}>people</span>
            {change !== 0 && <span className="hv-w2" style={{ fontSize: 12, color: change > 0 ? C.green : C.red }}>{change > 0 ? '+' : ''}{big(change)}/day</span>}
          </button>
        )}
        {guide && <span className="hv-w2" style={{ ...S.low, whiteSpace: 'nowrap' }}>{guide.era}</span>}
        {guide && <span style={S.stat} title="Earned as the village lives and learns. Spend it on ideas and upgrades."><strong style={{ color: C.gold, fontSize: 15 }}>{guide.insight}</strong><span style={S.low}>Insight</span></span>}
        {guide && (
          <span style={S.stat} title={guide.trust < guide.trust_heeded ? 'They ignore your focus on free days. Good advice wins them back.' : 'They follow your focus on free days.'}>
            <strong style={{ color: guide.trust < guide.trust_heeded ? C.red : C.text }}>{guide.trust}</strong><span style={S.low}>Trust</span><Meter value={guide.trust} max={100} width={36} color={guide.trust < guide.trust_heeded ? C.red : C.gold} />
          </span>
        )}
        <span className="hv-w1" style={S.stat} title={lastCall?.model ? `Last council used ${lastCall.model}` : 'Model tokens used today'}><strong>{tokensLeft}</strong><span style={S.low}>tokens · {plans} {plans === 1 ? 'council' : 'councils'}</span></span>
      </div>

      <div style={S.left}>
        <Resources res={world?.resources} world={world} people={world?.population ?? alive.length} folk={fs} />
        <div className="hv-feed" style={S.feed}>
          {dusk && (world?.current?.events ?? []).map(e => <strong key={e} style={{ color: DARK.test(e) ? C.red : C.gold }}>{plain(e)}</strong>)}
          {(live?.feed ?? []).slice(0, 3).map((f, i) => (
            <div key={`${i}-${f.name}-${f.text}`} style={{ opacity: f.ok ? 0.95 - i * 0.2 : 0.6 }}><strong>{f.name}</strong> {f.ok ? '' : '✗ '}{feedText(f.text, world?.camp)}</div>
          ))}
        </div>
      </div>

      <div className="hv-panel hv-mini" style={{ ...S.mini, display: tab ? 'none' : undefined }} title="What they have seen. Click to look there.">
        <canvas ref={miniCanvas} width={MINIMAP_SIZE} height={MINIMAP_SIZE} style={{ width: MINIMAP_SIZE, height: MINIMAP_SIZE, borderRadius: 6, cursor: 'pointer' }} />
      </div>

      <div className="hv-panel" style={S.rail}>
        {TABS.map(([key, icon, label]) => (
          <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(t => (t === key ? null : key))}
            style={{ position: 'relative', background: tab === key ? 'rgba(230, 180, 80, 0.16)' : 'none', color: tab === key ? C.gold : C.mid, border: 0, borderRadius: 7, padding: '6px 0 5px', cursor: 'pointer', font: 'inherit', fontSize: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
            <span style={{ fontSize: 15, lineHeight: 1 }}>{icon}</span>{label}
            {key === 'ideas' && affordable && <span style={{ position: 'absolute', top: 5, right: 12, width: 6, height: 6, borderRadius: 3, background: C.gold }} />}
            {key === 'people' && hungry > 0 && <span style={{ position: 'absolute', top: 5, right: 12, width: 6, height: 6, borderRadius: 3, background: C.red }} />}
          </button>
        ))}
      </div>

      {tab && guide && (
        <div className="hv-panel" style={{ ...S.drawer, ...(tab === 'ideas' ? { width: TREE_W + 26 } : null) }}>
          <div style={{ ...S.row, padding: '10px 12px 6px', justifyContent: 'space-between' }}>
            <strong>{TABS.find(t => t[0] === tab)[2]}</strong>
            <button type="button" aria-label="Close" onClick={() => setTab(null)} style={{ background: 'none', border: 0, color: C.low, cursor: 'pointer', font: 'inherit' }}>✕</button>
          </div>
          <div style={S.drawerBody}>
            {tab === 'people' && <PeopleTab world={world} live={live} selected={selected} onPick={pickFromList} dusk={dusk} />}
            {tab === 'ideas' && <IdeasTab guide={guide} idle={idle} run={run} api={api} eras={world?.eras} />}
            {tab === 'upgrades' && <UpgradesTab guide={guide} idle={idle} run={run} api={api} />}
            {tab === 'legacy' && <LegacyTab legacy={legacy} idle={idle} run={run} api={api} />}
            {tab === 'build' && <BuildTab buildings={world?.buildings} built={world?.built} />}
            {tab === 'story' && <StoryTab story={story.filter(n => dusk || n.day < (world?.current?.day ?? Infinity))} log={world?.log} />}
            {tab === 'speak' && (
              <>
                <div style={S.low}>Tell the villagers what you think. They hear it at the next council, and may disagree.</div>
                <textarea style={S.input} value={guideText} onChange={e => setGuideText(e.target.value)} placeholder="Store food before winter…" maxLength={300} rows={4} />
                <div><Btn disabled={idle} onClick={() => void run('guide', () => api.guide(guideText.trim()))}>Say it</Btn></div>
                {world?.guidance ? <div style={S.low}>They last heard: {world.guidance}</div> : null}
              </>
            )}
            {tab === 'settings' && (
              <>
                <div style={S.h}>Look</div>
                <div style={S.row}>
                  {SKINS.map(([key, label]) => <Btn key={key} on={skin === key} onClick={() => chooseSkin(key)}>{label}</Btn>)}
                </div>
                <div style={S.h}>Sound</div>
                <div><Btn on={sound} onClick={toggleSound}>{sound ? 'Sound on' : 'Sound off'}</Btn></div>
                <div style={S.h}>Keys</div>
                <div style={S.low}>Space pauses, 1 to 5 set the speed, P shows people, C goes to camp, F follows, Esc closes.</div>
                <div style={S.h}>Daily token limit</div>
                <div style={S.row}>
                  <input type="number" min="0" step="1000" style={S.input} value={budgetText} onChange={e => setBudgetText(e.target.value)} />
                  <Btn disabled={idle} onClick={saveBudget}>Save</Btn>
                </div>
                <div style={S.h}>This village</div>
                {confirmReset ? (
                  <div style={S.row}>
                    <Btn primary disabled={idle} onClick={() => { setConfirmReset(false); setSelected(null); setGuideText(''); void run('reset', () => api.reset()) }}>End it, bank {legacy?.would_earn ?? 0} Legacy</Btn>
                    <Btn onClick={() => setConfirmReset(false)}>Cancel</Btn>
                  </div>
                ) : <div><Btn disabled={idle} onClick={() => setConfirmReset(true)}>New village</Btn></div>}
              </>
            )}
          </div>
        </div>
      )}

      {shown && !(shown.dying && dusk) && <PersonCard v={shown} live={live?.villagers?.[shown.name]} maxHealth={world?.max_health ?? 5} onClose={() => setSelected(null)} way={world?.ways?.[shown.name]} goals={world?.way_goals} />}

      {world?.fallen && dusk && (
        <div className="hv-panel" style={S.welcome}>
          <strong style={{ fontSize: 17 }}>The village has fallen.</strong>
          <div style={S.mid}>{world.settlement ?? 'The camp'} lasted {world.fallen} {world.fallen === 1 ? 'day' : 'days'} and never got past the {guide?.era ?? 'Stone Age'}.</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 220, overflowY: 'auto' }}>
            {story.map((n, i) => <div key={`${n.day}-${i}`} style={{ display: 'flex', gap: 8 }}><span style={{ ...S.low, flex: '0 0 48px' }}>Day {n.day}</span><span style={{ color: DARK.test(n.text) ? C.red : C.text }}>{n.text}</span></div>)}
          </div>
          <div><Btn primary disabled={idle} onClick={() => { setSelected(null); setGuideText(''); void run('reset', () => api.reset()) }}>Start again · bank {legacy?.would_earn ?? 0} Legacy</Btn></div>
        </div>
      )}

      {away && !world?.fallen && (
        <div className="hv-panel" style={S.notice}>
          <div>
            <strong>While you were away: {away.days} days passed</strong>
            {fmtItems(away.gained) && <div style={S.mid}>{fmtItems(away.gained)}</div>}
            {(away.built ?? []).length > 0 && <div style={S.mid}>Built {plain(away.built.join(', '))}</div>}
            {(away.deaths ?? []).map(d => <div key={d.name} style={{ color: C.red }}>{d.name} died of {d.cause}</div>)}
          </div>
          <div><Btn disabled={idle} onClick={() => void run('ack', api.ack)}>OK</Btn></div>
        </div>
      )}

      {welcome && world && <Welcome onBegin={() => { setWelcome(false); remember('hermes-village.welcomed', '1') }} />}

      {(error || hint) && <div role="alert" className="hv-panel" style={{ ...S.notice, top: 'auto', bottom: DOCK + 16, borderColor: error ? C.red : C.line }}>{error || hint}</div>}

      <div className="hv-panel" style={S.dock}>
        <div style={S.bar}>
          <span className="hv-w1" style={S.h}>Focus</span>
          {guide && Object.entries(guide.focuses).map(([key, text]) => (
            <Btn key={key} on={guide.focus === key} disabled={idle || !!world?.fallen} title={`Urge them to ${text}. Judged every ${guide.focus_days} days.`}
              onClick={() => void run('focus', () => api.focus(guide.focus === key ? null : key))}>
              {key[0].toUpperCase() + key.slice(1)}
            </Btn>
          ))}
          <span style={{ flex: 1 }} />
          <span className="hv-w1" style={S.h}>Speed</span>
          <Btn on={paused} disabled={planning} title="Pause" aria-label="Pause" onClick={() => void run('speed', () => api.speed(paused ? world.speed : 0))}>❚❚</Btn>
          {(world?.speeds ?? []).map(n => (
            <Btn key={n} className={n === 2 || n === 8 ? 'hv-w2' : ''} on={!paused && world?.speed === n} disabled={planning} onClick={() => void run('speed', () => api.speed(n))}>{n}x</Btn>
          ))}
          <Btn className="hv-w1" title="Look at the camp (C)" onClick={goHome}>Camp</Btn>
          <Btn className="hv-w1" title="Camera follows the group (F)" onClick={() => sceneRef.current?.watch()}>Follow</Btn>
          <Btn primary disabled={!budget?.can_plan || idle || planning || world?.council_ready || !!world?.fallen} title={world?.council_ready ? 'The council has decided. Its plans start at dawn.' : reasons.length ? reasons.join('; ') : 'One model call plans everyone\'s next day'} onClick={() => void planDay()}>
            {planning ? 'Council meeting…' : world?.council_ready ? 'Plans set for dawn' : <>Hold council<span className="hv-w1">{estLabel}</span></>}{reasons.length && !world?.council_ready ? ' •' : ''}
          </Btn>
        </div>
      </div>
    </div>
  )
}
