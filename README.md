# Hermes Incremental Village

A 3D Stone Age village whose three villagers — Ash, Bryn and Coll — are played by Hermes.
You are their guide, not their god: you give advice, and they decide what to do.

- **The villagers only know what they can see.** Each villager's view covers 4 tiles in every
  direction, plus their own short memory and what others have told them. They cannot walk to a
  place they have never seen, and they must talk to coordinate.
- **The game is the referee.** Every action (look, walk, gather, build, talk, trade, teach, rest, experiment, deposit, take, hunt) is
  checked against position, energy, skills, materials and daylight. An invalid action fails,
  costs time, and the villager hears about it the next day.
- **The village is alive.** A day lasts 2 real minutes. You watch the villagers walk, chop,
  pick, build, talk and rest on the map, and the camp grows from Camp to Hamlet to Village.
- **Resources work like the real thing.** Forest is finite and slow to return: cut it bare and it only
  regrows as young trees seed from a neighbouring tile, unless the village learns coppicing and tends
  a woodlot. Stone never runs out, but it is heavy. Fires burn wood from the camp store every night,
  and go out without it. Villagers need water, fields tire unless rested, grain keeps and meat spoils.
  Deer and boar roam beyond the camp, breed in spring, and can be hunted out for good. The readout shows
  what the village holds and what it has found; land nobody has explored does not count.
- **Survival is real, and villagers die for good.** A year is 20 days. Bushes run out and regrow
  slowly, carried food rots, and nothing grows in winter. Hunger, cold and wolves all cost health,
  and a villager who reaches 0 dies and leaves a grave. If everyone dies while you are playing,
  the village has fallen and you start again.
- **Needs drive progress.** Picking bushes bare can teach someone farming. Fields must be near
  water, shelter must be near where you sleep, and a fire keeps wolves away. Huts add beds, and a
  wanderer may join when there is a spare bed and everyone is eating well.
- **Land with no edge.** Like Minecraft, a seed grows the world chunk by chunk as someone gets close, in
  every direction, with slow changes from plains to deep forest, lake country and rocky highs. A villager
  walks at most 24 tiles a day, so resources near camp run down and there is always more further out.
  Long walks carry across days, so villagers sleep where night finds them. The save holds only what has
  changed and what has been seen, so the world's size costs nothing.
- **Nomads first.** The band shelters where it stops and can raise new lean-tos and fires anywhere.
  Depots are cheap caches for goods too far to haul home. Moving on, hauling and settling down are all
  real choices with real costs.
- **The map starts dark.** Land nobody has seen is black, explored land is dim, and only what villagers
  can see right now is clear. Animals show up only while someone can see them. Land far past what anyone
  has seen is never generated or sent to the page; the nearest chunks are sent ahead so the ground can
  be drawn up to the edge of the dark.
- **Days flow into nights.** Dusk, night and dawn run as one cycle. Villagers sleep through the dark and
  pick up where they stopped. A council's plans start at the next dawn, so nobody jumps.
- **You control the clock.** Pause, or run at 1x, 2x, 4x, 8x or 16x. Speed and pause only last while
  the page is open: 30 seconds after you leave, time returns to 1x.
- **It keeps going while you're away.** When you come back, the days you missed are worked out
  from the villagers' habits and you get a summary, including anyone who died. Up to 30 days count
  per absence. Unwatched days can kill villagers, but never the last one.
- **Free days keep them alive; councils move them forward.** Without any model call, villagers
  follow their habits and instincts: eat, fetch wood, raise a first lean-to, wander. Skills,
  trades and every later building need a plan.
- **You are the guide, not a god.** You cannot move anyone or place anything. You earn Insight as
  the village lives, builds and even loses people, then spend it on ideas and upgrades. Ideas follow
  real history, and villagers must test each one with an experiment that can fail. Your focus is
  judged by results: good advice raises Trust, and below 40 Trust they ignore you on free days. When
  a village ends, it leaves Legacy, which buys permanent starting advantages for the next one.
- **A council is your decision.** It is one batched model call that plans every villager's day
  at once, about 1–3k tokens, never one call per villager or per action. The panel tells you
  when one is worth it.

Eras after copper, relationships, and optional extras for the Three Stage, Hermes Maps
and Screen Overlay plugins are planned but not built.

## Using it

| Where | How |
|---|---|
| Desktop | Open **Village** in the sidebar. The village fills the page: status runs along the top, villagers and actions dock at the bottom, and Ideas, Upgrades, Legacy, Build, Speak, Log and Settings open from the right. |
| Any chat | `/village` (status), `/village plan`, `/village speed <pause|1|2|4|8|16>`, `/village habit` (skip to a new free day), `/village guide <advice>`, `/village budget <tokens>`, `/village ideas`, `/village plant <idea>`, `/village upgrade <name>`, `/village focus <food\|shelter\|explore\|learn>` |
| Agent tools | `village_status`, `village_guide`, `village_habit_day`, `village_plan_day` (toolset `village`) |

### Install (local development)

1. Link or copy this folder to `<HERMES_HOME>/plugins/hermes-village`.
2. Run `hermes plugins enable hermes-village`, then restart the gateway so the backend routes mount.
3. In Desktop, turn on the plugin under **Capabilities → Plugins**.
4. Open the page and press **Download engine**, or run `/village setup` in chat. This fetches the
   rules engine for your computer once. You do not need Rust.

Prefer to build it yourself? With [Rust](https://rustup.rs) installed, run this from this folder:
```bash
cargo install --path engine-rs --locked
```
The plugin checks the engine's version, rules and protocol when it starts it, and refuses a mismatch
with a message saying so. A new plugin version asks for its matching engine the same way.

### Releasing the engine

Set the version in `plugin.yaml`, `dashboard/manifest.json`, `engine-rs/Cargo.toml`,
`village/bridge.py` and `village/engine-release.json`, commit, and push a tag such as `v0.10.0`.
`.github/workflows/engine.yml` builds Windows, Linux and macOS, tests each one against the frozen
Python engine, attests the builds and publishes them on the release. Then run
`python scripts/pin_engine.py`, which verifies each attestation and records its checksum, and commit
the result. The plugin only ever downloads a file whose checksum is pinned there.

### Rebuilding the Desktop page

```bash
cd web && npm ci && npm run build && npm run check
```

The build writes `desktop/plugin.js`: one unminified ES module that contains three.js r187.
Its only imports are `@hermes/plugin-sdk`, `react` and `react/jsx-runtime`.

### Getting around

Drag to turn the view, scroll to zoom, and click a villager to follow them. The map in the corner shows
everything they have seen; click it to look there. Space pauses, 1 to 5 set the speed, C goes to camp,
F follows the group and Esc closes what is open. Sound is off until you turn it on in Settings, and it is
made in the page, so nothing is downloaded.

## Costs, data, network and background work

- **Model cost.** Only a council spends tokens: one `ctx.llm.complete_structured` call with
  `max_tokens` 1500 (plus 400 per villager beyond the first 3), run against your active model. You can route it to a cheaper model by
  pinning the **Village planner** auxiliary slot in Settings → Models.
- **Daily cap.** The default is 30,000 tokens per calendar day; change it in the panel or with
  `/village budget`. A council is refused *before* the call if the worst case (estimated input
  plus the output cap) would go over the cap. Every call is written to the plugin's ledger.
  If the provider reports no usage, a conservative estimate is charged instead.
- **Hermes does not report dollar cost to plugins** in this version (`usage.cost_usd` is not
  filled in), so the budget is counted in tokens.
- **One child process, no background work or spending.** The rules run in
  `hermes-village-engine`, a Rust program whose source is in `engine-rs/`. Hermes starts one copy per
  process that uses the plugin, the first time it is needed, and talks to it over stdin and stdout.
  It listens on no port, opens no network connection, reads and writes no files, and exits when
  Hermes does. It only answers requests, so it does nothing while idle. The plugin starts no
  timers, threads or schedulers. Nothing runs while nobody is looking: time is caught up when
  the village is next read, by the page or a village tool or command. Catch-up uses habits and
  instincts only and can never call a model. Councils happen only when you ask for one, and are
  refused inside a cron run. The Desktop page re-reads the state every 5 seconds, and when a
  day ends, only while it is open and visible; those reads are free.
- **Network.** None while playing, apart from the model calls Hermes makes for a council through
  your configured provider. There are no remote assets or scripts, and no telemetry. There is one
  download, and only when you press **Download engine** or run `/village setup`: the engine for your
  computer, about 1 MB, from this plugin's GitHub releases. It is checked against a checksum pinned
  in `village/engine-release.json` and thrown away if it does not match. It is stored at
  `<HERMES_HOME>/plugin-data/hermes-village/engine/`. Building from source instead downloads the
  Rust crates (serde, serde_json, sha2 and their dependencies) from crates.io, pinned by
  `engine-rs/Cargo.lock`.
- **Data.** The village save and the token ledger live in Hermes plugin storage at
  `<HERMES_HOME>/plugin-data/hermes-village/data.db` (SQLite), along with the village's written
  history. Your welcome, look and sound choices stay in this browser. Python owns storage: the engine is
  handed the world and hands it back. The plugin reads no files outside that folder and never
  touches credentials.
- **What the model sees.** Only the game rules, the villagers' local views, memories and what
  they heard, plus your guidance. It sees nothing from your conversations or files.
- **Updates.** No self-update or remote code loading.

## Layout

```
plugin.yaml, __init__.py      agent half: tools, /village, "Village planner" model slot
engine-rs/                    the rules in Rust: clock, catch-up, perception, validation, replay
village/rules.json            every game constant and table, shared by Rust and Python
village/engine.py             thin client: the same functions, forwarded to the Rust engine
village/bridge.py             starts the engine and talks to it over a pipe
village/planner.py            council prompt and JSON schema
village/service.py            shared operations, token budget gate, spend ledger
village/store.py              SQLite in Hermes plugin storage
dashboard/plugin_api.py       read/write routes for the Desktop page (never call a model)
desktop/plugin.js             built Desktop page (do not edit; edit web/src)
web/                          Desktop page source (React + three.js) and build
tests/                        python -m pytest tests; reference_engine.py is the original Python
                              rules, kept so Rust can be compared with it day by day
spike/budget_sim.py           offline cost model used to design the council budget
```

## License

MIT. three.js is MIT and bundled; see `THIRD_PARTY_NOTICES.md`.
