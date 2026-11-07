// Bundles src/plugin.jsx (+ three.js) into ../desktop/plugin.js: one readable (unminified) ESM file
// whose only remaining imports are the specifiers Hermes Desktop resolves.
import { build } from 'esbuild'
import { statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const outfile = join(root, '..', 'desktop', 'plugin.js')

await build({
  entryPoints: [join(root, 'src', 'plugin.jsx')],
  outfile,
  bundle: true,
  format: 'esm',
  target: 'es2022',
  jsx: 'automatic',
  loader: { '.png': 'dataurl', '.woff': 'dataurl' },
  legalComments: 'eof',
  external: ['react', 'react/jsx-runtime', '@hermes/plugin-sdk'],
  banner: { js: '// hermes-village desktop plugin. Built from web/src (unminified). Bundles three.js (MIT, notice at end of file).' },
  logLevel: 'warning'
})
console.log(`wrote ${outfile} (${(statSync(outfile).size / 1024).toFixed(0)} KiB)`)
