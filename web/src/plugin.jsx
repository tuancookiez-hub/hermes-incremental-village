// Hermes Incremental Village: a 3D Stone Age village where the LLM plays three villagers.
import { ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { VillagePage } from './VillagePage.jsx'

const PATH = '/hermes-village'

export default {
  id: 'hermes-village',
  name: 'Hermes Incremental Village',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, title: 'Village', data: { path: PATH }, render: () => <VillagePage ctx={ctx} /> },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: PATH, label: 'Village', codicon: 'home' } }
    ])
  }
}
