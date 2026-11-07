// Fails if desktop/plugin.js imports anything outside the Hermes Desktop allowlist.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ALLOW = new Set(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'])
const file = join(dirname(fileURLToPath(import.meta.url)), '..', 'desktop', 'plugin.js')
const src = readFileSync(file, 'utf8')
const found = new Set()
// static: import ... from "x" / import "x" / export ... from "x"
for (const m of src.matchAll(/^\s*(?:import|export)\s[^;]*?\sfrom\s*["']([^"']+)["']/gm)) found.add(m[1])
for (const m of src.matchAll(/^\s*import\s*["']([^"']+)["']/gm)) found.add(m[1])
let bad = [...found].filter(s => !ALLOW.has(s))
if (/\bimport\s*\(/.test(src)) bad.push('<dynamic import()>')
if (/\brequire\s*\(/.test(src)) bad.push('<require()>')
console.log('imports found:', [...found].join(', ') || '(none)')
if (bad.length) { console.error('FAIL: disallowed:', bad.join(', ')); process.exit(1) }
console.log('OK: all imports within allowlist')
