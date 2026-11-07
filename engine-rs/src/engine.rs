//! The game rules: a line-for-line port of village/engine.py (the frozen oracle is
//! tests/reference_engine.py). Where Python behaviour is subtle it is reproduced on purpose.

use crate::pyfmt::{self, head, pystr, repr};
use crate::rng::PyRandom;
use crate::rules::*;
use crate::terrain::{self, dist, land_char};
use crate::world::*;
use serde_json::{json, Map, Value};
use std::collections::VecDeque;

pub type Out = (i64, Option<String>, String);
pub type Effects = Map<String, Value>;

pub const GRASS: char = '.';
pub const FOREST: char = 'T';
pub const ROCK: char = 'R';
pub const BERRIES: char = 'b';
pub const WATER: char = '~';

fn out(n: i64, err: &str, summary: &str) -> Out {
    (n, Some(err.to_string()), summary.to_string())
}

fn ok(n: i64, summary: String) -> Out {
    (n, None, summary)
}

// ---------------------------------------------------------------- small queries

pub fn season_of(day: i64) -> &'static str {
    let r = rules();
    &r.seasons[(day - 1).div_euclid(SEASON_DAYS).rem_euclid(r.seasons.len() as i64) as usize]
}

pub fn season(w: &World) -> &'static str {
    season_of(w.day)
}

pub fn ch(w: &World, x: i64, y: i64) -> char {
    match w.changed.get(&(x, y)) {
        Some(c) => *c,
        None => land_char(w.seed, x, y),
    }
}

pub fn base_char(w: &World, x: i64, y: i64) -> char {
    match w.shaped.get(&(x, y)) {
        Some(c) => *c,
        None => land_char(w.seed, x, y),
    }
}

pub fn tile_name(c: char) -> R<&'static str> {
    rules().tile_of(c).ok_or_else(|| format!("KeyError: {:?}", c.to_string()))
}

pub fn has(w: &World, upgrade: &str) -> bool {
    w.guide.upgrades.iter().any(|u| u == upgrade)
}

pub fn vision(w: &World) -> i64 {
    VISION + if has(w, "keen_eyes") { 1 } else { 0 }
}

pub fn memory_lines(w: &World) -> usize {
    MEMORY_LINES + if has(w, "long_memory") { 2 } else { 0 }
}

pub fn max_health(w: &World) -> i64 {
    MAX_HEALTH + if has(w, "hardy") { 1 } else { 0 }
}

pub fn knows(w: &World, idea: &str) -> bool {
    w.guide.known.iter().any(|k| k == idea)
}

pub fn near_built(w: &World, x: i64, y: i64, kinds: &[&str], reach: i64) -> bool {
    w.built.iter().any(|b| kinds.contains(&b.kind.as_str()) && dist(b.x, b.y, x, y) <= reach)
}

pub fn near_tile(w: &World, x: i64, y: i64, kind: char, reach: i64) -> bool {
    for ty in (y - reach)..=(y + reach) {
        for tx in (x - reach)..=(x + reach) {
            if ch(w, tx, ty) == kind {
                return true;
            }
        }
    }
    false
}

pub fn lit_fire_near(w: &World, x: i64, y: i64) -> bool {
    w.built.iter().any(|b| b.kind == "fire_pit" && b.is_lit() && dist(b.x, b.y, x, y) <= SHELTER_RANGE)
}

pub fn bonus(w: &World, key: &str) -> i64 {
    let mut seen: Vec<&str> = Vec::new();
    let mut total = 0;
    for b in &w.built {
        if seen.contains(&b.kind.as_str()) {
            continue;
        }
        seen.push(&b.kind);
        if let Some(spec) = rules().building(&b.kind) {
            total += if key == "rest" { spec.rest } else if key == "food" { spec.food } else { 0 };
        }
    }
    total
}

pub fn fmt_inv(inv: &[(String, i64)]) -> String {
    let items: Vec<String> = inv.iter().filter(|(_, n)| *n != 0).map(|(k, n)| format!("{} {}", n, k)).collect();
    if items.is_empty() {
        "nothing".into()
    } else {
        items.join(", ")
    }
}

pub fn pose(v: &Villager) -> Value {
    json!({"x": v.x, "y": v.y, "energy": v.energy, "inv": inv_to_value(&v.inv)})
}

fn last_n(list: &[String], n: usize) -> Vec<String> {
    let start = list.len().saturating_sub(n);
    list[start..].to_vec()
}

// ---------------------------------------------------------------- creation

pub fn camp_ground(cx: i64, cy: i64) -> HMap<Pt, char> {
    let mut shaped = HMap::default();
    for y in (cy - 2)..(cy + 2) {
        for x in (cx - 2)..(cx + 2) {
            shaped.insert((x, y), GRASS);
        }
    }
    let r = rules();
    for (dx, dy, kind) in [(-6, -1, "forest"), (5, 0, "rock"), (0, -6, "berries"), (0, 6, "water")] {
        shaped.insert((cx + dx, cy + dy), r.char_of(kind));
    }
    shaped
}

pub fn open_chunk(w: &mut World, cx: i64, cy: i64) {
    if w.chunks.contains(&(cx, cy)) {
        return;
    }
    w.chunks.insert((cx, cy));
    let land = terrain::land(w.seed, cx, cy);
    let mut grazing: Vec<Pt> = Vec::new();
    let r = rules();
    for dy in 0..16usize {
        for dx in 0..16usize {
            let (x, y) = (cx * CHUNK + dx as i64, cy * CHUNK + dy as i64);
            let c = w.shaped.get(&(x, y)).copied().unwrap_or(land[dy][dx] as char);
            if let Some(n) = r.full_stock_of(c) {
                w.stocks.insert((x, y), n);
            }
            if (c == GRASS || c == FOREST) && dist(x, y, w.camp.0, w.camp.1) >= 8 {
                grazing.push((x, y));
            }
        }
    }
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:herds", w.seed, key(cx, cy)));
    if !grazing.is_empty() && rng.random() < HERD_CHANCE {
        let (x, y) = grazing[rng.choice_index(grazing.len())];
        let kind = if rng.random() < 0.4 { "boar" } else { "deer" };
        let count = rng.randint(3, 5);
        w.herds.push(Herd { kind: kind.into(), x, y, count, extra: Map::new() });
    }
}

pub fn reveal(w: &mut World, vi: usize) -> i64 {
    let before = w.villagers[vi].seen.len() as i64;
    let reach = vision(w);
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    for cy in ((vy - reach) >> 4)..=((vy + reach) >> 4) {
        for cx in ((vx - reach) >> 4)..=((vx + reach) >> 4) {
            open_chunk(w, cx, cy);
        }
    }
    let seen = &mut w.villagers[vi].seen;
    for y in (vy - reach)..=(vy + reach) {
        for x in (vx - reach)..=(vx + reach) {
            seen.insert(x, y);
        }
    }
    seen.len() as i64 - before
}

pub fn new_world(seed: i64, now: Num, perks: &[String], camp: Option<Pt>) -> R<World> {
    let (cx, cy) = camp.unwrap_or_else(|| terrain::find_camp(seed));
    let shaped = camp_ground(cx, cy);
    let r = rules();
    let has_perk = |p: &str| perks.iter().any(|x| x == p);
    let mut villagers = Vec::new();
    for (i, base) in r.starting.iter().enumerate() {
        villagers.push(Villager {
            name: base.name.clone(),
            trait_: base.trait_.clone(),
            x: cx - 1 + i as i64,
            y: cy,
            energy: MAX_ENERGY,
            health: MAX_HEALTH,
            hungry: 0,
            skills: base.skills.clone(),
            inv: vec![("food".into(), if has_perk("full_packs") { 4 } else { 2 })],
            memory: vec![],
            heard: vec![],
            feedback: vec![],
            standing_orders: vec![],
            thought: String::new(),
            seen: Seen::default(),
            dry: None,
            extra: Map::new(),
            src: None,
        });
    }
    let seed_memory = has_perk("seed_memory");
    let mut w = World {
        schema: SCHEMA_VERSION,
        seed,
        day: 1,
        born: now,
        land_rev: 0,
        camp: (cx, cy),
        changed: shaped.clone(),
        shaped,
        chunks: HSet::default(),
        villagers,
        built: vec![],
        guidance: String::new(),
        guidance_day: 0,
        last_planned_day: 0,
        log: vec![],
        day_started_at: now,
        away: Value::Null,
        speed: Num::I(1),
        paused_at: None,
        last_read: now,
        store: vec![],
        store_at: (cx, cy - 1),
        depots: vec![],
        soil: HMap::default(),
        woodlots: vec![],
        woodlot_set: HSet::default(),
        fire_out: false,
        pending_plans: Value::Null,
        stocks: HMap::default(),
        herds: vec![],
        dead: vec![],
        emptied: 0,
        fallen: None,
        guide: Guide {
            insight: if has_perk("old_songs") { 5 } else { 0 },
            trust: if has_perk("first_trust") { 65 } else { START_TRUST },
            planted: if seed_memory { vec!["sowing".into()] } else { vec![] },
            known: if seed_memory { vec!["sowing".into()] } else { vec![] },
            upgrades: vec![],
            attempts: vec![],
            focus: None,
            focus_start: None,
            era: "Stone Age".into(),
            extra: Map::new(),
        },
        events: None,
        extra: Map::new(),
        gone: vec![],
    };
    if seed_memory {
        w.villagers[0].skills.push("farming".into());
    }
    for i in 0..w.villagers.len() {
        reveal(&mut w, i);
    }
    Ok(w)
}

// ---------------------------------------------------------------- paths and search

pub fn find_path(w: &World, vi: usize, x: i64, y: i64) -> Option<Vec<Pt>> {
    let v = &w.villagers[vi];
    let start = (v.x, v.y);
    let mut prev: HMap<Pt, Option<Pt>> = HMap::default();
    prev.insert(start, None);
    let mut queue = VecDeque::new();
    queue.push_back(start);
    while let Some((cx, cy)) = queue.pop_front() {
        if (cx, cy) == (x, y) {
            let mut path = Vec::new();
            let mut at = Some((cx, cy));
            while let Some(p) = at {
                path.push(p);
                at = prev[&p];
            }
            path.reverse();
            return Some(path);
        }
        for dy in [-1, 0, 1] {
            for dx in [-1, 0, 1] {
                let (nx, ny) = (cx + dx, cy + dy);
                if prev.contains_key(&(nx, ny)) {
                    continue;
                }
                if v.seen.contains(nx, ny) && ch(w, nx, ny) != WATER {
                    prev.insert((nx, ny), Some((cx, cy)));
                    queue.push_back((nx, ny));
                }
            }
        }
    }
    None
}

const AROUND: [(i64, i64); 9] = [(0, 0), (-1, 0), (1, 0), (0, -1), (-1, -1), (1, -1), (0, 1), (-1, 1), (1, 1)];

/// `_search`: walk outward over land this villager knows; first tile on (or beside) a hit.
pub fn search(w: &World, vi: usize, start: Option<Pt>, adjacent: bool, hit: &mut dyn FnMut(i64, i64) -> bool) -> Option<Pt> {
    let v = &w.villagers[vi];
    let origin = start.unwrap_or((v.x, v.y));
    let mut done: HSet<Pt> = HSet::default();
    done.insert(origin);
    let mut queue = VecDeque::new();
    queue.push_back((origin.0, origin.1, 0i64));
    while let Some((x, y, steps)) = queue.pop_front() {
        if adjacent {
            for (dx, dy) in AROUND {
                if hit(x + dx, y + dy) {
                    return Some((x, y));
                }
            }
        } else if hit(x, y) {
            return Some((x, y));
        }
        if steps >= SEARCH_REACH {
            continue;
        }
        for (dx, dy) in AROUND {
            let (nx, ny) = (x + dx, y + dy);
            if !done.contains(&(nx, ny)) && v.seen.contains(nx, ny) && ch(w, nx, ny) != WATER {
                done.insert((nx, ny));
                queue.push_back((nx, ny, steps + 1));
            }
        }
    }
    None
}

// ---------------------------------------------------------------- stores

pub fn store_positions(w: &World) -> Vec<Pt> {
    let mut v = vec![w.store_at];
    v.extend(w.depots.iter().map(|d| (d.x, d.y)));
    v
}

pub fn store_inv(w: &World, i: usize) -> &Inv {
    if i == 0 {
        &w.store
    } else {
        &w.depots[i - 1].inv
    }
}

pub fn store_inv_mut(w: &mut World, i: usize) -> &mut Inv {
    if i == 0 {
        &mut w.store
    } else {
        &mut w.depots[i - 1].inv
    }
}

/// Indices of stores within reach, closest first (ties by creation order).
pub fn packs_near(w: &World, x: i64, y: i64, reach: i64) -> Vec<usize> {
    let mut close: Vec<(i64, usize)> = store_positions(w)
        .iter()
        .enumerate()
        .filter_map(|(i, (sx, sy))| {
            let d = dist(*sx, *sy, x, y);
            if d <= reach { Some((d, i)) } else { None }
        })
        .collect();
    close.sort();
    close.into_iter().map(|(_, i)| i).collect()
}

pub fn near_store(w: &World, vi: usize, reach: i64) -> bool {
    let v = &w.villagers[vi];
    !packs_near(w, v.x, v.y, reach).is_empty()
}

pub fn have(w: &World, vi: usize, item: &str) -> i64 {
    let v = &w.villagers[vi];
    inv_get(&v.inv, item) + packs_near(w, v.x, v.y, BUILD_REACH).iter().map(|i| inv_get(store_inv(w, *i), item)).sum::<i64>()
}

pub fn spend(w: &mut World, vi: usize, item: &str, mut n: i64) {
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let near = packs_near(w, vx, vy, BUILD_REACH);
    let own = &mut w.villagers[vi].inv;
    let taken = inv_get(own, item).min(n);
    inv_set(own, item, inv_get(own, item) - taken);
    n -= taken;
    for i in near {
        let pack = store_inv_mut(w, i);
        let taken = inv_get(pack, item).min(n);
        inv_set(pack, item, inv_get(pack, item) - taken);
        n -= taken;
    }
}

pub fn room(w: &World, vi: usize, item: &str) -> i64 {
    let r = rules();
    let load: i64 = w.villagers[vi].inv.iter().map(|(k, n)| n * r.weight(k)).sum();
    let limit = CARRY_LIMIT + if has(w, "pack_frames") { PACK_FRAME_BONUS } else { 0 };
    (limit - load).max(0).div_euclid(r.weight(item))
}

pub fn edible(inv: &Inv) -> i64 {
    rules().edible.iter().map(|k| inv_get(inv, k)).sum()
}

// ---------------------------------------------------------------- hidden-type helpers

/// `dict.get(item)` on a str-keyed dict: strings match, other hashables never do, lists and dicts raise.
fn hashable_item(item: &Value) -> R<Option<&str>> {
    match item {
        Value::Array(_) | Value::Object(_) => Err("TypeError: unhashable type".into()),
        Value::String(s) => Ok(Some(s)),
        _ => Ok(None),
    }
}

fn aget<'a>(act: &'a Value, k: &str) -> &'a Value {
    act.get(k).unwrap_or(&Value::Null)
}

fn intlike(v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) => n.as_i64(),
        _ => None,
    }
}

fn goods(raw: &Value) -> Option<Vec<(String, i64)>> {
    match raw {
        Value::Null => Some(vec![]),
        Value::Object(m) => {
            let mut out = Vec::new();
            for (k, n) in m {
                let n = match n {
                    Value::Number(num) => num.as_i64()?,
                    _ => return None,
                };
                if !rules().is_item(k) || n <= 0 {
                    return None;
                }
                out.push((k.clone(), n));
            }
            Some(out)
        }
        _ => None,
    }
}

// ---------------------------------------------------------------- actions

fn discover(w: &mut World, vi: usize) {
    if w.emptied < EMPTIED_FOR_FARMING || w.villagers.iter().any(|o| o.skills.iter().any(|s| s == "farming")) {
        return;
    }
    w.villagers[vi].skills.push("farming".into());
    let msg = format!("{} noticed seeds sprouting where the bushes were picked bare", w.villagers[vi].name);
    w.push_event(msg);
}

fn cut_tree(w: &mut World, x: i64, y: i64, amount: i64) -> i64 {
    let k = (x, y);
    let amount = amount.min(*w.stocks.get(&k).unwrap_or(&0));
    let left = w.stocks.get(&k).copied().unwrap_or(0) - amount;
    w.stocks.insert(k, left);
    if left <= 0 {
        w.stocks.remove(&k);
        w.changed.insert(k, GRASS);
        w.push_event(format!("The trees at ({},{}) are gone", x, y));
    }
    amount
}

fn gather_wood(w: &mut World, vi: usize, fx: &mut Effects) -> Out {
    let rm = room(w, vi, "wood");
    let name = w.villagers[vi].name.clone();
    if rm <= 0 {
        return out(1, &format!("{} cannot carry any more", name), "overloaded");
    }
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let mut best: Option<(i64, i64, i64)> = None;
    for dy in [-1, 0, 1] {
        for dx in [-1, 0, 1] {
            let (tx, ty) = (vx + dx, vy + dy);
            let stock = w.stocks.get(&(tx, ty)).copied().unwrap_or(0);
            if stock > 0 && (ch(w, tx, ty) == FOREST || w.woodlot_set.contains(&(tx, ty))) {
                let cand = (stock, tx, ty);
                if best.is_none_or(|b| cand > b) {
                    best = Some(cand);
                }
            }
        }
    }
    let Some((_, tx, ty)) = best else {
        return out(1, &format!("no wood within reach of ({},{})", vx, vy), "empty-handed");
    };
    let mut amount = (2 + if knows(w, "copper") { 1 } else { 0 }).min(rm);
    if w.woodlot_set.contains(&(tx, ty)) {
        amount = amount.min(w.stocks[&(tx, ty)]);
        *w.stocks.get_mut(&(tx, ty)).unwrap() -= amount;
    } else {
        amount = cut_tree(w, tx, ty, amount);
    }
    inv_add(&mut w.villagers[vi].inv, "wood", amount);
    w.villagers[vi].energy -= 1;
    fx.insert("gain".into(), json!({"wood": amount}));
    fx.insert("source".into(), json!([tx, ty]));
    ok(2, format!("gathered {} wood", amount))
}

pub fn herd_step(w: &World, hx: i64, hy: i64, rng: &mut PyRandom, reach: i64) -> Pt {
    let x = hx + rng.randint(-reach, reach);
    let y = hy + rng.randint(-reach, reach);
    let c = ch(w, x, y);
    if c == GRASS || c == FOREST {
        (x, y)
    } else {
        (hx, hy)
    }
}

fn hunt(w: &mut World, vi: usize, act: &Value, slots_left: i64, fx: &mut Effects) -> R<Out> {
    let kind_v = aget(act, "item");
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let herd_idx = w.herds.iter().position(|h| kind_v.as_str() == Some(h.kind.as_str()) && dist(h.x, h.y, vx, vy) <= HUNT_REACH);
    let kind_s = hashable_item(kind_v)?;
    let spec = kind_s.and_then(|k| rules().animal(k));
    let (Some(spec), Some(hi)) = (spec, herd_idx) else {
        return Ok(out(1, &format!("no {} close enough to hunt", pystr(kind_v)), "empty-handed"));
    };
    let kind = spec.kind.clone();
    if HUNT_SLOTS > slots_left {
        return Ok(out(slots_left, "not enough daylight left to hunt", "unfinished"));
    }
    let (hx, hy) = (w.herds[hi].x, w.herds[hi].y);
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:{}:hunt:{},{}", w.seed, w.day, w.villagers[vi].name, hx, hy));
    w.villagers[vi].energy -= 1;
    fx.insert("source".into(), json!([hx, hy]));
    if rng.random() < spec.gore {
        let v = &mut w.villagers[vi];
        v.health = 1.max(v.health - GORE_DAMAGE);
        v.feedback.push(format!("gored by a {}", kind));
    }
    if rng.random() >= spec.odds {
        let (nx, ny) = herd_step(w, hx, hy, &mut rng, 3);
        w.herds[hi].x = nx;
        w.herds[hi].y = ny;
        return Ok(ok(HUNT_SLOTS, format!("hunted {}, but they got away", kind)));
    }
    w.herds[hi].count -= 1;
    let meat = MEAT_PER_KILL.min(room(w, vi, "meat"));
    inv_add(&mut w.villagers[vi].inv, "meat", meat);
    fx.insert("gain".into(), json!({"meat": meat}));
    if w.herds[hi].count <= 0 {
        w.herds.remove(hi);
        let msg = format!("{} killed the last of a {} herd", w.villagers[vi].name, kind);
        w.push_event(msg);
    }
    Ok(ok(HUNT_SLOTS, format!("brought down a {}", kind)))
}

pub fn is_food(w: &World, x: i64, y: i64) -> bool {
    w.stocks.contains_key(&(x, y)) && ch(w, x, y) != FOREST && !w.woodlot_set.contains(&(x, y))
}

pub fn food_near(w: &World, vi: usize) -> Vec<Pt> {
    let v = &w.villagers[vi];
    let mut out = Vec::new();
    for dy in [-1, 0, 1] {
        for dx in [-1, 0, 1] {
            if is_food(w, v.x + dx, v.y + dy) {
                out.push((v.x + dx, v.y + dy));
            }
        }
    }
    out
}

pub fn ready_food(w: &World, vi: usize) -> Vec<(i64, i64, i64)> {
    let winter = season(w) == "winter";
    food_near(w, vi)
        .into_iter()
        .filter_map(|(x, y)| {
            let s = w.stocks[&(x, y)];
            if s > 0 && !(winter && ch(w, x, y) == BERRIES) { Some((s, x, y)) } else { None }
        })
        .collect()
}

fn gather_food(w: &mut World, vi: usize, fx: &mut Effects) -> Out {
    let name = w.villagers[vi].name.clone();
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    if food_near(w, vi).is_empty() {
        return out(1, &format!("no food within reach of ({},{})", vx, vy), "empty-handed");
    }
    let winter = season(w) == "winter";
    let ready = ready_food(w, vi);
    if ready.is_empty() {
        if winter {
            return out(1, "the bushes are bare for the winter", "empty-handed");
        }
        return out(1, "everything within reach has been picked bare", "empty-handed");
    }
    let (stock, tx, ty) = *ready.iter().max().unwrap();
    let wild = ch(w, tx, ty) == BERRIES;
    let item = if wild { "food" } else { "grain" };
    let foraging = w.villagers[vi].skills.iter().any(|s| s == "foraging");
    let amount = stock.min((if foraging && wild { 3 } else { 2 }) + bonus(w, "food")).min(room(w, vi, item));
    if amount <= 0 {
        return out(1, &format!("{} cannot carry any more", name), "overloaded");
    }
    w.stocks.insert((tx, ty), stock - amount);
    if stock == amount && wild {
        w.emptied += 1;
        discover(w, vi);
    }
    if !wild {
        let cur = w.soil.get(&(tx, ty)).copied().unwrap_or(1.0);
        w.soil.insert((tx, ty), f64::max(0.3, cur - SOIL_LOSS));
    }
    inv_add(&mut w.villagers[vi].inv, item, amount);
    w.villagers[vi].energy -= 1;
    fx.insert("gain".into(), json!({ item: amount }));
    fx.insert("source".into(), json!([tx, ty]));
    ok(2, format!("gathered {} {}", amount, item))
}

fn experiment_block(w: &World, vi: usize, idea: &Value) -> Option<String> {
    let v = &w.villagers[vi];
    let spec = idea.as_str().and_then(|i| rules().idea(i));
    let planted = idea.as_str().is_some_and(|i| w.guide.planted.iter().any(|p| p == i));
    let Some(spec) = spec.filter(|_| planted) else {
        return Some(format!("nobody has had the idea {}", repr(idea)));
    };
    let id = idea.as_str().unwrap();
    let lname = spec.name.to_lowercase();
    if knows(w, id) {
        return Some(format!("the village already knows {}", lname));
    }
    if spec.near.as_deref() == Some("water") && !near_tile(w, v.x, v.y, WATER, FIELD_WATER_RANGE) {
        return Some(format!("{} has to be tried near water", lname));
    }
    if spec.near.as_deref() == Some("fire") && !near_built(w, v.x, v.y, &["fire_pit"], 2) {
        return Some(format!("{} has to be tried beside a fire pit", lname));
    }
    let missing: Vec<(String, i64)> =
        spec.try_.iter().filter(|(k, n)| inv_get(&v.inv, k) < *n).map(|(k, n)| (k.clone(), n - inv_get(&v.inv, k))).collect();
    if !missing.is_empty() {
        return Some(format!("needs {} more to try {}", fmt_inv(&missing), lname));
    }
    None
}

fn experiment(w: &mut World, vi: usize, idea: &str, fx: &mut Effects) -> Out {
    let spec = rules().idea(idea).unwrap();
    let lname = spec.name.to_lowercase();
    for (k, n) in &spec.try_ {
        inv_add(&mut w.villagers[vi].inv, k, -*n);
    }
    w.villagers[vi].energy -= 1;
    let tries = w.guide.attempts.iter().find(|(k, _)| k == idea).map(|(_, n)| *n).unwrap_or(0);
    inv_set(&mut w.guide.attempts, idea, tries + 1);
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:{}:{}:{}", w.seed, w.day, w.villagers[vi].name, idea, tries));
    let chance = 0.4 + 0.15 * tries as f64 + if w.guide.trust >= TRUST_EAGER { 0.1 } else { 0.0 };
    fx.insert("experiment".into(), json!(idea));
    if rng.random() >= chance {
        fx.insert("worked".into(), json!(false));
        let line = format!("day {}: my {} attempt failed", w.day, lname);
        let lines = memory_lines(w);
        let v = &mut w.villagers[vi];
        v.memory.push(line);
        v.memory = last_n(&v.memory, lines);
        return ok(EXPERIMENT_SLOTS, format!("tried {}, but it failed", lname));
    }
    fx.insert("worked".into(), json!(true));
    w.guide.known.push(idea.to_string());
    w.guide.insight += 4;
    if let Some(skill) = &spec.skill {
        if !w.villagers[vi].skills.contains(skill) {
            w.villagers[vi].skills.push(skill.clone());
        }
    }
    let msg = format!("{} worked out {}", w.villagers[vi].name, lname);
    w.push_event(msg);
    ok(EXPERIMENT_SLOTS, format!("worked out {}", lname))
}

fn use_store(w: &mut World, vi: usize, verb: &str, act: &Value) -> Out {
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let name = w.villagers[vi].name.clone();
    let packs = packs_near(w, vx, vy, STORE_REACH);
    if packs.is_empty() {
        return out(1, &format!("{} is too far from any store", name), "too far");
    }
    let pack = packs[0];
    let item_v = aget(act, "item");
    let item = match item_v.as_str() {
        Some(s) if rules().is_item(s) => s.to_string(),
        _ => return out(1, &format!("there is no {} to move", repr(item_v)), "confused"),
    };
    let want = match act.get("n") {
        Some(Value::Number(n)) if n.as_i64().is_some_and(|i| i > 0) => n.as_i64().unwrap(),
        _ => 1_000_000,
    };
    if verb == "deposit" {
        let n = want.min(inv_get(&w.villagers[vi].inv, &item));
        if n <= 0 {
            return out(1, &format!("{} is not carrying {}", name, item), "empty-handed");
        }
        inv_add(&mut w.villagers[vi].inv, &item, -n);
        let p = store_inv_mut(w, pack);
        inv_add(p, &item, n);
        return ok(1, format!("stored {} {}", n, item));
    }
    let n = want.min(inv_get(store_inv(w, pack), &item)).min(room(w, vi, &item));
    if n <= 0 {
        return out(1, &format!("cannot take {}: the store has none or the pack is full", item), "empty-handed");
    }
    inv_add(store_inv_mut(w, pack), &item, -n);
    inv_add(&mut w.villagers[vi].inv, &item, n);
    ok(1, format!("took {} {} from the store", n, item))
}

/// Validate and apply one action. Returns (slots_used, error_or_None, summary).
pub fn execute(w: &mut World, vi: usize, act: &Value, slots_left: i64, fx: &mut Effects) -> R<Out> {
    let r = rules();
    if !act.is_object() {
        return Ok(out(1, "that was not an action", "confused"));
    }
    let verb_v = aget(act, "verb");
    let verb = match verb_v.as_str() {
        Some(s) if r.is_verb(s) => s,
        _ => return Ok(out(1, &format!("there is no action called {}", repr(verb_v)), "confused")),
    };
    let name = w.villagers[vi].name.clone();
    if verb != "rest" && w.villagers[vi].energy <= 0 {
        return Ok(out(1, "too tired to do anything but rest", "slumped"));
    }
    match verb {
        "rest" => {
            let v = &mut w.villagers[vi];
            v.energy = MAX_ENERGY.min(v.energy + 3);
            return Ok(ok(1, "rested".into()));
        }
        "look" => {
            w.villagers[vi].energy -= 1;
            let new = reveal(w, vi);
            return Ok(ok(1, format!("looked around ({} new tiles)", new)));
        }
        "walk" => {
            let (xv, yv) = (aget(act, "x"), aget(act, "y"));
            let is_int = |v: &Value| matches!(v, Value::Number(n) if n.is_i64() || n.is_u64()) || v.is_boolean();
            if !(is_int(xv) && is_int(yv)) {
                return Ok(out(1, "walk needs a place on the map (x,y)", "confused"));
            }
            let (x, y) = match (intlike(xv), intlike(yv)) {
                (Some(x), Some(y)) => (x, y),
                _ => {
                    return Ok(out(
                        1,
                        &format!("{} has never seen ({},{}) and cannot head there", name, pystr(xv), pystr(yv)),
                        "lost",
                    ))
                }
            };
            if !w.villagers[vi].seen.contains(x, y) {
                return Ok(out(1, &format!("{} has never seen ({},{}) and cannot head there", name, x, y), "lost"));
            }
            if tile_name(ch(w, x, y))? == "water" {
                return Ok(out(1, &format!("({},{}) is water; stand beside it instead", x, y), "wet feet"));
            }
            let Some(mut path) = find_path(w, vi, x, y) else {
                return Ok(out(1, &format!("{} knows no way to reach ({},{})", name, x, y), "lost"));
            };
            let short = path.len() as i64 - 1 > slots_left * WALK_PER_SLOT;
            if short {
                path.truncate((slots_left * WALK_PER_SLOT + 1) as usize);
            }
            let cost = 1.max(-((-(path.len() as i64 - 1)).div_euclid(WALK_PER_SLOT)));
            fx.insert("path".into(), Value::Array(path.iter().map(|p| pt_to_value(*p)).collect()));
            let last = *path.last().unwrap();
            w.villagers[vi].x = last.0;
            w.villagers[vi].y = last.1;
            w.villagers[vi].energy -= 1;
            let new = reveal(w, vi);
            let v = &w.villagers[vi];
            let wh = if short {
                format!("walked toward ({},{}), and stopped at ({},{}) for the night", x, y, v.x, v.y)
            } else {
                format!("walked to ({},{})", x, y)
            };
            return Ok(ok(cost, wh + &if new != 0 { format!(", saw {} new tiles", new) } else { String::new() }));
        }
        "deposit" | "take" => return Ok(use_store(w, vi, verb, act)),
        "hunt" => return hunt(w, vi, act, slots_left, fx),
        "gather" => {
            let item_v = aget(act, "item");
            let item = match item_v.as_str() {
                Some(s) if r.is_item(s) => s.to_string(),
                _ => {
                    return Ok(out(
                        1,
                        &format!("cannot gather {}; try wood, stone, food or water", repr(item_v)),
                        "confused",
                    ))
                }
            };
            if item == "food" {
                return Ok(gather_food(w, vi, fx));
            }
            if item == "grain" || item == "meat" {
                return Ok(out(
                    1,
                    &format!("{} comes from fields and hunting; gather food at a field, or hunt", item),
                    "confused",
                ));
            }
            if item == "wood" {
                return Ok(gather_wood(w, vi, fx));
            }
            let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
            for dy in [-1, 0, 1] {
                for dx in [-1, 0, 1] {
                    let (tx, ty) = (vx + dx, vy + dy);
                    if r.yields(tile_name(ch(w, tx, ty))?) == Some(item.as_str()) {
                        let amount = (if knows(w, "copper") && item == "stone" { 3 } else { 2 }).min(room(w, vi, &item));
                        if amount <= 0 {
                            return Ok(out(1, &format!("{} cannot carry any more", name), "overloaded"));
                        }
                        inv_add(&mut w.villagers[vi].inv, &item, amount);
                        w.villagers[vi].energy -= 1;
                        fx.insert("gain".into(), json!({ &item: amount }));
                        fx.insert("source".into(), json!([tx, ty]));
                        return Ok(ok(2, format!("gathered {} {}", amount, item)));
                    }
                }
            }
            return Ok(out(1, &format!("no {} within reach of ({},{})", item, vx, vy), "empty-handed"));
        }
        "build" => return build(w, vi, act, slots_left, fx),
        "experiment" => {
            let idea = aget(act, "item");
            if let Some(block) = experiment_block(w, vi, idea) {
                return Ok((1, Some(block), "puzzled".into()));
            }
            if EXPERIMENT_SLOTS > slots_left {
                return Ok(out(slots_left, "not enough daylight left to try that", "unfinished"));
            }
            return Ok(experiment(w, vi, idea.as_str().unwrap(), fx));
        }
        _ => {}
    }

    // social verbs
    let target_v = act.get("target").cloned().unwrap_or(Value::String(String::new()));
    let want = pystr(&target_v).to_lowercase();
    let oi = w.villagers.iter().position(|o| o.name.to_lowercase() == want);
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let oi = match oi {
        Some(i) if i != vi => i,
        _ => {
            return Ok(out(
                1,
                &format!("there is nobody called {} to {}", repr(aget(act, "target")), verb),
                "talking to air",
            ))
        }
    };
    let oname = w.villagers[oi].name.clone();
    if dist(vx, vy, w.villagers[oi].x, w.villagers[oi].y) > TALK_RANGE {
        return Ok(out(1, &format!("{} is too far away to {}", oname, verb), "shouted into the wind"));
    }
    fx.insert("target".into(), json!(oname));
    w.villagers[vi].energy -= 1;
    if verb == "talk" {
        let raw = act.get("text").map(pystr).unwrap_or_default();
        let text = head(pyfmt::strip(&raw), 80);
        if text.is_empty() {
            return Ok(out(1, "had nothing to say", "silent"));
        }
        let line = format!("{}: {}", name, text);
        let o = &mut w.villagers[oi];
        o.heard.push(line);
        o.heard = last_n(&o.heard, HEARD_LINES);
        fx.insert("say".into(), json!(text));
        return Ok(ok(1, format!("told {} \"{}\"", oname, text)));
    }
    if verb == "trade" {
        let (give, get) = (goods(aget(act, "give")), goods(aget(act, "get")));
        let (Some(give), Some(get)) = (give, get) else {
            return Ok(out(1, "a trade needs goods, for example give wood 2, get food 2", "confused"));
        };
        if give.is_empty() && get.is_empty() {
            return Ok(out(1, "a trade needs goods, for example give wood 2, get food 2", "confused"));
        }
        if give.iter().any(|(k, n)| inv_get(&w.villagers[vi].inv, k) < *n) {
            return Ok(out(1, &format!("{} lacks the goods to give", name), "empty-handed"));
        }
        if get.iter().any(|(k, n)| inv_get(&w.villagers[oi].inv, k) < *n) {
            return Ok(out(1, &format!("{} lacks the goods to give back", oname), "empty-handed"));
        }
        for (k, n) in &give {
            inv_add(&mut w.villagers[vi].inv, k, -*n);
            inv_add(&mut w.villagers[oi].inv, k, *n);
        }
        for (k, n) in &get {
            inv_add(&mut w.villagers[oi].inv, k, -*n);
            inv_add(&mut w.villagers[vi].inv, k, *n);
        }
        return Ok(ok(1, format!("traded with {}", oname)));
    }
    // teach
    let skill_v = aget(act, "item");
    let skill = skill_v.as_str();
    if !skill.is_some_and(|s| w.villagers[vi].skills.iter().any(|k| k == s)) {
        return Ok(out(1, &format!("{} cannot teach {}", name, repr(skill_v)), "unsure"));
    }
    let skill = skill.unwrap();
    if w.villagers[oi].skills.iter().any(|k| k == skill) {
        return Ok(out(1, &format!("{} already knows {}", oname, skill), "redundant"));
    }
    w.villagers[oi].skills.push(skill.to_string());
    Ok(ok(if has(w, "patient_teaching") { 1 } else { 2 }, format!("taught {} {}", oname, skill)))
}

fn build(w: &mut World, vi: usize, act: &Value, slots_left: i64, fx: &mut Effects) -> R<Out> {
    let r = rules();
    let name_v = aget(act, "item");
    let name_s = hashable_item(name_v)?;
    let Some((name, spec)) = name_s.and_then(|n| r.building(n).map(|b| (n, b))) else {
        let known: Vec<&str> = r.buildings.iter().map(|(n, _)| n.as_str()).collect();
        return Ok(out(1, &format!("nobody knows how to build {} (known: {})", repr(name_v), known.join(", ")), "confused"));
    };
    if let Some(idea) = &spec.idea {
        if !knows(w, idea) {
            return Ok(out(1, &format!("nobody has worked out {} yet", r.idea(idea).unwrap().name.to_lowercase()), "unsure"));
        }
    }
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    let vname = w.villagers[vi].name.clone();
    if let Some(skill) = &spec.skill {
        if !w.villagers[vi].skills.contains(skill) {
            return Ok(out(1, &format!("{} does not know {}", vname, skill), "unsure"));
        }
    }
    if tile_name(ch(w, vx, vy))? != "grass" || w.built.iter().any(|b| b.x == vx && b.y == vy) {
        return Ok(out(1, "needs open grass to build on", "blocked"));
    }
    if let Some(nw) = spec.near_water {
        if nw != 0 && !near_tile(w, vx, vy, WATER, nw) {
            return Ok(out(1, &format!("a {} must be within {} tiles of water", name, nw), "too dry"));
        }
    }
    if store_positions(w).contains(&(vx, vy)) {
        return Ok(out(1, "that spot already holds a store", "blocked"));
    }
    let missing: Vec<(String, i64)> =
        spec.cost.iter().filter(|(k, n)| have(w, vi, k) < *n).map(|(k, n)| (k.clone(), n - have(w, vi, k))).collect();
    if !missing.is_empty() {
        return Ok(out(1, &format!("needs {} more to build {}", fmt_inv(&missing), name), "short of materials"));
    }
    if w.built.iter().filter(|b| b.kind == name).count() as i64 >= spec.max {
        return Ok(out(1, &format!("the camp already has enough of {}", name), "redundant"));
    }
    if spec.slots > slots_left {
        return Ok(out(slots_left, &format!("not enough daylight left to build {}", name), "unfinished"));
    }
    for (k, n) in &spec.cost {
        spend(w, vi, k, *n);
    }
    let mut extra = Map::new();
    extra.insert("by".into(), json!(vname));
    extra.insert("day".into(), json!(w.day));
    let built = Built { kind: name.to_string(), x: vx, y: vy, lit: None, extra };
    fx.insert("built".into(), built.to_value());
    w.built.push(built);
    if name == "field" || name == "woodlot" {
        w.stocks.insert((vx, vy), 0);
    }
    if name == "woodlot" {
        w.woodlots.push((vx, vy));
        w.woodlot_set.insert((vx, vy));
    }
    if name == "depot" {
        w.depots.push(Depot { x: vx, y: vy, inv: vec![], extra: Map::new() });
    }
    w.villagers[vi].energy -= 1;
    Ok(ok(spec.slots, format!("built a {}", name)))
}

// ---------------------------------------------------------------- instincts

pub fn describe_action(a: &Value) -> String {
    let verb = aget(a, "verb");
    match verb.as_str() {
        Some("walk") => format!("walk to ({},{})", pystr(aget(a, "x")), pystr(aget(a, "y"))),
        Some("gather") => format!("gather {}", pystr(aget(a, "item"))),
        Some("build") => format!("build {}", pystr(aget(a, "item"))),
        Some("trade") => format!("trade with {}", pystr(aget(a, "target"))),
        Some(v @ ("talk" | "teach")) => {
            let extra = if v == "teach" {
                pystr(aget(a, "item"))
            } else {
                let text = a.get("text").map(pystr).unwrap_or_default();
                pyfmt::str_repr(&head(&text, 40))
            };
            format!("{} {} {}", v, pystr(aget(a, "target")), extra)
        }
        _ => pystr(verb),
    }
}

fn walk_act(x: i64, y: i64) -> Value {
    json!({"verb": "walk", "x": x, "y": y})
}

pub fn beside(w: &World, vi: usize, x: i64, y: i64) -> Option<Pt> {
    search(w, vi, None, true, &mut |a, b| a == x && b == y)
}

pub fn nearest_resource(w: &World, vi: usize, kind: &str) -> Option<Pt> {
    let c = rules().char_of(kind);
    let v = &w.villagers[vi];
    search(w, vi, None, true, &mut |x, y| v.seen.contains(x, y) && ch(w, x, y) == c)
}

pub fn nearest_food(w: &World, vi: usize) -> Option<Pt> {
    let winter = season(w) == "winter";
    let v = &w.villagers[vi];
    search(w, vi, None, true, &mut |x, y| {
        v.seen.contains(x, y)
            && w.stocks.get(&(x, y)).copied().unwrap_or(0) > 0
            && is_food(w, x, y)
            && !(winter && ch(w, x, y) == BERRIES)
    })
}

pub fn home(w: &World, vi: usize) -> Option<Pt> {
    let v = &w.villagers[vi];
    let mut homes: Vec<(i64, i64, i64)> = w
        .built
        .iter()
        .filter(|b| matches!(b.kind.as_str(), "fire_pit" | "lean_to" | "hut"))
        .map(|b| (dist(v.x, v.y, b.x, b.y), b.x, b.y))
        .collect();
    if homes.is_empty() {
        homes = store_positions(w).iter().map(|(x, y)| (dist(v.x, v.y, *x, *y), *x, *y)).collect();
    }
    homes.sort();
    if homes[0].0 <= 2 {
        return Some((v.x, v.y));
    }
    let s = season(w);
    if homes[0].0 > HOME_REACH && (!(s == "autumn" || s == "winter") || homes[0].0 > SEARCH_REACH) {
        return Some((v.x, v.y));
    }
    beside(w, vi, homes[0].1, homes[0].2)
}

pub fn open_ground(w: &World, vi: usize) -> Option<Pt> {
    let mut taken: HSet<Pt> = w.built.iter().map(|b| (b.x, b.y)).collect();
    taken.extend(store_positions(w));
    let v = &w.villagers[vi];
    search(w, vi, None, false, &mut |x, y| !taken.contains(&(x, y)) && ch(w, x, y) == GRASS && v.seen.contains(x, y))
}

fn gather_trip(w: &World, vi: usize, item: &str, kind: &str) -> Vec<Value> {
    match nearest_resource(w, vi, kind) {
        Some(spot) => vec![walk_act(spot.0, spot.1), json!({"verb": "gather", "item": item}), json!({"verb": "gather", "item": item})],
        None => vec![],
    }
}

fn focus_shelter(w: &World, vi: usize) -> Vec<Value> {
    let hut = rules().building("hut").unwrap();
    if w.built.iter().filter(|b| b.kind == "hut").count() as i64 >= hut.max {
        return vec![];
    }
    let near_camp = near_store(w, vi, BUILD_REACH);
    let stored: Vec<(&str, i64)> = hut.cost.iter().map(|(k, _)| (k.as_str(), have(w, vi, k))).collect();
    let got = |k: &str| stored.iter().find(|(n, _)| *n == k).map(|(_, v)| *v).unwrap_or(0);
    if hut.cost.iter().all(|(k, n)| got(k) >= *n) {
        return match open_ground(w, vi) {
            Some(spot) => {
                let mut acts = if near_camp { vec![] } else { vec![walk_act(spot.0, spot.1)] };
                acts.push(walk_act(spot.0, spot.1));
                acts.push(json!({"verb": "build", "item": "hut"}));
                acts
            }
            None => vec![],
        };
    }
    let wood_cost = hut.cost.iter().find(|(k, _)| k == "wood").map(|(_, n)| *n).unwrap_or(0);
    if got("wood") < wood_cost {
        return gather_trip(w, vi, "wood", "forest");
    }
    gather_trip(w, vi, "stone", "rock")
}

fn focus_learn(w: &World, vi: usize) -> Vec<Value> {
    let v = &w.villagers[vi];
    let kinds = [("wood", "forest"), ("stone", "rock")];
    for idea in &w.guide.planted {
        if knows(w, idea) {
            continue;
        }
        let spec = rules().idea(idea).unwrap();
        for (item, n) in &spec.try_ {
            if inv_get(&v.inv, item) < *n {
                if let Some((_, kind)) = kinds.iter().find(|(k, _)| k == item) {
                    return gather_trip(w, vi, item, kind);
                }
            }
        }
        if spec.try_.iter().any(|(k, n)| inv_get(&v.inv, k) < *n) {
            continue;
        }
        let mut place = None;
        match spec.near.as_deref() {
            Some("water") => {
                place = if near_tile(w, v.x, v.y, WATER, FIELD_WATER_RANGE) { None } else { nearest_resource(w, vi, "water") };
            }
            Some("fire") => {
                let fires: Vec<&Built> = w.built.iter().filter(|b| b.kind == "fire_pit").collect();
                if fires.is_empty() {
                    continue;
                }
                if dist(fires[0].x, fires[0].y, v.x, v.y) > 2 {
                    place = beside(w, vi, fires[0].x, fires[0].y);
                }
            }
            _ => {}
        }
        let mut acts = Vec::new();
        if let Some(p) = place {
            acts.push(walk_act(p.0, p.1));
        }
        acts.push(json!({"verb": "experiment", "item": idea}));
        return acts;
    }
    vec![]
}

fn deliver(w: &World, vi: usize, items: &[&str]) -> Vec<Value> {
    let v = &w.villagers[vi];
    let stores = store_positions(w);
    let mut best = stores[0];
    let mut bd = dist(best.0, best.1, v.x, v.y);
    for s in &stores[1..] {
        let d = dist(s.0, s.1, v.x, v.y);
        if d < bd {
            best = *s;
            bd = d;
        }
    }
    let deposits = || items.iter().map(|i| json!({"verb": "deposit", "item": i})).collect::<Vec<_>>();
    if near_store(w, vi, STORE_REACH) {
        return deposits();
    }
    match beside(w, vi, best.0, best.1) {
        Some(spot) => {
            let mut acts = vec![walk_act(spot.0, spot.1)];
            acts.extend(deposits());
            acts
        }
        None => vec![],
    }
}

fn nearest_herd(w: &World, vi: usize) -> Option<usize> {
    let v = &w.villagers[vi];
    let mut best: Option<(i64, usize)> = None;
    for (i, h) in w.herds.iter().enumerate() {
        let d = dist(h.x, h.y, v.x, v.y);
        if d <= VISION + 2 && best.is_none_or(|(bd, _)| d < bd) {
            best = Some((d, i));
        }
    }
    best.map(|(_, i)| i)
}

pub fn scout(w: &World, vi: usize) -> Vec<Value> {
    let v = &w.villagers[vi];
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:{}", w.seed, v.name, (w.day - 1).div_euclid(SEASON_DAYS)));
    let angle = rng.random() * std::f64::consts::TAU;
    let (hx, hy) = (angle.cos(), angle.sin());
    let mut best: Option<Pt> = None;
    let mut best_score = f64::NEG_INFINITY;
    search(w, vi, None, false, &mut |x, y| {
        if !v.seen.contains(x + 1, y) || !v.seen.contains(x - 1, y) || !v.seen.contains(x, y + 1) || !v.seen.contains(x, y - 1) {
            let score = (x - v.x) as f64 * hx + (y - v.y) as f64 * hy;
            if score > best_score {
                best = Some((x, y));
                best_score = score;
            }
        }
        false
    });
    match best {
        Some((x, y)) => vec![walk_act(x, y), json!({"verb": "look"})],
        None => vec![],
    }
}

pub fn instinct_actions(w: &World, vi: usize) -> Vec<Value> {
    let v = &w.villagers[vi];
    let now = season(w);
    let home = home(w, vi);
    let go_home: Vec<Value> = match home {
        Some(h) if h != (v.x, v.y) => vec![walk_act(h.0, h.1)],
        _ => vec![],
    };
    let rest = || json!({"verb": "rest"});
    let cat = |mut a: Vec<Value>, b: &Vec<Value>| {
        a.extend(b.iter().cloned());
        a
    };
    if v.energy <= 2 {
        return cat(go_home.clone(), &vec![rest(), rest()]);
    }
    let sheltered = near_built(w, v.x, v.y, &["lean_to", "hut", "stone_house"], HOME_REACH);
    let lean_wood = rules().building("lean_to").unwrap().cost.iter().find(|(k, _)| k == "wood").map(|(_, n)| *n).unwrap_or(0);
    if !sheltered && inv_get(&v.inv, "wood") >= lean_wood {
        if let Some(spot) = open_ground(w, vi) {
            return vec![walk_act(spot.0, spot.1), json!({"verb": "build", "item": "lean_to"})];
        }
    }
    let focus: Option<&str> = if w.guide.trust >= TRUST_HEEDED { w.guide.focus.as_deref() } else { None };
    let people = w.villagers.len() as i64;
    let own = edible(&v.inv);
    let nearby = packs_near(w, v.x, v.y, HOME_REACH);
    let stored: i64 = nearby.iter().map(|i| edible(store_inv(w, *i))).sum();
    let wood_stored: i64 = nearby.iter().map(|i| inv_get(store_inv(w, *i), "wood")).sum();
    let has_fire = near_built(w, v.x, v.y, &["fire_pit"], HOME_REACH);
    let mut acts: Vec<Value> = vec![];
    if !near_tile(w, v.x, v.y, WATER, WATER_RANGE) && inv_get(&v.inv, "water") < 1 {
        acts = gather_trip(w, vi, "water", "water");
    }
    if acts.is_empty() && own < 2 && stored > 0 {
        let item = rules().edible.iter().find(|k| nearby.iter().any(|i| inv_get(store_inv(w, *i), k) > 0)).cloned().unwrap();
        let mut best: Option<(i64, Pt)> = None;
        for (i, pos) in store_positions(w).iter().enumerate() {
            if inv_get(store_inv(w, i), &item) > 0 {
                let d = dist(pos.0, pos.1, v.x, v.y);
                if best.is_none_or(|(bd, _)| d < bd) {
                    best = Some((d, *pos));
                }
            }
        }
        let (_, (x, y)) = best.unwrap();
        if let Some(spot) = beside(w, vi, x, y) {
            acts = vec![walk_act(spot.0, spot.1), json!({"verb": "take", "item": item, "n": 3})];
        }
    }
    let enough = 3 + match focus {
        Some("food") => 3,
        Some("explore") => -1,
        _ => 0,
    };
    let stocking = (now == "summer" || now == "autumn") && stored < 4 * people;
    if acts.is_empty() && (own < enough || stocking) {
        let herd = nearest_herd(w, vi);
        let spot = nearest_food(w, vi);
        if let Some(hi) = herd {
            if spot.is_none() || own < 2 {
                let h = &w.herds[hi];
                if let Some(near) = beside(w, vi, h.x, h.y) {
                    acts = vec![walk_act(near.0, near.1), json!({"verb": "hunt", "item": h.kind})];
                }
            }
        }
        if acts.is_empty() {
            if let Some(s) = spot {
                acts = vec![walk_act(s.0, s.1), json!({"verb": "gather", "item": "food"}), json!({"verb": "gather", "item": "food"})];
            }
        }
        if !acts.is_empty() && stocking && own >= 2 {
            acts.extend(deliver(w, vi, &["grain", "food", "meat"]));
        }
        if acts.is_empty() && own < 2 && stored <= 0 && now != "winter" {
            acts = scout(w, vi);
            if !acts.is_empty() {
                return acts;
            }
        }
    }
    if acts.is_empty() && has_fire && wood_stored < 3 && now != "winter" {
        acts = gather_trip(w, vi, "wood", "forest");
        if !acts.is_empty() {
            acts.extend(deliver(w, vi, &["wood"]));
        }
    }
    if acts.is_empty() && !sheltered {
        acts = gather_trip(w, vi, "wood", "forest");
    }
    if acts.is_empty() && focus == Some("shelter") && sheltered {
        acts = focus_shelter(w, vi);
        if acts.last().is_some_and(|a| a.get("verb").and_then(|v| v.as_str()) == Some("gather")) {
            acts.extend(deliver(w, vi, &["wood", "stone"]));
        }
    }
    if acts.is_empty() && focus == Some("learn") {
        acts = focus_learn(w, vi);
    }
    if acts.is_empty() && (now == "autumn" || now == "winter") {
        return cat(go_home, &vec![rest()]);
    }
    if acts.is_empty() {
        acts = scout(w, vi);
    }
    if acts.is_empty() {
        acts = vec![rest()];
    }
    acts.extend(go_home);
    acts
}

// ---------------------------------------------------------------- habit gates

fn nothing_to_do(w: &World, vi: usize, act: &Value) -> R<bool> {
    let v = &w.villagers[vi];
    let verb = aget(act, "verb").as_str();
    let item_v = aget(act, "item");
    match verb {
        Some("deposit") => {
            let item = hashable_item(item_v)?;
            Ok(item.map_or(0, |i| inv_get(&v.inv, i)) <= 0 || !near_store(w, vi, STORE_REACH))
        }
        Some("take") => {
            let item = hashable_item(item_v)?;
            let packs = packs_near(w, v.x, v.y, STORE_REACH);
            if packs.is_empty() || item.map_or(0, |i| inv_get(store_inv(w, packs[0]), i)) <= 0 {
                return Ok(true);
            }
            match item {
                Some(i) => Ok(room(w, vi, i) <= 0),
                None => Ok(true),
            }
        }
        Some("gather") => match item_v.as_str() {
            Some(i) if rules().is_item(i) => Ok(room(w, vi, i) <= 0),
            _ => Ok(false),
        },
        Some("hunt") => Ok(!w.herds.iter().any(|h| item_v.as_str() == Some(h.kind.as_str()) && dist(h.x, h.y, v.x, v.y) <= HUNT_REACH)),
        _ => Ok(false),
    }
}

fn can_build(w: &World, vi: usize, act: &Value) -> R<bool> {
    let item_v = aget(act, "item");
    let name = hashable_item(item_v)?;
    let Some((name, spec)) = name.and_then(|n| rules().building(n).map(|b| (n, b))) else {
        return Ok(false);
    };
    let v = &w.villagers[vi];
    Ok(spec.cost.iter().all(|(k, n)| have(w, vi, k) >= *n)
        && (w.built.iter().filter(|b| b.kind == name).count() as i64) < spec.max
        && spec.skill.as_ref().is_none_or(|s| v.skills.contains(s))
        && spec.idea.as_ref().is_none_or(|i| knows(w, i)))
}

// ---------------------------------------------------------------- night, growth

fn eat(w: &mut World, vi: usize) -> bool {
    let edible_items = &rules().edible;
    for item in edible_items {
        if inv_get(&w.villagers[vi].inv, item) > 0 {
            inv_add(&mut w.villagers[vi].inv, item, -1);
            return true;
        }
    }
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    for i in packs_near(w, vx, vy, SHELTER_RANGE) {
        for item in edible_items {
            if inv_get(store_inv(w, i), item) > 0 {
                inv_add(store_inv_mut(w, i), item, -1);
                return true;
            }
        }
    }
    false
}

fn drink(w: &mut World, vi: usize) -> bool {
    let (vx, vy) = (w.villagers[vi].x, w.villagers[vi].y);
    if near_tile(w, vx, vy, WATER, WATER_RANGE) {
        return true;
    }
    if inv_get(&w.villagers[vi].inv, "water") > 0 {
        inv_add(&mut w.villagers[vi].inv, "water", -1);
        return true;
    }
    for i in packs_near(w, vx, vy, SHELTER_RANGE) {
        if inv_get(store_inv(w, i), "water") > 0 {
            inv_add(store_inv_mut(w, i), "water", -1);
            return true;
        }
    }
    false
}

pub fn rot(pack: &mut Inv) -> i64 {
    let mut lost = 0;
    for (item, share) in &rules().rot_by_item {
        let spoiled = inv_get(pack, item).div_euclid(*share);
        if spoiled != 0 {
            inv_add(pack, item, -spoiled);
            lost += spoiled;
        }
    }
    lost
}

fn night(w: &mut World, vi: usize, entry: &mut Map<String, Value>) -> Option<&'static str> {
    let ate = eat(w, vi);
    {
        let v = &mut w.villagers[vi];
        v.hungry = if ate { 0 } else { v.hungry + 1 };
        if !ate {
            v.feedback.push("went to sleep hungry".into());
        }
    }
    let drank = drink(w, vi);
    let dry = if drank { 0 } else { w.villagers[vi].dry.unwrap_or(0) + 1 };
    w.villagers[vi].dry = Some(dry);
    if !drank {
        w.villagers[vi].feedback.push("went to sleep thirsty".into());
    }
    let parched = dry >= 2;
    let (x, y) = (w.villagers[vi].x, w.villagers[vi].y);
    let stored = w.built.iter().any(|b| b.kind == "drying_rack") || near_built(w, x, y, &["storehouse"], SHELTER_RANGE);
    let rotted = if stored { 0 } else { rot(&mut w.villagers[vi].inv) };
    if rotted != 0 {
        w.villagers[vi].feedback.push(format!("{} food rotted overnight", rotted));
    }
    let shelter = near_built(w, x, y, &["lean_to", "hut", "stone_house"], SHELTER_RANGE);
    let warm = shelter || lit_fire_near(w, x, y);
    let cold = season(w) == "winter" && !warm;
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:{}:night", w.seed, w.day, w.villagers[vi].name));
    let exposed = if shelter { 0.4 } else { 1.0 };
    let bitten = !lit_fire_near(w, x, y) && rng.random() < WOLF_CHANCE * exposed;
    let harm = (if ate { 0 } else { 1 }) + (if parched { 1 } else { 0 }) + (if cold { 1 } else { 0 }) + (if bitten { WOLF_BITE } else { 0 });
    let mh = max_health(w);
    let rest = bonus(w, "rest");
    let v = &mut w.villagers[vi];
    if cold {
        v.feedback.push("nearly froze in the open".into());
    }
    if bitten {
        v.feedback.push("wolves attacked in the night".into());
    }
    v.health = mh.min(v.health + if harm == 0 { 1 } else { -harm });
    let recovery = (if ate { OVERNIGHT_ENERGY } else { HUNGRY_ENERGY }) + rest;
    v.energy = MAX_ENERGY.min(0.max(v.energy) + recovery);
    let mut night = Map::new();
    night.insert("ate".into(), json!(ate));
    night.insert("drank".into(), json!(drank));
    night.insert("cold".into(), json!(cold));
    night.insert("bitten".into(), json!(bitten));
    night.insert("health".into(), json!(v.health));
    if let Value::Object(p) = pose(v) {
        night.extend(p);
    }
    entry.insert("night".into(), Value::Object(night));
    if v.health > 0 {
        return None;
    }
    Some(if bitten { "wolves" } else if cold { "the cold" } else if parched { "thirst" } else { "hunger" })
}

fn burn_fuel(w: &mut World, events: &mut Vec<String>) {
    let fires: Vec<usize> = (0..w.built.len()).filter(|i| w.built[*i].kind == "fire_pit").collect();
    let positions = store_positions(w);
    for fi in &fires {
        let (fx, fy) = (w.built[*fi].x, w.built[*fi].y);
        let pack = positions
            .iter()
            .enumerate()
            .find(|(i, (x, y))| dist(*x, *y, fx, fy) <= FIRE_FUEL_REACH && inv_get(store_inv(w, *i), "wood") > 0)
            .map(|(i, _)| i);
        if let Some(i) = pack {
            inv_add(store_inv_mut(w, i), "wood", -1);
            if !w.built[*fi].is_lit() {
                events.push("The fire is lit again".into());
            }
            w.built[*fi].lit = Some(true);
        } else {
            if w.built[*fi].is_lit() {
                events.push("The fire went out: no wood in the store".into());
            }
            w.built[*fi].lit = Some(false);
        }
    }
    w.fire_out = fires.iter().any(|i| !w.built[*i].is_lit());
}

fn beds(w: &World) -> i64 {
    let extra: i64 = w.built.iter().map(|b| match b.kind.as_str() { "hut" => 2, "stone_house" => 3, _ => 0 }).sum();
    MAX_VILLAGERS.min(3 + extra)
}

pub fn arrival(w: &mut World, events: &mut Vec<String>) {
    let n = w.villagers.len();
    let stored: i64 = (0..store_positions(w).len()).map(|i| edible(store_inv(w, i))).sum();
    let carried: i64 = w.villagers.iter().map(|v| edible(&v.inv)).sum();
    if n == 0 || n as i64 >= beds(w) || carried + stored < 2 * n as i64 {
        return;
    }
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:arrival", w.seed, w.day));
    let dead_names: Vec<&str> = w.dead.iter().filter_map(|d| d.get("name").and_then(|n| n.as_str())).collect();
    let names: Vec<&String> = rules()
        .wanderers
        .iter()
        .filter(|n| !w.villagers.iter().any(|v| &v.name == *n) && !dead_names.contains(&n.as_str()))
        .collect();
    if names.is_empty() || rng.random() > 0.25 {
        return;
    }
    let (cx, cy) = match w.built.iter().find(|b| b.kind == "hut" || b.kind == "stone_house") {
        Some(b) => (b.x, b.y),
        None => (w.villagers[0].x, w.villagers[0].y),
    };
    let traits = ["quiet and watchful", "cheerful and reckless", "stubborn, proud of their work", "kind, always sharing food"];
    let trait_ = traits[rng.choice_index(4)];
    let skill = rules().skills[rng.choice_index(3)].clone();
    let name = names[0].clone();
    let v = Villager {
        name: name.clone(),
        trait_: trait_.into(),
        x: cx,
        y: cy,
        energy: MAX_ENERGY,
        health: MAX_HEALTH,
        hungry: 0,
        skills: vec![skill],
        inv: vec![("food".into(), 2)],
        memory: vec![],
        heard: vec![],
        feedback: vec![],
        standing_orders: vec![],
        thought: String::new(),
        seen: Seen::default(),
        dry: None,
        extra: Map::new(),
        src: None,
    };
    w.villagers.push(v);
    let vi = w.villagers.len() - 1;
    reveal(w, vi);
    events.push(format!("{} wandered in looking for a home", name));
}

pub fn herds_live(w: &mut World) {
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:herds", w.seed, w.day));
    let spring = season(w) == "spring" && (w.day - 1) % SEASON_DAYS == 0;
    for i in 0..w.herds.len() {
        let (nx, ny) = herd_step(w, w.herds[i].x, w.herds[i].y, &mut rng, 2);
        let h = &mut w.herds[i];
        h.x = nx;
        h.y = ny;
        if spring && 2 <= h.count && h.count < HERD_LIMIT {
            h.count += 1;
        }
    }
}

pub fn seed_forest(w: &mut World) {
    let mut rng = PyRandom::from_str_seed(&format!("{}:{}:seeds", w.seed, w.day));
    let taken: HSet<Pt> = w.built.iter().map(|b| (b.x, b.y)).collect();
    let mut items: Vec<(String, Pt, char)> = w.changed.iter().map(|(p, c)| (key(p.0, p.1), *p, *c)).collect();
    items.sort();
    for (_, (x, y), c) in items {
        if c != GRASS || base_char(w, x, y) != FOREST || taken.contains(&(x, y)) {
            continue;
        }
        let mut beside = false;
        'outer: for dy in [-1, 0, 1] {
            for dx in [-1, 0, 1] {
                if (dx != 0 || dy != 0) && ch(w, x + dx, y + dy) == FOREST {
                    beside = true;
                    break 'outer;
                }
            }
        }
        if beside && rng.random() < SEEDING_CHANCE {
            w.changed.insert((x, y), FOREST);
            w.stocks.insert((x, y), 1);
        }
    }
}

fn py_round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

pub fn grow(w: &mut World) {
    herds_live(w);
    if season(w) == "winter" {
        return;
    }
    if season(w) == "spring" && (w.day - 1) % SEASON_DAYS == 0 {
        seed_forest(w);
    }
    let items: Vec<(Pt, i64)> = w.stocks.iter().map(|(p, s)| (*p, *s)).collect();
    for (p, stock) in items {
        let kind = ch(w, p.0, p.1);
        if w.woodlot_set.contains(&p) {
            if w.day % WOODLOT_GROW_DAYS == 0 {
                w.stocks.insert(p, TREE_WOOD.min(stock + 1));
            }
        } else if kind == FOREST {
            if w.day % TREE_REGROW_DAYS == 0 {
                w.stocks.insert(p, TREE_WOOD.min(stock + 1));
            }
        } else if kind == BERRIES {
            if w.day % BUSH_REGROW_DAYS == 0 {
                w.stocks.insert(p, BUSH_FOOD.min(stock + 1));
            }
        } else {
            let soil = w.soil.get(&p).copied().unwrap_or(1.0);
            let cap = py_round(FIELD_FOOD as f64 * soil);
            let step = 1.max(py_round(FIELD_GROWTH as f64 * soil));
            w.stocks.insert(p, cap.min(stock + step));
            w.soil.insert(p, f64::min(1.0, soil + SOIL_REST));
        }
    }
}

pub fn era(w: &World) -> &'static str {
    if knows(w, "copper") {
        "Copper Age"
    } else if knows(w, "sowing") {
        "Farming Age"
    } else {
        "Stone Age"
    }
}

// ---------------------------------------------------------------- guide

fn all_stores_edible(w: &World) -> i64 {
    (0..store_positions(w).len()).map(|i| edible(store_inv(w, i))).sum()
}

pub fn focus_mark(w: &World) -> Mark {
    Mark {
        day: w.day,
        food: w.villagers.iter().map(|v| edible(&v.inv)).sum::<i64>() + all_stores_edible(w),
        seen: w.villagers.iter().map(|v| v.seen.len() as i64).sum(),
        built: w.built.len() as i64,
        deaths: w.dead.len() as i64,
        hungry: 0,
        tries: w.guide.attempts.iter().map(|(_, n)| *n).sum(),
    }
}

pub struct Report {
    pub day: i64,
    pub source: String,
    pub season: &'static str,
    pub villagers: Vec<Value>,
    pub ate: Vec<bool>,
    pub ok: i64,
    pub rejected: i64,
    pub gained: Vec<(String, i64)>,
    pub built: Vec<String>,
    pub events: Vec<String>,
    pub deaths: Vec<Value>,
    pub revealed: Vec<String>,
    pub insight: Option<i64>,
}

impl Report {
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("day".into(), json!(self.day));
        m.insert("source".into(), json!(self.source));
        m.insert("season".into(), json!(self.season));
        m.insert("villagers".into(), Value::Array(self.villagers.clone()));
        m.insert("ok".into(), json!(self.ok));
        m.insert("rejected".into(), json!(self.rejected));
        m.insert("gained".into(), inv_to_value(&self.gained));
        m.insert("built".into(), strings_to_value(&self.built));
        m.insert("events".into(), strings_to_value(&self.events));
        m.insert("deaths".into(), Value::Array(self.deaths.clone()));
        m.insert("revealed".into(), strings_to_value(&self.revealed));
        if let Some(i) = self.insight {
            m.insert("insight".into(), json!(i));
        }
        Value::Object(m)
    }
}

fn judge_focus(w: &mut World, report: &mut Report) -> R<()> {
    let now = focus_mark(w);
    let focus = w.guide.focus.clone().ok_or("no focus")?;
    let start = w.guide.focus_start.clone().ok_or("TypeError: focus_start is None")?;
    if focus == "learn" && !w.guide.planted.iter().any(|i| !w.guide.known.contains(i)) {
        w.guide.focus_start = Some(now);
        return Ok(());
    }
    let worked = match focus.as_str() {
        "food" => start.hungry == 0 && now.food >= w.villagers.len() as i64,
        "shelter" => now.built > start.built,
        "explore" => now.seen >= start.seen + 20,
        "learn" => now.tries > start.tries,
        other => return Err(format!("KeyError: {:?}", other)),
    };
    let lost = now.deaths > start.deaths;
    let change: i64 = if lost { -10 } else if worked { 5 } else { -3 };
    w.guide.trust = 0.max(100.min(w.guide.trust + change));
    let verdict = if lost { "someone died following it" } else if worked { "it helped" } else { "it did not help" };
    let text = rules().focuses.iter().find(|(k, _)| *k == focus).map(|(_, t)| t.clone()).unwrap();
    report.events.push(format!("Your advice to {}: {} (Trust {:+})", text, verdict, change));
    w.guide.focus_start = Some(now);
    Ok(())
}

fn settle_guide(w: &mut World, report: &mut Report, was_winter: bool) -> R<()> {
    if w.fallen.is_some_and(|d| d != 0) {
        return Ok(());
    }
    let mut gain = report.day.rem_euclid(2) + 3 * report.deaths.len() as i64;
    let kinds: Vec<&String> = w.built.iter().map(|b| &b.kind).collect();
    let mut distinct: Vec<&String> = Vec::new();
    for k in &report.built {
        if !distinct.contains(&k) {
            distinct.push(k);
        }
    }
    gain += 3 * distinct
        .iter()
        .filter(|k| kinds.iter().filter(|x| **x == **k).count() == report.built.iter().filter(|x| x == *k).count())
        .count() as i64;
    gain += 2 * report.events.iter().filter(|e| e.ends_with("looking for a home")).count() as i64;
    if was_winter && season(w) == "spring" {
        gain += 5;
        report.events.push("The village came through the winter (+5 Insight)".into());
    }
    w.guide.insight += gain;
    report.insight = Some(gain);
    if era(w) != w.guide.era {
        w.guide.era = era(w).to_string();
        w.guide.insight += 10;
        report.events.push(format!("The {} has begun (+10 Insight)", w.guide.era));
    }
    if w.guide.focus.as_deref().is_some_and(|f| !f.is_empty()) {
        let add = report.ate.iter().filter(|a| !**a).count() as i64;
        let day = w.day;
        let fs = w.guide.focus_start.as_mut().ok_or("TypeError: focus_start is None")?;
        fs.hungry += add;
        if day - fs.day >= FOCUS_DAYS {
            judge_focus(w, report)?;
        }
    }
    Ok(())
}

pub fn plant_idea(w: &mut World, idea: &str) -> Option<String> {
    let r = rules();
    let Some(spec) = r.idea(idea) else {
        return Some(format!("there is no idea called {}", pyfmt::str_repr(idea)));
    };
    if w.guide.planted.iter().any(|p| p == idea) {
        return Some(format!("the villagers already have the idea of {}", spec.name.to_lowercase()));
    }
    if spec.needs.iter().any(|n| !w.guide.known.contains(n)) {
        let names: Vec<&str> = spec.needs.iter().map(|n| r.idea(n).unwrap().name.as_str()).collect();
        return Some(format!("{} builds on {}, which they have not worked out", spec.name, names.join(", ")));
    }
    if w.guide.insight < spec.cost {
        return Some(format!("{} costs {} Insight; you have {}", spec.name, spec.cost, w.guide.insight));
    }
    w.guide.insight -= spec.cost;
    w.guide.planted.push(idea.to_string());
    None
}

pub fn buy_upgrade(w: &mut World, upgrade: &str) -> Option<String> {
    let r = rules();
    let Some((_, name, cost)) = r.upgrades.iter().find(|(k, _, _)| k == upgrade) else {
        return Some(format!("there is no upgrade called {}", pyfmt::str_repr(upgrade)));
    };
    if w.guide.upgrades.iter().any(|u| u == upgrade) {
        return Some(format!("the village already has {}", name.to_lowercase()));
    }
    if w.guide.insight < *cost {
        return Some(format!("{} costs {} Insight; you have {}", name, cost, w.guide.insight));
    }
    w.guide.insight -= cost;
    w.guide.upgrades.push(upgrade.to_string());
    for i in 0..w.villagers.len() {
        reveal(w, i);
    }
    None
}

pub fn set_focus(w: &mut World, focus: Option<&str>) -> Option<String> {
    if let Some(f) = focus {
        if !rules().focuses.iter().any(|(k, _)| k == f) {
            let keys: Vec<&str> = rules().focuses.iter().map(|(k, _)| k.as_str()).collect();
            return Some(format!("focus must be one of {}", keys.join(", ")));
        }
    }
    w.guide.focus = focus.map(|s| s.to_string());
    w.guide.focus_start = if focus.is_some_and(|f| !f.is_empty()) { Some(focus_mark(w)) } else { None };
    None
}

pub fn legacy_earned(w: &World) -> i64 {
    (w.day - 1).div_euclid(SEASON_DAYS * rules().seasons.len() as i64)
        + w.guide.known.len() as i64
        + if w.fallen.is_some_and(|d| d != 0) { 1 } else { 0 }
}

// ---------------------------------------------------------------- the day

pub fn seen_union(w: &World) -> Seen {
    let mut u = Seen::default();
    for v in &w.villagers {
        u.union(&v.seen);
    }
    u
}

fn py_list(v: &Value) -> R<Vec<Value>> {
    match v {
        Value::Array(a) => Ok(a.clone()),
        Value::String(s) => Ok(s.chars().map(|c| Value::String(c.to_string())).collect()),
        Value::Object(m) => Ok(m.keys().map(|k| Value::String(k.clone())).collect()),
        _ => Err("TypeError: object is not iterable".into()),
    }
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_none_or(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

pub fn run_day(w: &mut World, plans_in: &Value, source_in: &str, unwatched: bool) -> R<Value> {
    let mut plans = plans_in.clone();
    let mut source = source_in.to_string();
    if !truthy(&plans) && truthy(&w.pending_plans) {
        plans = std::mem::replace(&mut w.pending_plans, Value::Null);
        source = "model".into();
    }
    let seen_before = seen_union(w);
    let mut report = Report {
        day: w.day,
        source: source.clone(),
        season: season(w),
        villagers: vec![],
        ate: vec![],
        ok: 0,
        rejected: 0,
        gained: vec![],
        built: vec![],
        events: vec![],
        deaths: vec![],
        revealed: vec![],
        insight: None,
    };
    let mut fatal: Vec<(usize, &'static str)> = Vec::new();
    // (entry index, step index, built index): the report shares the building dict with the world
    let mut built_links: Vec<(usize, usize, usize)> = Vec::new();
    let count = w.villagers.len();
    let lines = memory_lines(w);
    for vi in 0..count {
        let name = w.villagers[vi].name.clone();
        let plan = plans.get(&name).filter(|p| !p.is_null()).cloned();
        w.villagers[vi].feedback = vec![];
        let (actions, mode): (Vec<Value>, String);
        match &plan {
            None => {
                let mut a = w.villagers[vi].standing_orders.clone();
                a.extend(instinct_actions(w, vi));
                a.truncate(MAX_ACTIONS);
                actions = a;
                mode = "habit".into();
            }
            Some(plan) => {
                let p = plan.as_object().ok_or("AttributeError: plan is not a dict")?;
                let raw = p.get("actions").cloned().unwrap_or(Value::Null);
                let mut a = if truthy(&raw) { py_list(&raw)? } else { vec![] };
                a.truncate(MAX_ACTIONS);
                actions = a;
                mode = source.clone();
                let thought = p.get("thought").map(pystr).unwrap_or_default();
                w.villagers[vi].thought = head(&thought, 160);
                let note_raw = p.get("remember").map(pystr).unwrap_or_default();
                let note = head(pyfmt::strip(&note_raw), 80);
                if !note.is_empty() {
                    let line = format!("day {}: {}", w.day, note);
                    let v = &mut w.villagers[vi];
                    v.memory.push(line);
                    v.memory = last_n(&v.memory, lines);
                }
                if let Some(Value::Array(orders)) = p.get("standing_orders") {
                    w.villagers[vi].standing_orders = orders
                        .iter()
                        .filter(|a| a.is_object() && aget(a, "verb").as_str().is_some_and(|s| rules().is_verb(s)))
                        .take(3)
                        .cloned()
                        .collect();
                }
            }
        }
        let mut entry = Map::new();
        entry.insert("name".into(), json!(name));
        entry.insert("mode".into(), json!(mode));
        entry.insert("start".into(), pose(&w.villagers[vi]));
        let mut steps: Vec<Value> = Vec::new();
        entry.insert(
            "thought".into(),
            json!(if mode != "habit" { w.villagers[vi].thought.clone() } else { String::new() }),
        );
        let entry_idx = report.villagers.len();
        let mut slots = SLOTS_PER_DAY;
        for act in &actions {
            if slots <= 0 {
                break;
            }
            if mode == "habit" && act.is_object() {
                let verb = aget(act, "verb").as_str();
                if verb == Some("build") && !can_build(w, vi, act)? {
                    continue;
                }
                if verb == Some("gather") && aget(act, "item").as_str() == Some("food") && ready_food(w, vi).is_empty() {
                    continue;
                }
                if nothing_to_do(w, vi, act)? {
                    continue;
                }
            }
            let mut fx = Effects::new();
            let (used, err, summary) = execute(w, vi, act, slots, &mut fx)?;
            let mut step = Map::new();
            step.insert("action".into(), if act.is_object() { act.clone() } else { json!({}) });
            step.insert("ok".into(), json!(err.is_none()));
            step.insert("result".into(), json!(err.clone().filter(|e| !e.is_empty()).unwrap_or(summary)));
            step.insert("at".into(), json!(SLOTS_PER_DAY - slots));
            step.insert("slots".into(), json!(used));
            step.insert("after".into(), pose(&w.villagers[vi]));
            for (k, v) in &fx {
                step.insert(k.clone(), v.clone());
            }
            slots -= used;
            if let Some(e) = err {
                w.villagers[vi].feedback.push(e);
                report.rejected += 1;
            } else {
                report.ok += 1;
                if let Some(Value::Object(g)) = fx.get("gain") {
                    for (k, n) in g {
                        let n = n.as_i64().unwrap_or(0);
                        let cur = inv_get(&report.gained, k);
                        inv_set(&mut report.gained, k, cur + n);
                    }
                }
                if let Some(b) = fx.get("built") {
                    report.built.push(b["kind"].as_str().unwrap_or("").to_string());
                    built_links.push((entry_idx, steps.len(), w.built.len() - 1));
                }
            }
            steps.push(Value::Object(step));
        }
        entry.insert("steps".into(), Value::Array(steps));
        let cause = night(w, vi, &mut entry);
        let mut cause = cause;
        if cause.is_some() && unwatched && fatal.len() + 1 >= w.villagers.len() {
            w.villagers[vi].health = 1;
            if let Some(Value::Object(n)) = entry.get_mut("night") {
                n.insert("health".into(), json!(1));
            }
            cause = None;
        }
        if let Some(c) = cause {
            fatal.push((vi, c));
        }
        let v = &mut w.villagers[vi];
        v.heard = last_n(&v.heard, HEARD_LINES);
        report.ate.push(entry.get("night").and_then(|n| n.get("ate")).and_then(|a| a.as_bool()).unwrap_or(false));
        report.villagers.push(Value::Object(entry));
    }
    // remove the dead, highest index first so positions stay valid
    let mut removed: Vec<(usize, Villager, &'static str)> = Vec::new();
    for (vi, cause) in &fatal {
        removed.push((*vi, w.villagers[*vi].clone(), cause));
    }
    for (vi, _) in fatal.iter().rev() {
        w.villagers.remove(*vi);
    }
    for (vi, v, cause) in removed {
        let mut record = match v.to_value(false) {
            Value::Object(m) => m,
            _ => Map::new(),
        };
        record.insert("cause".into(), json!(cause));
        record.insert("day".into(), json!(w.day));
        w.dead.push(Value::Object(record));
        report.deaths.push(json!({"name": v.name, "cause": cause}));
        report.events.push(format!("{} died of {}", v.name, cause));
        if let Some(src) = v.src {
            w.gone.push((src, v.to_value(true)));
        }
        let _ = vi;
    }
    burn_fuel(w, &mut report.events);
    // the report shares each new building's dict with the world: it now carries the fire's `lit`
    for (ei, si, bi) in &built_links {
        if let Some(b) = w.built.get(*bi) {
            if let Some(Value::Object(e)) = report.villagers.get_mut(*ei) {
                if let Some(Value::Array(steps)) = e.get_mut("steps") {
                    if let Some(Value::Object(s)) = steps.get_mut(*si) {
                        s.insert("built".into(), b.to_value());
                    }
                }
            }
        }
    }
    if !w.built.iter().any(|b| b.kind == "storehouse" || b.kind == "drying_rack") {
        for i in 0..store_positions(w).len() {
            rot(store_inv_mut(w, i));
        }
    }
    let mut events = w.events.take().unwrap_or_default();
    events.extend(std::mem::take(&mut report.events));
    report.events = events;
    grow(w);
    if !w.villagers.is_empty() {
        arrival(w, &mut report.events);
    } else {
        w.fallen = Some(w.day);
        report.events.push("The village has fallen".into());
    }
    let after = seen_union(w);
    let mut revealed: Vec<String> = after.difference(&seen_before).map(|p| key(p.0, p.1)).collect();
    revealed.sort();
    report.revealed = revealed;
    w.land_rev += 1;
    let was_winter = season(w) == "winter";
    w.day += 1;
    if !w.fallen.is_some_and(|d| d != 0) && (w.day - 1) % SEASON_DAYS == 0 {
        let s = season(w);
        let mut cap = s.to_string();
        cap[..1].make_ascii_uppercase();
        report.events.push(format!("{} is here", cap));
    }
    settle_guide(w, &mut report, was_winter)?;
    let value = report.to_value();
    w.log.push(value.clone());
    if w.log.len() > 12 {
        let cut = w.log.len() - 12;
        w.log.drain(..cut);
    }
    Ok(value)
}

// ---------------------------------------------------------------- clock

fn unpause(w: &mut World, now: Num) {
    if let Some(p) = w.paused_at {
        w.day_started_at = w.day_started_at.add(now.sub(p));
        w.paused_at = None;
    }
}

fn set_rate(w: &mut World, speed: Num, now: Num) {
    let played = now.sub(w.day_started_at).mul(w.speed);
    w.day_started_at = Num::F(now.f() - played.f() / speed.f());
    w.speed = speed;
}

pub fn set_speed(w: &mut World, speed: &Value, now: Num) -> Option<String> {
    let r = rules();
    let sp = match speed {
        Value::Number(_) | Value::Bool(_) => Num::from_value(speed).ok(),
        _ => None,
    };
    let zero = sp.is_some_and(|s| s.f() == 0.0);
    let member = sp.is_some_and(|s| r.value["SPEEDS"].as_array().unwrap().iter().any(|m| m.as_f64() == Some(s.f())));
    if !zero && !member {
        let list: Vec<String> = r.value["SPEEDS"].as_array().unwrap().iter().map(|m| m.to_string()).collect();
        return Some(format!("speed must be 0 (pause) or one of {}", list.join(", ")));
    }
    w.last_read = now;
    if zero {
        if w.paused_at.is_none() {
            w.paused_at = Some(now);
        }
        return None;
    }
    unpause(w, now);
    set_rate(w, sp.unwrap(), now);
    None
}

pub fn restart_day(w: &mut World, now: Num) {
    w.day_started_at = now;
    if w.paused_at.is_some() {
        w.paused_at = Some(now);
    }
}

fn at_normal_speed(w: &World) -> bool {
    w.speed.f() == 1.0 && w.paused_at.is_none()
}

fn drop_idle_speed(w: &mut World, now: Num) -> bool {
    if at_normal_speed(w) {
        return false;
    }
    let seen = w.last_read;
    w.last_read = now;
    if now.f() - seen.f() > SPEED_IDLE_SECONDS as f64 {
        unpause(w, seen);
        set_rate(w, Num::I(1), seen);
    }
    true
}

pub fn advance(w: &mut World, now: Num) -> R<Value> {
    let mut changed = drop_idle_speed(w, now);
    if w.log.is_empty() {
        run_day(w, &Value::Null, "habit", false)?;
        w.day_started_at = now;
        changed = true;
    }
    if w.paused_at.is_some() {
        w.extra.insert("_dirty".into(), Value::Bool(changed));
        return Ok(Value::Null);
    }
    let mut days = 0i64;
    let mut gained: Vec<(String, i64)> = Vec::new();
    let mut built: Vec<Value> = Vec::new();
    let mut deaths: Vec<Value> = Vec::new();
    let step = DAY_SECONDS as f64 / w.speed.f();
    let fallen = |w: &World| w.fallen.is_some_and(|d| d != 0);
    while now.f() - w.day_started_at.f() >= step && days < MAX_CATCHUP_DAYS && !fallen(w) {
        let catching_up = w.speed.f() == 1.0 && now.f() - w.day_started_at.f() >= 2.0 * step;
        let report = run_day(w, &Value::Null, "habit", catching_up)?;
        w.day_started_at = w.day_started_at.add(Num::F(step));
        days += 1;
        changed = true;
        if let Some(Value::Object(g)) = report.get("gained") {
            for (k, n) in g {
                let cur = inv_get(&gained, k);
                inv_set(&mut gained, k, cur + n.as_i64().unwrap_or(0));
            }
        }
        if let Some(Value::Array(b)) = report.get("built") {
            built.extend(b.iter().cloned());
        }
        if let Some(Value::Array(d)) = report.get("deaths") {
            deaths.extend(d.iter().cloned());
        }
    }
    if now.f() - w.day_started_at.f() >= step && !fallen(w) {
        w.day_started_at = now;
        changed = true;
    }
    w.extra.insert("_dirty".into(), Value::Bool(changed));
    if days < 2 || w.speed.f() > 1.0 {
        return Ok(Value::Null);
    }
    let mut away = match &w.away {
        Value::Object(m) if !m.is_empty() => m.clone(),
        _ => {
            let mut m = Map::new();
            m.insert("days".into(), json!(0));
            m.insert("gained".into(), json!({}));
            m.insert("built".into(), json!([]));
            m.insert("deaths".into(), json!([]));
            m
        }
    };
    let mut ag: Inv = match away.get("gained") {
        Some(g) => inv_from(g, "away.gained")?,
        None => vec![],
    };
    for (k, n) in &gained {
        let cur = inv_get(&ag, k);
        inv_set(&mut ag, k, cur + n);
    }
    away.insert("gained".into(), inv_to_value(&ag));
    let d0 = away.get("days").and_then(|d| d.as_i64()).unwrap_or(0);
    away.insert("days".into(), json!(d0 + days));
    for (k, extra) in [("built", built), ("deaths", deaths)] {
        let mut cur = match away.get(k) {
            Some(Value::Array(a)) => a.clone(),
            _ => vec![],
        };
        cur.extend(extra);
        away.insert(k.into(), Value::Array(cur));
    }
    w.away = Value::Object(away);
    Ok(w.away.clone())
}

// ---------------------------------------------------------------- views

pub fn needs_council(w: &World, wild_wood: Option<i64>) -> R<Vec<String>> {
    let mut reasons = Vec::new();
    if w.fallen.is_some_and(|d| d != 0) || truthy(&w.pending_plans) {
        return Ok(reasons);
    }
    if w.last_planned_day == 0 {
        reasons.push("the village has never held a council".into());
    }
    if !w.guidance.is_empty() && w.guidance_day > w.last_planned_day {
        reasons.push("you gave new guidance".into());
    }
    let waiting: Vec<String> =
        w.guide.planted.iter().filter(|i| !w.guide.known.contains(i)).map(|i| rules().idea(i).unwrap().name.to_lowercase()).collect();
    if !waiting.is_empty() {
        reasons.push(format!("{} is waiting to be tried", waiting.join(", ")));
    }
    let starving: Vec<&str> = w.villagers.iter().filter(|v| v.hungry >= 2 || v.health <= 2).map(|v| v.name.as_str()).collect();
    if !starving.is_empty() {
        reasons.push(format!("{} may not survive much longer", starving.join(", ")));
    }
    let day_of_season = (w.day - 1) % SEASON_DAYS;
    let food: i64 = w.villagers.iter().map(|v| inv_get(&v.inv, "food")).sum();
    if season(w) == "autumn" && day_of_season >= 2 && food < 4 * w.villagers.len() as i64 {
        reasons.push("winter is close and there is not enough food".into());
    }
    let wood = match wild_wood {
        Some(x) => x,
        None => resources(w).wild_wood,
    };
    if wood < 10 {
        reasons.push("they know of very little wood left nearby".into());
    }
    if w.fire_out {
        reasons.push("the fire is out".into());
    }
    let tired: Vec<&str> = w.villagers.iter().filter(|v| v.feedback.len() >= 3).map(|v| v.name.as_str()).collect();
    if !tired.is_empty() {
        reasons.push(format!("{} keep failing", tired.join(", ")));
    }
    Ok(reasons)
}

pub struct Resources {
    pub value: Value,
    pub wild_wood: i64,
}

pub fn resources(w: &World) -> Resources {
    let stores: Vec<&Inv> = (0..store_positions(w).len()).map(|i| store_inv(w, i)).collect();
    let mut packs: Vec<&Inv> = w.villagers.iter().map(|v| &v.inv).collect();
    packs.extend(stores.iter().copied());
    let held = json!({
        "food": packs.iter().map(|p| edible(p)).sum::<i64>(),
        "wood": packs.iter().map(|p| inv_get(p, "wood")).sum::<i64>(),
        "stone": packs.iter().map(|p| inv_get(p, "stone")).sum::<i64>(),
    });
    let seen = seen_union(w);
    let (mut wf, mut ww) = (0i64, 0i64);
    for (p, stock) in &w.stocks {
        if seen.has(p) {
            if ch(w, p.0, p.1) == FOREST || w.woodlot_set.contains(p) {
                ww += stock;
            } else {
                wf += stock;
            }
        }
    }
    let ws = seen.iter().filter(|p| ch(w, p.0, p.1) == ROCK).count() as i64;
    let herds: Vec<Value> = w.herds.iter().filter(|h| seen.contains(h.x, h.y)).map(|h| h.to_value()).collect();
    let mut stored: Inv = Vec::new();
    for inv in &stores {
        for (item, n) in inv.iter() {
            let cur = inv_get(&stored, item);
            inv_set(&mut stored, item, cur + n);
        }
    }
    Resources {
        value: json!({"held": held, "stored": inv_to_value(&stored), "wild": {"food": wf, "wood": ww, "stone": ws},
                      "herds": herds, "fire_out": w.fire_out}),
        wild_wood: ww,
    }
}

pub fn land_rev(w: &World) -> String {
    format!("{}:{}:{}", w.seed, w.born.py(), w.land_rev)
}

pub fn land_view(w: &World) -> Value {
    let seen = seen_union(w);
    let mut masks: HMap<Pt, [u8; 256]> = HMap::default();
    for (x, y) in seen.iter() {
        let m = masks.entry((x >> 4, y >> 4)).or_insert([b'0'; 256]);
        m[((y & 15) * CHUNK + (x & 15)) as usize] = b'1';
    }
    let mut near: HSet<Pt> = HSet::default();
    for (cx, cy) in masks.keys() {
        for dy in [-1, 0, 1] {
            for dx in [-1, 0, 1] {
                near.insert((cx + dx, cy + dy));
            }
        }
    }
    let mut land: HMap<Pt, [u8; 256]> = HMap::default();
    for at in &near {
        let chunk = terrain::land(w.seed, at.0, at.1);
        let mut flat = [0u8; 256];
        for (i, row) in chunk.iter().enumerate() {
            flat[i * 16..i * 16 + 16].copy_from_slice(row);
        }
        land.insert(*at, flat);
    }
    for ((x, y), c) in &w.shaped {
        if let Some(cell) = land.get_mut(&(x >> 4, y >> 4)) {
            cell[((y & 15) * CHUNK + (x & 15)) as usize] = *c as u8;
        }
    }
    let sorted = |m: &HMap<Pt, [u8; 256]>| -> Map<String, Value> {
        let mut keys: Vec<&Pt> = m.keys().collect();
        keys.sort();
        keys.into_iter().map(|k| (key(k.0, k.1), Value::String(String::from_utf8_lossy(&m[k]).to_string()))).collect()
    };
    let mut stocks: Vec<(&Pt, &i64)> = w.stocks.iter().filter(|(p, _)| seen.has(p)).collect();
    stocks.sort();
    json!({
        "rev": land_rev(w),
        "land": sorted(&land),
        "seen": sorted(&masks),
        "stocks": stocks.into_iter().map(|(p, n)| (key(p.0, p.1), json!(n))).collect::<Map<String, Value>>(),
    })
}

fn light_report(report: &Value) -> Value {
    let mut r = report.clone();
    if let Some(m) = r.as_object_mut() {
        let villagers: Vec<Value> = report["villagers"]
            .as_array()
            .map(|a| {
                a.iter()
                    .map(|e| {
                        let steps: Vec<Value> = e["steps"]
                            .as_array()
                            .map(|s| s.iter().map(|s| json!({"action": s["action"], "ok": s["ok"], "result": s["result"]})).collect())
                            .unwrap_or_default();
                        json!({"name": e["name"], "mode": e["mode"], "thought": e["thought"], "steps": steps})
                    })
                    .collect()
            })
            .unwrap_or_default();
        m.insert("villagers".into(), Value::Array(villagers));
    }
    r
}

pub fn settlement(n_built: usize) -> String {
    let levels = &rules().levels;
    let mut name = levels[0].1.clone();
    for (need, label) in levels {
        if n_built as i64 >= *need {
            name = label.clone();
        }
    }
    name
}

pub fn public_state(w: &World, now: Num, have: &str) -> R<Value> {
    let r = rules();
    let current = w.log.last();
    let rev = land_rev(w);
    let held = resources(w);
    let fields = ["name", "trait", "x", "y", "energy", "health", "hungry", "skills", "inv", "memory", "heard", "feedback", "standing_orders", "thought"];
    let mut villagers: Vec<Value> = Vec::new();
    for v in &w.villagers {
        let full = v.to_value(false);
        let mut m = Map::new();
        for k in fields {
            m.insert(k.into(), full[k].clone());
        }
        m.insert("seen_count".into(), json!(v.seen.len()));
        villagers.push(Value::Object(m));
    }
    if let Some(cur) = current {
        for d in &w.dead {
            if d.get("day") == cur.get("day") {
                let mut m = Map::new();
                for k in fields {
                    m.insert(k.into(), d.get(k).cloned().ok_or_else(|| format!("KeyError: {:?}", k))?);
                }
                m.insert("dying".into(), d.get("cause").cloned().unwrap_or(Value::Null));
                m.insert("seen_count".into(), json!(0));
                villagers.push(Value::Object(m));
            }
        }
    }
    let mut out = Map::new();
    out.insert("schema".into(), json!(w.schema));
    out.insert("day".into(), current.map(|c| c["day"].clone()).unwrap_or(json!(w.day)));
    out.insert("land_id".into(), json!(format!("{}:{}", w.seed, w.born.py())));
    out.insert("land_rev".into(), json!(rev));
    out.insert("camp".into(), pt_to_value(w.camp));
    out.insert("built".into(), Value::Array(w.built.iter().map(|b| b.to_value()).collect()));
    out.insert("guidance".into(), json!(w.guidance));
    out.insert("resources".into(), held.value.clone());
    out.insert("store_at".into(), pt_to_value(w.store_at));
    if have != rev {
        out.insert("land_view".into(), land_view(w));
    }
    out.insert("vision".into(), json!(vision(w)));
    out.insert("dawn_fraction".into(), json!(DAWN_FRACTION));
    out.insert("chunk".into(), json!(CHUNK));
    out.insert("depots".into(), Value::Array(w.depots.iter().map(|d| json!([d.x, d.y])).collect()));
    out.insert("council_ready".into(), json!(truthy(&w.pending_plans)));
    let mut stock_full = Map::new();
    for (c, n) in &r.full_stock {
        stock_full.insert(c.to_string(), json!(n));
    }
    out.insert("stock_full".into(), Value::Object(stock_full));
    out.insert("settlement".into(), json!(settlement(w.built.len())));
    out.insert("buildings".into(), r.value["BUILDINGS"].clone());
    out.insert("now".into(), now.to_value());
    out.insert("day_started_at".into(), w.day_started_at.to_value());
    out.insert("day_seconds".into(), json!(DAY_SECONDS));
    out.insert("speed".into(), w.speed.to_value());
    out.insert("paused_at".into(), w.paused_at.map(|p| p.to_value()).unwrap_or(Value::Null));
    out.insert("speeds".into(), r.value["SPEEDS"].clone());
    out.insert("work_fraction".into(), json!(WORK_FRACTION));
    out.insert("slots_per_day".into(), json!(SLOTS_PER_DAY));
    out.insert("current".into(), current.cloned().unwrap_or(Value::Null));
    out.insert("away".into(), w.away.clone());
    out.insert("villagers".into(), Value::Array(villagers));
    out.insert("season".into(), current.map(|c| c["season"].clone()).unwrap_or(json!(season(w))));
    out.insert("season_days".into(), json!(SEASON_DAYS));
    out.insert("fallen".into(), w.fallen.map(Value::from).unwrap_or(Value::Null));
    out.insert("max_health".into(), json!(max_health(w)));
    let g = &w.guide;
    out.insert(
        "guide".into(),
        json!({
            "insight": g.insight, "trust": g.trust, "focus": g.focus, "planted": g.planted, "known": g.known,
            "upgrades": g.upgrades, "era": g.era, "attempts": inv_to_value(&g.attempts),
            "ideas": r.value["IDEAS"], "upgrades_for_sale": r.value["UPGRADES"], "focuses": r.value["FOCUSES"],
            "future_eras": r.value["FUTURE_ERAS"], "trust_heeded": TRUST_HEEDED, "focus_days": FOCUS_DAYS,
        }),
    );
    out.insert(
        "dead".into(),
        Value::Array(
            w.dead
                .iter()
                .map(|d| {
                    let mut m = Map::new();
                    for k in ["name", "day", "cause", "x", "y"] {
                        m.insert(k.into(), d.get(k).cloned().unwrap_or(Value::Null));
                    }
                    Value::Object(m)
                })
                .collect(),
        ),
    );
    let start = w.log.len().saturating_sub(10);
    out.insert("log".into(), Value::Array(w.log[start..].iter().map(light_report).collect()));
    out.insert("council_reasons".into(), strings_to_value(&needs_council(w, Some(held.wild_wood))?));
    Ok(Value::Object(out))
}
