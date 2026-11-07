// Thin wrappers over ctx.rest for the hermes-village backend (/api/plugins/hermes-village/).
export function makeApi(ctx) {
  const call = (path, method = 'GET', body) =>
    ctx.rest(path, method === 'GET' ? { method } : { method, body: body ?? {} })
  return {
    state: have => call(have ? `/state?have=${encodeURIComponent(have)}` : '/state'),
    engine: () => call('/engine'),
    installEngine: () => call('/engine', 'POST', {}),
    guide: text => call('/guide', 'POST', { text }),
    habit: () => call('/habit', 'POST', {}),
    ack: () => call('/ack', 'POST', {}),
    budget: daily_tokens => call('/budget', 'POST', { daily_tokens }),
    plant: idea => call('/plant', 'POST', { idea }),
    upgrade: upgrade => call('/upgrade', 'POST', { upgrade }),
    focus: focus => call('/focus', 'POST', { focus }),
    perk: perk => call('/perk', 'POST', { perk }),
    speed: speed => call('/speed', 'POST', { speed }),
    reset: seed => call('/reset', 'POST', seed == null ? {} : { seed })
  }
}

export function errText(e) {
  const d = e?.detail ?? e?.body?.detail ?? e?.data?.detail
  if (typeof d === 'string') return d
  if (d) {
    try { return JSON.stringify(d) } catch { /* fall through */ }
  }
  return String(e?.message ?? e ?? 'Request failed')
}

export function fmtTokens(n) {
  n = Number(n) || 0
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, '')}k`
  return String(Math.round(n))
}
