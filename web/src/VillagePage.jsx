import * as sdk from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { makeApi, errText, fmtTokens } from './api.js'
import { createScene } from './scene.js'
import { SKIN_CSS } from './skins.js'
import { poseAt, idlePose, describePose, feedAt, clockAt } from './playback.js'

const { host } = sdk

// The page is always dark: the village fills the view and everything else docks around it.
const C = {
  glass: 'rgba(14, 16, 20, 0.86)', solid: '#111317', raised: 'rgba(255, 255, 255, 0.06)', line: 'rgba(255, 255, 255, 0.09)',
  text: '#ece9e2', mid: 'var(--hv-mid, #a9a69e)', low: 'var(--hv-low, #74726b)', gold: '#e6b450', red: '#e8695a', green: '#86c172'
}
const glass = { background: C.glass, backdropFilter: 'blur(10px)', border: `1px solid ${C.line}`, borderRadius: 10 }
const TOP = 46
const DOCK = 130
const RAIL = 62

const S = {
  root: { position: 'relative', width: '100%', height: '100%', minHeight: 420, overflow: 'hidden', background: C.solid, color: C.text, fontSize: 13, lineHeight: 1.35 },
  canvas: { position: 'absolute', inset: 0, overflow: 'hidden' },
  top: { ...glass, position: 'absolute', top: 8, left: 8, right: 8, height: TOP, boxSizing: 'border-box', padding: '0 14px', display: 'flex', alignItems: 'center', gap: 16 },
  stat: { display: 'flex', alignItems: 'baseline', gap: 5, whiteSpace: 'nowrap' },
  rail: { ...glass, position: 'absolute', top: TOP + 16, right: 8, width: RAIL, boxSizing: 'border-box', padding: 4, display: 'flex', flexDirection: 'column', gap: 2 },
  drawer: { ...glass, position: 'absolute', top: TOP + 16, right: RAIL + 16, bottom: DOCK + 16, width: 300, maxWidth: 'calc(100% - 100px)', boxSizing: 'border-box', display: 'flex', flexDirection: 'column' },
  drawerBody: { flex: 1, minHeight: 0, overflowY: 'auto', padding: '4px 12px 12px', display: 'flex', flexDirection: 'column', gap: 10 },
  dock: { ...glass, position: 'absolute', left: 8, right: 8, bottom: 8, height: DOCK, boxSizing: 'border-box', padding: 8, display: 'flex', flexDirection: 'column', gap: 8 },
  people: { display: 'flex', gap: 6, flex: 1, minHeight: 0 },
  person: { flex: '1 1 0', minWidth: 0, background: C.raised, border: `1px solid ${C.line}`, borderRadius: 8, padding: '5px 8px', color: C.text, font: 'inherit', textAlign: 'left', cursor: 'pointer', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 1 },
  bar: { display: 'flex', alignItems: 'center', gap: 6 },
  clip: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  h: { fontSize: 11, fontWeight: 600, letterSpacing: 0.5, textTransform: 'uppercase', color: C.low },
  mid: { color: C.mid },
  low: { color: C.low, fontSize: 12 },
  row: { display: 'flex', gap: 8, alignItems: 'center' },
  stock: { ...glass, position: 'absolute', top: TOP + 16, left: 8, boxSizing: 'border-box', padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 1 },
  feed: { position: 'absolute', top: TOP + 116, left: 12, width: 'min(320px, 45%)', display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12, textShadow: '0 1px 3px rgba(0,0,0,0.9)', pointerEvents: 'none' },
  card: { ...glass, position: 'absolute', left: 8, bottom: DOCK + 16, width: 300, maxWidth: 'calc(100% - 100px)', boxSizing: 'border-box', padding: 12, display: 'flex', flexDirection: 'column', gap: 6 },
  notice: { ...glass, position: 'absolute', top: TOP + 16, left: '50%', transform: 'translateX(-50%)', width: 'min(380px, 60%)', boxSizing: 'border-box', padding: 12, display: 'flex', flexDirection: 'column', gap: 8, borderColor: C.gold },
  input: { width: '100%', boxSizing: 'border-box', background: C.raised, color: C.text, border: `1px solid ${C.line}`, borderRadius: 8, padding: '6px 8px', font: 'inherit', resize: 'none' }
}

function Btn({ primary, on, style, ...props }) {
  const look = primary ? { background: C.gold, color: '#1a1408', borderColor: C.gold, fontWeight: 600 }
    : on ? { background: 'rgba(230, 180, 80, 0.18)', color: C.gold, borderColor: C.gold } : { background: C.raised, color: C.text, borderColor: C.line }
  return (
    <button type="button" {...props} className={`hv-btn${primary ? ' hv-primary' : ''}`} data-on={on ? 'true' : undefined} style={{ font: 'inherit', fontSize: 12, border: '1px solid', borderRadius: 7, padding: '5px 10px', whiteSpace: 'nowrap', cursor: props.disabled ? 'default' : 'pointer', opacity: props.disabled ? 0.4 : 1, ...look, ...style }} />
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
    <span style={{ display: 'inline-block', width, height: 4, borderRadius: 2, background: C.line, overflow: 'hidden', alignSelf: 'center' }}>
      <span style={{ display: 'block', width: `${pct}%`, height: '100%', background: color }} />
    </span>
  )
}

function DayBar({ dayT, wf }) {
  const pct = Math.max(0, Math.min(1, dayT ?? 0)) * 100
  return (
    <div style={{ position: 'relative', flex: 1, minWidth: 40, height: 4, borderRadius: 2, background: C.line }}>
      <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: C.gold, opacity: 0.6 }} />
      <div style={{ position: 'absolute', left: `${wf * 100}%`, top: -2, width: 1, height: 8, background: C.low }} />
    </div>
  )
}

function Person({ v, live, selected, onSelect, gone, maxHealth }) {
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
    </button>
  )
}

function PersonCard({ v, live, maxHealth, onClose }) {
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
      {(v.feedback ?? []).slice(0, 3).map((f, i) => <div key={i} style={S.low}>{f}</div>)}
    </div>
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

function IdeasTab({ guide, idle, run, api }) {
  return (
    <>
      {Object.entries(guide.ideas).map(([key, idea]) => {
        const known = guide.known.includes(key)
        const planted = guide.planted.includes(key)
        const ready = idea.needs.every(n => guide.known.includes(n))
        const tries = guide.attempts?.[key] ?? 0
        return (
          <Item key={key} title={idea.name} note={`Unlocks ${idea.unlocks}`} tip={idea.history}>
            {known && <span style={{ ...S.low, color: C.green }}>Known</span>}
            {!known && planted && <span style={S.low}>Being tried{tries ? ` · ${tries} failed` : ''}</span>}
            {!known && !planted && (ready
              ? <Btn disabled={idle || guide.insight < idea.cost} onClick={() => void run('plant', () => api.plant(key))}>Plant · {idea.cost}</Btn>
              : <span style={S.low}>After {idea.needs.map(n => guide.ideas[n].name).join(', ')}</span>)}
          </Item>
        )
      })}
      <div style={S.low}>Still ahead: {guide.future_eras.join(' → ')}</div>
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

function LogTab({ log }) {
  if (!log?.length) return <div style={S.low}>No days recorded yet.</div>
  return [...log].reverse().map((d, i) => (
    <details key={`${d.day}-${i}`}>
      <summary style={{ cursor: 'pointer' }}>Day {d.day} <span style={S.low}>{d.source === 'model' ? 'council' : 'free day'}{d.rejected ? ` · ${d.rejected} failed` : ''}</span></summary>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '4px 0 0 8px' }}>
        {(d.events ?? []).map(e => <div key={e}><strong>{e}</strong></div>)}
        {(d.villagers ?? []).map(vl => (
          <div key={vl.name}>
            <strong>{vl.name}</strong>
            {vl.thought && <div style={{ ...S.mid, fontStyle: 'italic' }}>"{vl.thought}"</div>}
            {(vl.steps ?? []).map((st, j) => <div key={j} style={st.ok ? S.mid : S.low}>{st.ok ? '✓' : '✗'} {st.result ?? st.action?.verb}</div>)}
          </div>
        ))}
      </div>
    </details>
  ))
}

function fmtItems(o) {
  return Object.entries(o ?? {}).filter(([, n]) => n > 0).map(([k, n]) => `+${n} ${k}`).join(', ')
}

function Resources({ res, people }) {
  if (!res) return null
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
    </div>
  )
}

const TABS = [['ideas', '✦', 'Ideas'], ['upgrades', '▲', 'Upgrades'], ['legacy', '◆', 'Legacy'], ['build', '⌂', 'Build'], ['speak', '✎', 'Speak'], ['log', '≡', 'Log'], ['settings', '⚙', 'Settings']]

const SKINS = [['ps1', 'PS1 blue'], ['wood', 'RPG wood']]

function savedSkin() {
  try {
    const value = localStorage.getItem('hermes-village.skin')
    return SKINS.some(([key]) => key === value) ? value : 'ps1'
  } catch {
    return 'ps1'
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
      sc = createScene(boxRef.current)
    } catch (e) {
      setError(`3D view unavailable: ${errText(e)}`)
      return undefined
    }
    sceneRef.current = sc
    if (worldRef.current) sc.setPlayback(worldRef.current, getClock)
    return () => { sceneRef.current = null; sc.dispose() }
  }, [getClock])

  useEffect(() => { if (world) sceneRef.current?.setPlayback(world, getClock) }, [world, getClock])
  useEffect(() => { sceneRef.current?.select(selected) }, [selected])

  useEffect(() => { if (world && guideText === '') setGuideText(world.guidance ?? '') }, [world?.guidance]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (budget) setBudgetText(String(budget.daily_tokens)) }, [budget?.daily_tokens]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSelect = name => setSelected(s => (s === name ? null : name))

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
  const affordable = guide ? Object.entries(guide.ideas).some(([k, i]) => !guide.planted.includes(k) && i.needs.every(n => guide.known.includes(n)) && guide.insight >= i.cost) : false

  return (
    <div className="hv" data-skin={skin} style={S.root}>
      <style>{SKIN_CSS}</style>
      <div ref={boxRef} style={S.canvas} />

      <div className="hv-panel" style={S.top}>
        <strong style={{ fontSize: 15, whiteSpace: 'nowrap' }}>{world ? `${world.settlement ?? 'Camp'} · Day ${world.day ?? '-'}` : 'Loading…'}</strong>
        <span style={{ ...S.low, whiteSpace: 'nowrap' }}>{spd}{live?.phase ? ` · ${live.phase}` : ''}{paused ? ' · Paused' : ''}</span>
        <DayBar dayT={live?.dayT} wf={wf} />
        {guide && <span style={{ ...S.low, whiteSpace: 'nowrap' }}>{guide.era}</span>}
        {guide && <span style={S.stat} title="Earned as the village lives and learns. Spend it on ideas and upgrades."><strong style={{ color: C.gold, fontSize: 15 }}>{guide.insight}</strong><span style={S.low}>Insight</span></span>}
        {guide && (
          <span style={S.stat} title={guide.trust < guide.trust_heeded ? 'They ignore your focus on free days. Good advice wins them back.' : 'They follow your focus on free days.'}>
            <strong style={{ color: guide.trust < guide.trust_heeded ? C.red : C.text }}>{guide.trust}</strong><span style={S.low}>Trust</span><Meter value={guide.trust} max={100} width={36} color={guide.trust < guide.trust_heeded ? C.red : C.gold} />
          </span>
        )}
        <span style={S.stat} title={lastCall?.model ? `Last council used ${lastCall.model}` : 'Model tokens used today'}><strong>{tokensLeft}</strong><span style={S.low}>tokens · {plans} {plans === 1 ? 'council' : 'councils'}</span></span>
      </div>

      <Resources res={world?.resources} people={(world?.villagers ?? []).filter(v => !v.dying).length} />

      <div style={S.feed}>
        {dusk && (world?.current?.events ?? []).map(e => <strong key={e} style={{ color: C.gold }}>{e}</strong>)}
        {(live?.feed ?? []).slice(0, 3).map((f, i) => (
          <div key={`${i}-${f.name}-${f.text}`} style={{ opacity: f.ok ? 0.95 - i * 0.2 : 0.6 }}><strong>{f.name}</strong> {f.ok ? '' : '✗ '}{f.text}</div>
        ))}
      </div>

      <div className="hv-panel" style={S.rail}>
        {TABS.map(([key, icon, label]) => (
          <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(t => (t === key ? null : key))}
            style={{ position: 'relative', background: tab === key ? 'rgba(230, 180, 80, 0.16)' : 'none', color: tab === key ? C.gold : C.mid, border: 0, borderRadius: 7, padding: '6px 0 5px', cursor: 'pointer', font: 'inherit', fontSize: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1 }}>
            <span style={{ fontSize: 15, lineHeight: 1 }}>{icon}</span>{label}
            {key === 'ideas' && affordable && <span style={{ position: 'absolute', top: 5, right: 12, width: 6, height: 6, borderRadius: 3, background: C.gold }} />}
          </button>
        ))}
      </div>

      {tab && guide && (
        <div className="hv-panel" style={S.drawer}>
          <div style={{ ...S.row, padding: '10px 12px 6px', justifyContent: 'space-between' }}>
            <strong>{TABS.find(t => t[0] === tab)[2]}</strong>
            <button type="button" aria-label="Close" onClick={() => setTab(null)} style={{ background: 'none', border: 0, color: C.low, cursor: 'pointer', font: 'inherit' }}>✕</button>
          </div>
          <div style={S.drawerBody}>
            {tab === 'ideas' && <IdeasTab guide={guide} idle={idle} run={run} api={api} />}
            {tab === 'upgrades' && <UpgradesTab guide={guide} idle={idle} run={run} api={api} />}
            {tab === 'legacy' && <LegacyTab legacy={legacy} idle={idle} run={run} api={api} />}
            {tab === 'build' && <BuildTab buildings={world?.buildings} built={world?.built} />}
            {tab === 'log' && <LogTab log={world?.log} />}
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

      {shown && !(shown.dying && dusk) && <PersonCard v={shown} live={live?.villagers?.[shown.name]} maxHealth={world?.max_health ?? 5} onClose={() => setSelected(null)} />}

      {world?.fallen && dusk && (
        <div className="hv-panel" style={S.notice}>
          <div><strong>The village has fallen.</strong> Everyone was gone by day {world.fallen}.</div>
          <div><Btn primary disabled={idle} onClick={() => { setSelected(null); setGuideText(''); void run('reset', () => api.reset()) }}>Start again · bank {legacy?.would_earn ?? 0} Legacy</Btn></div>
        </div>
      )}

      {away && !world?.fallen && (
        <div className="hv-panel" style={S.notice}>
          <div>
            <strong>While you were away: {away.days} days passed</strong>
            {fmtItems(away.gained) && <div style={S.mid}>{fmtItems(away.gained)}</div>}
            {(away.built ?? []).length > 0 && <div style={S.mid}>Built {away.built.join(', ').replace(/_/g, ' ')}</div>}
            {(away.deaths ?? []).map(d => <div key={d.name} style={{ color: C.red }}>{d.name} died of {d.cause}</div>)}
          </div>
          <div><Btn disabled={idle} onClick={() => void run('ack', api.ack)}>OK</Btn></div>
        </div>
      )}

      {(error || hint) && <div role="alert" className="hv-panel" style={{ ...S.notice, top: 'auto', bottom: DOCK + 16, borderColor: error ? C.red : C.line }}>{error || hint}</div>}

      <div className="hv-panel" style={S.dock}>
        <div style={S.people}>
          {(world?.villagers ?? []).map(v => (
            <Person key={v.name} v={v} live={live?.villagers?.[v.name]} selected={selected === v.name} onSelect={onSelect}
              gone={!!v.dying && dusk} maxHealth={world?.max_health ?? 5} />
          ))}
        </div>
        <div style={S.bar}>
          <span style={S.h}>Focus</span>
          {guide && Object.entries(guide.focuses).map(([key, text]) => (
            <Btn key={key} on={guide.focus === key} disabled={idle} title={`Urge them to ${text}. Judged every ${guide.focus_days} days.`}
              onClick={() => void run('focus', () => api.focus(guide.focus === key ? null : key))}>
              {key[0].toUpperCase() + key.slice(1)}
            </Btn>
          ))}
          <span style={{ ...S.h, marginLeft: 'auto' }}>Speed</span>
          <Btn on={paused} disabled={planning} title="Pause" aria-label="Pause" onClick={() => void run('speed', () => api.speed(paused ? world.speed : 0))}>❚❚</Btn>
          {(world?.speeds ?? []).map(n => (
            <Btn key={n} on={!paused && world?.speed === n} disabled={planning} onClick={() => void run('speed', () => api.speed(n))}>{n}x</Btn>
          ))}
          <Btn title="Camera follows the group" onClick={() => sceneRef.current?.watch()}>Follow</Btn>
          <Btn primary disabled={!budget?.can_plan || idle || planning || world?.council_ready} title={world?.council_ready ? 'The council has decided. Its plans start at dawn.' : reasons.length ? reasons.join('; ') : 'One model call plans everyone\'s next day'} onClick={() => void planDay()}>
            {planning ? 'Council meeting…' : world?.council_ready ? 'Plans set for dawn' : `Hold council${estLabel}`}{reasons.length && !world?.council_ready ? ' •' : ''}
          </Btn>
        </div>
      </div>
    </div>
  )
}
