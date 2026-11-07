//! Request dispatch: one JSON object in, one JSON object out.
//!
//! Request:  {"id": n, "op": "run_day", "world": {...}, "args": {...}}
//! Response: {"id": n, "ok": true, "result": ..., "world": {...}?, "vmap": [...]?, "gone": [...]?}
//!           {"id": n, "ok": false, "error": "..."}

use crate::engine::{self, Effects};
use crate::rng::PyRandom;
use crate::rules::{rules, SCHEMA_VERSION};
use crate::terrain;
use crate::world::*;
use serde_json::{json, Map, Value};

pub const PROTOCOL: i64 = 2;

fn arg<'a>(args: &'a Value, k: &str) -> R<&'a Value> {
    args.get(k).ok_or_else(|| format!("missing argument {:?}", k))
}

fn arg_int(args: &Value, k: &str) -> R<i64> {
    int(arg(args, k)?, k)
}

fn arg_str<'a>(args: &'a Value, k: &str) -> R<&'a str> {
    arg(args, k)?.as_str().ok_or_else(|| format!("argument {:?} must be a string", k))
}

fn arg_vi(args: &Value, w: &World) -> R<usize> {
    let vi = arg_int(args, "vi")?;
    if vi < 0 || vi as usize >= w.villagers.len() {
        return Err("that villager is not in this world".into());
    }
    Ok(vi as usize)
}

fn opt_str(v: &Option<String>) -> Value {
    v.clone().map(Value::String).unwrap_or(Value::Null)
}

/// Worlds that only need the land: seed, changed, shaped.
fn land_stub(args: &Value) -> R<World> {
    let mut w = World::blank();
    w.seed = arg_int(args, "seed")?;
    for (name, target) in [("changed", true), ("shaped", false)] {
        if let Some(Value::Object(m)) = args.get(name) {
            for (k, c) in m {
                let p = parse_key(k).ok_or("bad tile key")?;
                if let Some(ch) = c.as_str().and_then(|s| s.chars().next()) {
                    if target {
                        w.changed.insert(p, ch);
                    } else {
                        w.shaped.insert(p, ch);
                    }
                }
            }
        }
    }
    Ok(w)
}

fn rng_probe(args: &Value) -> R<Value> {
    let mut rng = PyRandom::from_str_seed(arg_str(args, "seed")?);
    let mut out = Vec::new();
    for op in arg(args, "ops")?.as_array().ok_or("ops must be a list")? {
        let a = op.as_array().ok_or("op must be a list")?;
        let kind = a.first().and_then(|k| k.as_str()).ok_or("op needs a name")?;
        out.push(match kind {
            "random" => json!(rng.random()),
            "bits" => json!(rng.getrandbits(int(&a[1], "k")? as u32)),
            "randint" => json!(rng.randint(int(&a[1], "a")?, int(&a[2], "b")?)),
            "choice" => json!(rng.choice_index(int(&a[1], "n")? as usize)),
            other => return Err(format!("unknown rng op {:?}", other)),
        });
    }
    Ok(Value::Array(out))
}

pub struct Reply {
    pub result: Value,
    pub world: bool,
}

fn pure(result: Value) -> R<Reply> {
    Ok(Reply { result, world: false })
}

fn mutated(result: Value) -> R<Reply> {
    Ok(Reply { result, world: true })
}

pub fn handle(req: &Value) -> R<Value> {
    let op = req.get("op").and_then(|o| o.as_str()).ok_or("request has no op")?;
    let empty = json!({});
    let args = req.get("args").unwrap_or(&empty);
    let id = req.get("id").cloned().unwrap_or(Value::Null);
    let mut resp = Map::new();
    resp.insert("id".into(), id);
    // ops that need no world
    let free: Option<Value> = match op {
        "hello" => Some(json!({
            "protocol": PROTOCOL,
            "version": env!("CARGO_PKG_VERSION"),
            "engine": env!("CARGO_PKG_NAME"),
            "version": env!("CARGO_PKG_VERSION"),
            "rules_sha256": rules().sha256,
            "schema": SCHEMA_VERSION,
        })),
        "rng_probe" => Some(rng_probe(args)?),
        "new_world" => {
            let seed = arg_int(args, "seed")?;
            let now = Num::from_value(arg(args, "now")?)?;
            let perks = match args.get("perks") {
                Some(Value::Array(a)) => a.iter().filter_map(|p| p.as_str().map(|s| s.to_string())).collect(),
                _ => vec![],
            };
            let camp = match args.get("camp") {
                Some(Value::Null) | None => None,
                Some(c) => Some(pt(c, "camp")?),
            };
            Some(engine::new_world(seed, now, &perks, camp)?.to_value())
        }
        "_find_camp" => {
            let (x, y) = terrain::find_camp(arg_int(args, "seed")?);
            Some(json!([x, y]))
        }
        "_land" => {
            let c = terrain::land(arg_int(args, "seed")?, arg_int(args, "cx")?, arg_int(args, "cy")?);
            Some(Value::Array(c.iter().map(|row| Value::String(String::from_utf8_lossy(row).to_string())).collect()))
        }
        "_land_char" => {
            Some(json!(terrain::land_char(arg_int(args, "seed")?, arg_int(args, "x")?, arg_int(args, "y")?).to_string()))
        }
        "describe_action" => Some(json!(engine::describe_action(arg(args, "action")?))),
        "tile" | "_char" | "_base_char" | "_near_tile" => {
            let w = land_stub(args)?;
            let (x, y) = (arg_int(args, "x")?, arg_int(args, "y")?);
            Some(match op {
                "tile" => json!(engine::tile_name(engine::ch(&w, x, y))?),
                "_char" => json!(engine::ch(&w, x, y).to_string()),
                "_base_char" => json!(engine::base_char(&w, x, y).to_string()),
                _ => {
                    let kind = arg_str(args, "kind")?;
                    json!(engine::near_tile(&w, x, y, rules().char_of(kind), arg_int(args, "reach")?))
                }
            })
        }
        _ => None,
    };
    if let Some(result) = free {
        resp.insert("ok".into(), Value::Bool(true));
        resp.insert("result".into(), result);
        return Ok(Value::Object(resp));
    }

    let mut w = World::from_value(req.get("world").ok_or("request has no world")?)?;
    let reply = world_op(op, &mut w, args)?;
    resp.insert("ok".into(), Value::Bool(true));
    resp.insert("result".into(), reply.result);
    if reply.world {
        resp.insert("world".into(), w.to_value());
        resp.insert(
            "vmap".into(),
            Value::Array(w.villagers.iter().map(|v| v.src.map(Value::from).unwrap_or(Value::Null)).collect()),
        );
        resp.insert(
            "gone".into(),
            Value::Array(w.gone.iter().map(|(src, state)| json!([src, state])).collect()),
        );
    }
    Ok(Value::Object(resp))
}

fn world_op(op: &str, w: &mut World, args: &Value) -> R<Reply> {
    match op {
        "_reveal" => {
            let vi = arg_vi(args, w)?;
            mutated(json!(engine::reveal(w, vi)))
        }
        "find_path" => {
            let vi = arg_vi(args, w)?;
            let path = engine::find_path(w, vi, arg_int(args, "x")?, arg_int(args, "y")?);
            pure(match path {
                Some(p) => Value::Array(p.into_iter().map(pt_to_value).collect()),
                None => Value::Null,
            })
        }
        "observe" => {
            let vi = arg_vi(args, w)?;
            pure(json!(observe(w, vi)))
        }
        "execute" => {
            let vi = arg_vi(args, w)?;
            let mut fx: Effects = match args.get("fx") {
                Some(Value::Object(m)) => m.clone(),
                _ => Map::new(),
            };
            let (used, err, summary) = engine::execute(w, vi, arg(args, "act")?, arg_int(args, "slots_left")?, &mut fx)?;
            mutated(json!({"out": [used, opt_str(&err), summary], "fx": fx}))
        }
        "instinct_actions" => {
            let vi = arg_vi(args, w)?;
            pure(Value::Array(engine::instinct_actions(w, vi)))
        }
        "_scout" => {
            let vi = arg_vi(args, w)?;
            pure(Value::Array(engine::scout(w, vi)))
        }
        "_home" => {
            let vi = arg_vi(args, w)?;
            pure(engine::home(w, vi).map(pt_to_value).unwrap_or(Value::Null))
        }
        "_room" => {
            let vi = arg_vi(args, w)?;
            pure(json!(engine::room(w, vi, arg_str(args, "item")?)))
        }
        "_knows" => pure(json!(engine::knows(w, arg_str(args, "idea")?))),
        "_lit_fire_near" => pure(json!(engine::lit_fire_near(w, arg_int(args, "x")?, arg_int(args, "y")?))),
        "_grow" => {
            engine::grow(w);
            mutated(Value::Null)
        }
        "_seed_forest" => {
            engine::seed_forest(w);
            mutated(Value::Null)
        }
        "_herds_live" => {
            engine::herds_live(w);
            mutated(Value::Null)
        }
        "_open_chunk" => {
            engine::open_chunk(w, arg_int(args, "cx")?, arg_int(args, "cy")?);
            mutated(Value::Null)
        }
        "_arrival" => {
            let mut events = strings(arg(args, "events")?, "events")?;
            engine::arrival(w, &mut events);
            mutated(strings_to_value(&events))
        }
        "run_day" => {
            let report = engine::run_day(
                w,
                args.get("plans").unwrap_or(&Value::Null),
                arg_str(args, "source")?,
                args.get("unwatched").and_then(|u| u.as_bool()).unwrap_or(false),
            )?;
            mutated(report)
        }
        "advance" => {
            let now = Num::from_value(arg(args, "now")?)?;
            mutated(engine::advance(w, now)?)
        }
        "public_state" => {
            let now = Num::from_value(arg(args, "now")?)?;
            let have = args.get("have").and_then(|h| h.as_str()).unwrap_or("");
            pure(engine::public_state(w, now, have)?)
        }
        "land_view" => pure(engine::land_view(w)),
        "land_rev" => pure(json!(engine::land_rev(w))),
        "resources" => pure(engine::resources(w).value),
        "needs_council" => {
            let wood = args.get("held").and_then(|h| h.get("wild")).and_then(|x| x.get("wood")).and_then(|x| x.as_i64());
            pure(strings_to_value(&engine::needs_council(w, wood)?))
        }
        "era" => pure(json!(engine::era(w))),
        "max_health" => pure(json!(engine::max_health(w))),
        "season" => pure(json!(engine::season(w))),
        "legacy_earned" => pure(json!(engine::legacy_earned(w))),
        "set_speed" => {
            let now = Num::from_value(arg(args, "now")?)?;
            let r = engine::set_speed(w, arg(args, "speed")?, now);
            mutated(opt_str(&r))
        }
        "restart_day" => {
            engine::restart_day(w, Num::from_value(arg(args, "now")?)?);
            mutated(Value::Null)
        }
        "set_focus" => {
            let focus = match arg(args, "focus")? {
                Value::Null => None,
                Value::String(s) => Some(s.as_str()),
                _ => return Err("focus must be a string or null".into()),
            };
            let r = engine::set_focus(w, focus);
            mutated(opt_str(&r))
        }
        "plant_idea" => {
            let r = engine::plant_idea(w, arg_str(args, "idea")?);
            mutated(opt_str(&r))
        }
        "buy_upgrade" => {
            let r = engine::buy_upgrade(w, arg_str(args, "upgrade")?);
            mutated(opt_str(&r))
        }
        other => Err(format!("unknown op {:?}", other)),
    }
}

/// Egocentric text view: only what this villager can see and remembers.
fn observe(w: &World, vi: usize) -> String {
    use engine::*;
    let v = &w.villagers[vi];
    let reach = vision(w);
    let (x0, y0) = (v.x - reach, v.y - reach);
    let (x1, y1) = (v.x + reach + 1, v.y + reach + 1);
    let stores: HSet<Pt> = store_positions(w).into_iter().collect();
    let herds: HSet<Pt> = w.herds.iter().map(|h| (h.x, h.y)).collect();
    let built: HSet<Pt> = w.built.iter().map(|b| (b.x, b.y)).collect();
    let fields: HSet<Pt> = w.built.iter().filter(|b| b.kind == "field").map(|b| (b.x, b.y)).collect();
    let mut rows = Vec::new();
    for y in y0..y1 {
        let mut row = String::new();
        for x in x0..x1 {
            let c = if (x, y) == (v.x, v.y) {
                '@'
            } else if stores.contains(&(x, y)) {
                'S'
            } else if herds.contains(&(x, y)) {
                'D'
            } else if built.contains(&(x, y)) {
                if fields.contains(&(x, y)) { 'F' } else { 'L' }
            } else if ch(w, x, y) == BERRIES && w.stocks.get(&(x, y)).copied().unwrap_or(0) <= 0 {
                ','
            } else {
                ch(w, x, y)
            };
            row.push(c);
        }
        rows.push(row);
    }
    let near: Vec<&str> = w
        .villagers
        .iter()
        .enumerate()
        .filter(|(i, o)| *i != vi && dist_pt(o.x, o.y, v.x, v.y) <= reach)
        .map(|(_, o)| o.name.as_str())
        .collect();
    let mut head = format!(
        "## {} ({}) at ({},{}) energy {}/{}, health {}/{}",
        v.name, v.trait_, v.x, v.y, v.energy, crate::rules::MAX_ENERGY, v.health, max_health(w)
    );
    if v.hungry != 0 {
        head.push_str(&format!(", {} hungry nights in a row", v.hungry));
    }
    let skills = if v.skills.is_empty() { "none".to_string() } else { v.skills.join(", ") };
    let mut lines = vec![head, format!("skills: {}; carrying: {}", skills, fmt_inv(&v.inv)), format!("view, top-left=({},{}):", x0, y0)];
    lines.extend(rows);
    if !near.is_empty() {
        lines.push(format!("can see: {}", near.join(", ")));
    }
    let herds_near: Vec<String> = w
        .herds
        .iter()
        .filter(|h| dist_pt(h.x, h.y, v.x, v.y) <= reach)
        .map(|h| format!("{} {} at ({},{})", h.count, h.kind, h.x, h.y))
        .collect();
    if !herds_near.is_empty() {
        lines.push(format!("animals: {}", herds_near.join(", ")));
    }
    let tail = |list: &Vec<String>, n: usize| list[list.len().saturating_sub(n)..].join(" | ");
    if !v.memory.is_empty() {
        lines.push(format!("remembers: {}", tail(&v.memory, memory_lines(w))));
    }
    if !v.heard.is_empty() {
        lines.push(format!("heard: {}", tail(&v.heard, crate::rules::HEARD_LINES)));
    }
    if !v.feedback.is_empty() {
        lines.push(format!("yesterday went wrong: {}", tail(&v.feedback, 3)));
    }
    if !v.standing_orders.is_empty() {
        let acts: Vec<String> = v.standing_orders.iter().map(describe_action).collect();
        lines.push(format!("habit: {}", acts.join(", ")));
    }
    for (i, (sx, sy)) in store_positions(w).iter().enumerate() {
        if dist_pt(*sx, *sy, v.x, v.y) <= reach {
            lines.push(format!("store at ({},{}) holds {}", sx, sy, fmt_inv(store_inv(w, i))));
        }
    }
    for idea in &w.guide.planted {
        if !w.guide.known.contains(idea) {
            let spec = rules().idea(idea).expect("planted idea exists");
            let place = match spec.near.as_deref() {
                Some("water") => " near water",
                Some("fire") => " beside a fire pit",
                _ => "",
            };
            lines.push(format!(
                "an idea came to you: {} (experiment {}{}, uses {})",
                rules().value["IDEAS"][idea]["hint"].as_str().unwrap_or(""),
                idea,
                place,
                fmt_inv(&spec.try_)
            ));
        }
    }
    lines.join("\n")
}

fn dist_pt(ax: i64, ay: i64, bx: i64, by: i64) -> i64 {
    terrain::dist(ax, ay, bx, by)
}
