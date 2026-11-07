//! Typed view of the JSON world. Reading and writing keep the save format identical:
//! "x,y" string keys, schema 10, unknown keys carried through untouched.

use serde_json::{Map, Number, Value};
use std::collections::{HashMap, HashSet};
use std::hash::{BuildHasherDefault, Hasher};

pub type R<T> = Result<T, String>;
pub type Pt = (i64, i64);
pub type Inv = Vec<(String, i64)>;

/// Small fast deterministic hasher for coordinate keys.
#[derive(Default, Clone, Copy)]
pub struct Fx(u64);

impl Hasher for Fx {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for b in bytes {
            self.write_u64(*b as u64);
        }
    }
    fn write_u64(&mut self, i: u64) {
        self.0 = (self.0.rotate_left(5) ^ i).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
    fn write_i64(&mut self, i: i64) {
        self.write_u64(i as u64);
    }
}

pub type HMap<K, V> = HashMap<K, V, BuildHasherDefault<Fx>>;
pub type HSet<K> = HashSet<K, BuildHasherDefault<Fx>>;

pub fn key(x: i64, y: i64) -> String {
    format!("{},{}", x, y)
}

pub fn parse_key(s: &str) -> Option<Pt> {
    let (a, b) = s.split_once(',')?;
    Some((a.parse().ok()?, b.parse().ok()?))
}

// ------------------------------------------------------------------ inventories

pub fn inv_get(inv: &Inv, k: &str) -> i64 {
    inv.iter().find(|(n, _)| n == k).map(|(_, v)| *v).unwrap_or(0)
}

pub fn inv_set(inv: &mut Inv, k: &str, n: i64) {
    if let Some(e) = inv.iter_mut().find(|(name, _)| name == k) {
        e.1 = n;
    } else {
        inv.push((k.to_string(), n));
    }
}

pub fn inv_add(inv: &mut Inv, k: &str, n: i64) {
    let now = inv_get(inv, k);
    inv_set(inv, k, now + n);
}

pub fn inv_to_value(inv: &Inv) -> Value {
    Value::Object(inv.iter().map(|(k, n)| (k.clone(), Value::from(*n))).collect())
}

// ------------------------------------------------------------------ numbers (int vs float matters)

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Num {
    I(i64),
    F(f64),
}

impl Num {
    pub fn f(self) -> f64 {
        match self {
            Num::I(i) => i as f64,
            Num::F(f) => f,
        }
    }
    pub fn add(self, o: Num) -> Num {
        match (self, o) {
            (Num::I(a), Num::I(b)) => Num::I(a + b),
            _ => Num::F(self.f() + o.f()),
        }
    }
    pub fn sub(self, o: Num) -> Num {
        match (self, o) {
            (Num::I(a), Num::I(b)) => Num::I(a - b),
            _ => Num::F(self.f() - o.f()),
        }
    }
    pub fn mul(self, o: Num) -> Num {
        match (self, o) {
            (Num::I(a), Num::I(b)) => Num::I(a * b),
            _ => Num::F(self.f() * o.f()),
        }
    }
    pub fn from_value(v: &Value) -> R<Num> {
        match v {
            Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Ok(Num::I(i))
                } else {
                    Ok(Num::F(n.as_f64().ok_or("bad number")?))
                }
            }
            Value::Bool(b) => Ok(Num::I(*b as i64)),
            other => Err(format!("expected a number, got {}", other)),
        }
    }
    pub fn to_value(self) -> Value {
        match self {
            Num::I(i) => Value::from(i),
            Num::F(f) => Number::from_f64(f).map(Value::Number).unwrap_or(Value::Null),
        }
    }
    /// How Python prints it inside an f-string.
    pub fn py(self) -> String {
        match self {
            Num::I(i) => i.to_string(),
            Num::F(f) => crate::pyfmt::float_repr(f),
        }
    }
}

// ------------------------------------------------------------------ JSON helpers

pub fn int(v: &Value, what: &str) -> R<i64> {
    match v {
        Value::Number(n) => n.as_i64().ok_or_else(|| format!("{} must be an integer", what)),
        Value::Bool(b) => Ok(*b as i64),
        _ => Err(format!("{} must be an integer", what)),
    }
}

pub fn string(v: &Value, what: &str) -> R<String> {
    v.as_str().map(|s| s.to_string()).ok_or_else(|| format!("{} must be a string", what))
}

pub fn strings(v: &Value, what: &str) -> R<Vec<String>> {
    v.as_array()
        .ok_or_else(|| format!("{} must be a list", what))?
        .iter()
        .map(|s| string(s, what))
        .collect()
}

pub fn strings_to_value(v: &[String]) -> Value {
    Value::Array(v.iter().map(|s| Value::String(s.clone())).collect())
}

pub fn pt(v: &Value, what: &str) -> R<Pt> {
    let a = v.as_array().ok_or_else(|| format!("{} must be [x, y]", what))?;
    if a.len() != 2 {
        return Err(format!("{} must be [x, y]", what));
    }
    Ok((int(&a[0], what)?, int(&a[1], what)?))
}

pub fn pt_to_value(p: Pt) -> Value {
    Value::Array(vec![Value::from(p.0), Value::from(p.1)])
}

pub fn inv_from(v: &Value, what: &str) -> R<Inv> {
    v.as_object()
        .ok_or_else(|| format!("{} must be an object", what))?
        .iter()
        .map(|(k, n)| Ok((k.clone(), int(n, what)?)))
        .collect()
}

fn obj<'a>(v: &'a Value, what: &str) -> R<&'a Map<String, Value>> {
    v.as_object().ok_or_else(|| format!("{} must be an object", what))
}

fn coord_chars(v: &Value, what: &str) -> R<HMap<Pt, char>> {
    let mut out = HMap::default();
    for (k, c) in obj(v, what)? {
        let p = parse_key(k).ok_or_else(|| format!("bad tile key {:?}", k))?;
        let s = c.as_str().ok_or_else(|| format!("{} holds a non-string tile", what))?;
        if let Some(ch) = s.chars().next() {
            out.insert(p, ch);
        }
    }
    Ok(out)
}

fn chars_to_value(m: &HMap<Pt, char>) -> Value {
    Value::Object(m.iter().map(|(p, c)| (key(p.0, p.1), Value::String(c.to_string()))).collect())
}

// ------------------------------------------------------------------ seen

/// What a villager has seen, as one bitmap per 16x16 chunk. A save holds `"cx,cy": <64 hex digits>`,
/// so it grows with chunks walked rather than tiles, and crossing the bridge stays cheap. Bit n of
/// a chunk is the tile at (n / 16, n % 16) as (row, column). Older `"x,y": 1` dicts and plain lists
/// of tiles are still read.
#[derive(Clone, Default, Debug)]
pub struct Seen {
    chunks: HMap<Pt, [u64; 4]>,
    count: usize,
}

impl Seen {
    fn at(x: i64, y: i64) -> (Pt, usize, u64) {
        let n = ((y & 15) * 16 + (x & 15)) as usize;
        ((x >> 4, y >> 4), n / 64, 1u64 << (n % 64))
    }
    pub fn contains(&self, x: i64, y: i64) -> bool {
        let (chunk, limb, bit) = Seen::at(x, y);
        self.chunks.get(&chunk).is_some_and(|m| m[limb] & bit != 0)
    }
    pub fn has(&self, p: &Pt) -> bool {
        self.contains(p.0, p.1)
    }
    pub fn insert(&mut self, x: i64, y: i64) {
        let (chunk, limb, bit) = Seen::at(x, y);
        let map = self.chunks.entry(chunk).or_insert([0; 4]);
        if map[limb] & bit == 0 {
            map[limb] |= bit;
            self.count += 1;
        }
    }
    pub fn len(&self) -> usize {
        self.count
    }
    pub fn union(&mut self, other: &Seen) {
        for (chunk, bits) in &other.chunks {
            let map = self.chunks.entry(*chunk).or_insert([0; 4]);
            for i in 0..4 {
                self.count += (bits[i] & !map[i]).count_ones() as usize;
                map[i] |= bits[i];
            }
        }
    }
    /// Every tile, in no particular order.
    pub fn iter(&self) -> impl Iterator<Item = Pt> + '_ {
        self.chunks.iter().flat_map(|(chunk, bits)| Seen::tiles(*chunk, *bits))
    }
    /// Tiles here that are not in `other`.
    pub fn difference<'a>(&'a self, other: &'a Seen) -> impl Iterator<Item = Pt> + 'a {
        self.chunks.iter().flat_map(move |(chunk, bits)| {
            let old = other.chunks.get(chunk).copied().unwrap_or([0; 4]);
            let mut new = *bits;
            for i in 0..4 {
                new[i] &= !old[i];
            }
            Seen::tiles(*chunk, new)
        })
    }
    fn tiles(chunk: Pt, bits: [u64; 4]) -> impl Iterator<Item = Pt> {
        (0..256usize).filter(move |n| bits[n / 64] & (1u64 << (n % 64)) != 0).map(move |n| {
            (chunk.0 * 16 + (n % 16) as i64, chunk.1 * 16 + (n / 16) as i64)
        })
    }
    fn from_value(v: &Value) -> R<Seen> {
        let mut out = Seen::default();
        match v {
            Value::Object(m) => {
                for (k, val) in m {
                    let Some(p) = parse_key(k) else { continue };
                    match val.as_str() {
                        Some(hex) => out.add_chunk(p, hex)?,
                        None => out.insert(p.0, p.1),
                    }
                }
            }
            Value::Array(a) => {
                for p in a.iter().filter_map(|k| k.as_str().and_then(parse_key)) {
                    out.insert(p.0, p.1);
                }
            }
            _ => return Err("seen must be a dict or list".into()),
        }
        Ok(out)
    }
    fn add_chunk(&mut self, chunk: Pt, hex: &str) -> R<()> {
        if hex.len() != 64 || !hex.is_ascii() {
            return Err(format!("bad seen map for chunk {},{}", chunk.0, chunk.1));
        }
        let mut bits = [0u64; 4];
        for (i, limb) in bits.iter_mut().enumerate() {
            *limb = u64::from_str_radix(&hex[i * 16..(i + 1) * 16], 16).map_err(|e| e.to_string())?;
        }
        self.count += bits.iter().map(|b| b.count_ones() as usize).sum::<usize>();
        self.chunks.insert(chunk, bits);
        Ok(())
    }
    pub fn to_value(&self) -> Value {
        let mut keys: Vec<&Pt> = self.chunks.keys().collect();
        keys.sort(); // the same knowledge always saves as the same bytes
        let mut m = Map::new();
        for chunk in keys {
            let b = self.chunks[chunk];
            m.insert(key(chunk.0, chunk.1), Value::String(format!("{:016x}{:016x}{:016x}{:016x}", b[0], b[1], b[2], b[3])));
        }
        Value::Object(m)
    }
}

// ------------------------------------------------------------------ entities

#[derive(Clone, Debug)]
pub struct Villager {
    pub name: String,
    pub trait_: String,
    pub x: i64,
    pub y: i64,
    pub energy: i64,
    pub health: i64,
    pub hungry: i64,
    pub skills: Vec<String>,
    pub inv: Inv,
    pub memory: Vec<String>,
    pub heard: Vec<String>,
    pub feedback: Vec<String>,
    pub standing_orders: Vec<Value>,
    pub thought: String,
    pub seen: Seen,
    pub dry: Option<i64>,
    pub extra: Map<String, Value>,
    /// position in the incoming request, so the caller's dict can be updated in place
    pub src: Option<usize>,
}

impl Villager {
    pub fn from_value(v: &Value) -> R<Villager> {
        let m = obj(v, "villager")?;
        let mut out = Villager {
            name: String::new(),
            trait_: String::new(),
            x: 0,
            y: 0,
            energy: 0,
            health: 0,
            hungry: 0,
            skills: vec![],
            inv: vec![],
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
        let mut have = 0u32;
        for (k, val) in m {
            let bit = match k.as_str() {
                "name" => { out.name = string(val, "name")?; 1 }
                "trait" => { out.trait_ = string(val, "trait")?; 2 }
                "x" => { out.x = int(val, "x")?; 4 }
                "y" => { out.y = int(val, "y")?; 8 }
                "energy" => { out.energy = int(val, "energy")?; 16 }
                "health" => { out.health = int(val, "health")?; 32 }
                "hungry" => { out.hungry = int(val, "hungry")?; 64 }
                "skills" => { out.skills = strings(val, "skills")?; 128 }
                "inv" => { out.inv = inv_from(val, "inv")?; 256 }
                "memory" => { out.memory = strings(val, "memory")?; 512 }
                "heard" => { out.heard = strings(val, "heard")?; 1024 }
                "feedback" => { out.feedback = strings(val, "feedback")?; 2048 }
                "standing_orders" => {
                    out.standing_orders = val.as_array().ok_or("standing_orders must be a list")?.clone();
                    4096
                }
                "thought" => { out.thought = string(val, "thought")?; 8192 }
                "seen" => { out.seen = Seen::from_value(val)?; 16384 }
                "dry" => { out.dry = Some(int(val, "dry")?); 0 }
                _ => { out.extra.insert(k.clone(), val.clone()); 0 }
            };
            have |= bit;
        }
        if have != 32767 {
            return Err("villager is missing a required key".into());
        }
        Ok(out)
    }

    pub fn to_value(&self, with_seen: bool) -> Value {
        let mut m = Map::new();
        m.insert("name".into(), Value::String(self.name.clone()));
        m.insert("trait".into(), Value::String(self.trait_.clone()));
        m.insert("x".into(), Value::from(self.x));
        m.insert("y".into(), Value::from(self.y));
        m.insert("energy".into(), Value::from(self.energy));
        m.insert("health".into(), Value::from(self.health));
        m.insert("hungry".into(), Value::from(self.hungry));
        m.insert("skills".into(), strings_to_value(&self.skills));
        m.insert("inv".into(), inv_to_value(&self.inv));
        m.insert("memory".into(), strings_to_value(&self.memory));
        m.insert("heard".into(), strings_to_value(&self.heard));
        m.insert("feedback".into(), strings_to_value(&self.feedback));
        m.insert("standing_orders".into(), Value::Array(self.standing_orders.clone()));
        m.insert("thought".into(), Value::String(self.thought.clone()));
        if with_seen {
            m.insert("seen".into(), self.seen.to_value());
        }
        if let Some(d) = self.dry {
            m.insert("dry".into(), Value::from(d));
        }
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }
}

#[derive(Clone, Debug)]
pub struct Herd {
    pub kind: String,
    pub x: i64,
    pub y: i64,
    pub count: i64,
    pub extra: Map<String, Value>,
}

impl Herd {
    fn from_value(v: &Value) -> R<Herd> {
        let m = obj(v, "herd")?;
        let mut h = Herd { kind: String::new(), x: 0, y: 0, count: 0, extra: Map::new() };
        let mut have = 0;
        for (k, val) in m {
            match k.as_str() {
                "kind" => { h.kind = string(val, "kind")?; have |= 1 }
                "x" => { h.x = int(val, "x")?; have |= 2 }
                "y" => { h.y = int(val, "y")?; have |= 4 }
                "count" => { h.count = int(val, "count")?; have |= 8 }
                _ => { h.extra.insert(k.clone(), val.clone()); }
            }
        }
        if have != 15 {
            return Err("herd is missing a key".into());
        }
        Ok(h)
    }
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("kind".into(), Value::String(self.kind.clone()));
        m.insert("x".into(), Value::from(self.x));
        m.insert("y".into(), Value::from(self.y));
        m.insert("count".into(), Value::from(self.count));
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }
}

#[derive(Clone, Debug)]
pub struct Built {
    pub kind: String,
    pub x: i64,
    pub y: i64,
    pub lit: Option<bool>,
    pub extra: Map<String, Value>,
}

impl Built {
    fn from_value(v: &Value) -> R<Built> {
        let m = obj(v, "building")?;
        let mut b = Built { kind: String::new(), x: 0, y: 0, lit: None, extra: Map::new() };
        let mut have = 0;
        for (k, val) in m {
            match k.as_str() {
                "kind" => { b.kind = string(val, "kind")?; have |= 1 }
                "x" => { b.x = int(val, "x")?; have |= 2 }
                "y" => { b.y = int(val, "y")?; have |= 4 }
                "lit" => { b.lit = Some(val.as_bool().ok_or("lit must be a bool")?) }
                _ => { b.extra.insert(k.clone(), val.clone()); }
            }
        }
        if have != 7 {
            return Err("building is missing a key".into());
        }
        Ok(b)
    }
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("kind".into(), Value::String(self.kind.clone()));
        m.insert("x".into(), Value::from(self.x));
        m.insert("y".into(), Value::from(self.y));
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        if let Some(l) = self.lit {
            m.insert("lit".into(), Value::Bool(l));
        }
        Value::Object(m)
    }
    pub fn is_lit(&self) -> bool {
        self.lit.unwrap_or(true)
    }
}

#[derive(Clone, Debug)]
pub struct Depot {
    pub x: i64,
    pub y: i64,
    pub inv: Inv,
    pub extra: Map<String, Value>,
}

impl Depot {
    fn from_value(v: &Value) -> R<Depot> {
        let m = obj(v, "depot")?;
        let mut d = Depot { x: 0, y: 0, inv: vec![], extra: Map::new() };
        let mut have = 0;
        for (k, val) in m {
            match k.as_str() {
                "x" => { d.x = int(val, "x")?; have |= 1 }
                "y" => { d.y = int(val, "y")?; have |= 2 }
                "inv" => { d.inv = inv_from(val, "inv")?; have |= 4 }
                _ => { d.extra.insert(k.clone(), val.clone()); }
            }
        }
        if have != 7 {
            return Err("depot is missing a key".into());
        }
        Ok(d)
    }
    fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("x".into(), Value::from(self.x));
        m.insert("y".into(), Value::from(self.y));
        m.insert("inv".into(), inv_to_value(&self.inv));
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }
}

#[derive(Clone, Debug, Default)]
pub struct Mark {
    pub day: i64,
    pub food: i64,
    pub seen: i64,
    pub built: i64,
    pub deaths: i64,
    pub hungry: i64,
    pub tries: i64,
}

impl Mark {
    fn from_value(v: &Value) -> R<Mark> {
        let m = obj(v, "focus_start")?;
        let get = |k: &str| -> R<i64> { int(m.get(k).ok_or_else(|| format!("focus_start lacks {}", k))?, k) };
        Ok(Mark {
            day: get("day")?,
            food: get("food")?,
            seen: get("seen")?,
            built: get("built")?,
            deaths: get("deaths")?,
            hungry: get("hungry")?,
            tries: get("tries")?,
        })
    }
    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        for (k, v) in [
            ("day", self.day),
            ("food", self.food),
            ("seen", self.seen),
            ("built", self.built),
            ("deaths", self.deaths),
            ("hungry", self.hungry),
            ("tries", self.tries),
        ] {
            m.insert(k.into(), Value::from(v));
        }
        Value::Object(m)
    }
}

#[derive(Clone, Debug)]
pub struct Guide {
    pub insight: i64,
    pub trust: i64,
    pub planted: Vec<String>,
    pub known: Vec<String>,
    pub upgrades: Vec<String>,
    pub attempts: Vec<(String, i64)>,
    pub focus: Option<String>,
    pub focus_start: Option<Mark>,
    pub era: String,
    pub extra: Map<String, Value>,
}

impl Guide {
    fn from_value(v: &Value) -> R<Guide> {
        let m = obj(v, "guide")?;
        let mut g = Guide {
            insight: 0,
            trust: 0,
            planted: vec![],
            known: vec![],
            upgrades: vec![],
            attempts: vec![],
            focus: None,
            focus_start: None,
            era: String::new(),
            extra: Map::new(),
        };
        let mut have = 0;
        for (k, val) in m {
            match k.as_str() {
                "insight" => { g.insight = int(val, "insight")?; have |= 1 }
                "trust" => { g.trust = int(val, "trust")?; have |= 2 }
                "planted" => { g.planted = strings(val, "planted")?; have |= 4 }
                "known" => { g.known = strings(val, "known")?; have |= 8 }
                "upgrades" => { g.upgrades = strings(val, "upgrades")?; have |= 16 }
                "attempts" => { g.attempts = inv_from(val, "attempts")?; have |= 32 }
                "focus" => {
                    g.focus = if val.is_null() { None } else { Some(string(val, "focus")?) };
                    have |= 64
                }
                "focus_start" => {
                    g.focus_start = if val.is_null() { None } else { Some(Mark::from_value(val)?) };
                    have |= 128
                }
                "era" => { g.era = string(val, "era")?; have |= 256 }
                _ => { g.extra.insert(k.clone(), val.clone()); }
            }
        }
        if have != 511 {
            return Err("guide is missing a key".into());
        }
        Ok(g)
    }
    fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("insight".into(), Value::from(self.insight));
        m.insert("trust".into(), Value::from(self.trust));
        m.insert("planted".into(), strings_to_value(&self.planted));
        m.insert("known".into(), strings_to_value(&self.known));
        m.insert("upgrades".into(), strings_to_value(&self.upgrades));
        m.insert("attempts".into(), inv_to_value(&self.attempts));
        m.insert("focus".into(), self.focus.clone().map(Value::String).unwrap_or(Value::Null));
        m.insert("focus_start".into(), self.focus_start.as_ref().map(|f| f.to_value()).unwrap_or(Value::Null));
        m.insert("era".into(), Value::String(self.era.clone()));
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }
}

// ------------------------------------------------------------------ the world

pub struct World {
    pub schema: i64,
    pub seed: i64,
    pub day: i64,
    pub born: Num,
    pub land_rev: i64,
    pub camp: Pt,
    pub shaped: HMap<Pt, char>,
    pub changed: HMap<Pt, char>,
    pub chunks: HSet<Pt>,
    pub villagers: Vec<Villager>,
    pub built: Vec<Built>,
    pub guidance: String,
    pub guidance_day: i64,
    pub last_planned_day: i64,
    pub log: Vec<Value>,
    pub day_started_at: Num,
    pub away: Value,
    pub speed: Num,
    pub paused_at: Option<Num>,
    pub last_read: Num,
    pub store: Inv,
    pub store_at: Pt,
    pub depots: Vec<Depot>,
    pub soil: HMap<Pt, f64>,
    pub woodlots: Vec<Pt>,
    pub woodlot_set: HSet<Pt>,
    pub fire_out: bool,
    pub pending_plans: Value,
    pub stocks: HMap<Pt, i64>,
    pub herds: Vec<Herd>,
    pub dead: Vec<Value>,
    pub emptied: i64,
    pub fallen: Option<i64>,
    pub guide: Guide,
    pub events: Option<Vec<String>>,
    pub extra: Map<String, Value>,
    /// villagers who left the list during the call, with their last state
    pub gone: Vec<(usize, Value)>,
}

const WORLD_KEYS: u64 = (1 << 33) - 1;

impl World {
    pub fn blank() -> World {
        World {
            schema: 0,
            seed: 0,
            day: 0,
            born: Num::I(0),
            land_rev: 0,
            camp: (0, 0),
            shaped: HMap::default(),
            changed: HMap::default(),
            chunks: HSet::default(),
            villagers: vec![],
            built: vec![],
            guidance: String::new(),
            guidance_day: 0,
            last_planned_day: 0,
            log: vec![],
            day_started_at: Num::I(0),
            away: Value::Null,
            speed: Num::I(1),
            paused_at: None,
            last_read: Num::I(0),
            store: vec![],
            store_at: (0, 0),
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
                insight: 0, trust: 0, planted: vec![], known: vec![], upgrades: vec![], attempts: vec![],
                focus: None, focus_start: None, era: String::new(), extra: Map::new(),
            },
            events: None,
            extra: Map::new(),
            gone: vec![],
        }
    }

    pub fn from_value(v: &Value) -> R<World> {
        let m = obj(v, "world")?;
        let mut w = World::blank();
        let mut have = 0u64;
        for (k, val) in m {
            let bit: u32 = match k.as_str() {
                "schema" => { w.schema = int(val, "schema")?; 0 }
                "seed" => { w.seed = int(val, "seed")?; 1 }
                "day" => { w.day = int(val, "day")?; 2 }
                "born" => { w.born = Num::from_value(val)?; 3 }
                "land_rev" => { w.land_rev = int(val, "land_rev")?; 4 }
                "camp" => { w.camp = pt(val, "camp")?; 5 }
                "shaped" => { w.shaped = coord_chars(val, "shaped")?; 6 }
                "changed" => { w.changed = coord_chars(val, "changed")?; 7 }
                "chunks" => {
                    for k in obj(val, "chunks")?.keys() {
                        w.chunks.insert(parse_key(k).ok_or("bad chunk key")?);
                    }
                    8
                }
                "villagers" => {
                    let list = val.as_array().ok_or("villagers must be a list")?;
                    for (i, item) in list.iter().enumerate() {
                        let mut vil = Villager::from_value(item)?;
                        vil.src = Some(i);
                        w.villagers.push(vil);
                    }
                    9
                }
                "built" => {
                    w.built = val.as_array().ok_or("built must be a list")?.iter().map(Built::from_value).collect::<R<_>>()?;
                    10
                }
                "guidance" => { w.guidance = string(val, "guidance")?; 11 }
                "guidance_day" => { w.guidance_day = int(val, "guidance_day")?; 12 }
                "last_planned_day" => { w.last_planned_day = int(val, "last_planned_day")?; 13 }
                "log" => { w.log = val.as_array().ok_or("log must be a list")?.clone(); 14 }
                "day_started_at" => { w.day_started_at = Num::from_value(val)?; 15 }
                "away" => { w.away = val.clone(); 16 }
                "speed" => { w.speed = Num::from_value(val)?; 17 }
                "paused_at" => {
                    w.paused_at = if val.is_null() { None } else { Some(Num::from_value(val)?) };
                    18
                }
                "last_read" => { w.last_read = Num::from_value(val)?; 19 }
                "store" => { w.store = inv_from(val, "store")?; 20 }
                "store_at" => { w.store_at = pt(val, "store_at")?; 21 }
                "depots" => {
                    w.depots = val.as_array().ok_or("depots must be a list")?.iter().map(Depot::from_value).collect::<R<_>>()?;
                    22
                }
                "soil" => {
                    for (k, s) in obj(val, "soil")? {
                        let p = parse_key(k).ok_or("bad soil key")?;
                        w.soil.insert(p, s.as_f64().ok_or("soil must be a number")?);
                    }
                    23
                }
                "woodlots" => {
                    for s in val.as_array().ok_or("woodlots must be a list")? {
                        let p = s.as_str().and_then(parse_key).ok_or("bad woodlot key")?;
                        w.woodlots.push(p);
                        w.woodlot_set.insert(p);
                    }
                    24
                }
                "fire_out" => { w.fire_out = val.as_bool().ok_or("fire_out must be a bool")?; 25 }
                "pending_plans" => { w.pending_plans = val.clone(); 26 }
                "stocks" => {
                    for (k, n) in obj(val, "stocks")? {
                        w.stocks.insert(parse_key(k).ok_or("bad stock key")?, int(n, "stock")?);
                    }
                    27
                }
                "herds" => {
                    w.herds = val.as_array().ok_or("herds must be a list")?.iter().map(Herd::from_value).collect::<R<_>>()?;
                    28
                }
                "dead" => { w.dead = val.as_array().ok_or("dead must be a list")?.clone(); 29 }
                "emptied" => { w.emptied = int(val, "emptied")?; 30 }
                "fallen" => {
                    w.fallen = if val.is_null() { None } else { Some(int(val, "fallen")?) };
                    31
                }
                "guide" => { w.guide = Guide::from_value(val)?; 32 }
                "_events" => {
                    w.events = Some(strings(val, "_events")?);
                    33
                }
                _ => { w.extra.insert(k.clone(), val.clone()); 34 }
            };
            have |= 1 << bit;
        }
        // schema is optional on purpose (the caller checks it); everything else is required
        let need = WORLD_KEYS & !(1 << 0) & !(1 << 33) & !(1 << 34);
        if have & need != need {
            let missing: Vec<u32> = (0..34).filter(|b| need & (1 << b) != 0 && have & (1 << b) == 0).collect();
            return Err(format!("world is missing required keys (slots {:?})", missing));
        }
        Ok(w)
    }

    pub fn to_value(&self) -> Value {
        let mut m = Map::new();
        m.insert("schema".into(), Value::from(self.schema));
        m.insert("seed".into(), Value::from(self.seed));
        m.insert("day".into(), Value::from(self.day));
        m.insert("born".into(), self.born.to_value());
        m.insert("land_rev".into(), Value::from(self.land_rev));
        m.insert("camp".into(), pt_to_value(self.camp));
        m.insert("shaped".into(), chars_to_value(&self.shaped));
        m.insert("changed".into(), chars_to_value(&self.changed));
        m.insert(
            "chunks".into(),
            Value::Object(self.chunks.iter().map(|p| (key(p.0, p.1), Value::from(1))).collect()),
        );
        m.insert("villagers".into(), Value::Array(self.villagers.iter().map(|v| v.to_value(true)).collect()));
        m.insert("built".into(), Value::Array(self.built.iter().map(|b| b.to_value()).collect()));
        m.insert("guidance".into(), Value::String(self.guidance.clone()));
        m.insert("guidance_day".into(), Value::from(self.guidance_day));
        m.insert("last_planned_day".into(), Value::from(self.last_planned_day));
        m.insert("log".into(), Value::Array(self.log.clone()));
        m.insert("day_started_at".into(), self.day_started_at.to_value());
        m.insert("away".into(), self.away.clone());
        m.insert("speed".into(), self.speed.to_value());
        m.insert("paused_at".into(), self.paused_at.map(|p| p.to_value()).unwrap_or(Value::Null));
        m.insert("last_read".into(), self.last_read.to_value());
        m.insert("store".into(), inv_to_value(&self.store));
        m.insert("store_at".into(), pt_to_value(self.store_at));
        m.insert("depots".into(), Value::Array(self.depots.iter().map(|d| d.to_value()).collect()));
        m.insert(
            "soil".into(),
            Value::Object(
                self.soil
                    .iter()
                    .map(|(p, s)| (key(p.0, p.1), Number::from_f64(*s).map(Value::Number).unwrap_or(Value::Null)))
                    .collect(),
            ),
        );
        m.insert(
            "woodlots".into(),
            Value::Array(self.woodlots.iter().map(|p| Value::String(key(p.0, p.1))).collect()),
        );
        m.insert("fire_out".into(), Value::Bool(self.fire_out));
        m.insert("pending_plans".into(), self.pending_plans.clone());
        m.insert(
            "stocks".into(),
            Value::Object(self.stocks.iter().map(|(p, n)| (key(p.0, p.1), Value::from(*n))).collect()),
        );
        m.insert("herds".into(), Value::Array(self.herds.iter().map(|h| h.to_value()).collect()));
        m.insert("dead".into(), Value::Array(self.dead.clone()));
        m.insert("emptied".into(), Value::from(self.emptied));
        m.insert("fallen".into(), self.fallen.map(Value::from).unwrap_or(Value::Null));
        m.insert("guide".into(), self.guide.to_value());
        if let Some(e) = &self.events {
            m.insert("_events".into(), strings_to_value(e));
        }
        for (k, v) in &self.extra {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }

    pub fn push_event(&mut self, s: String) {
        self.events.get_or_insert_with(Vec::new).push(s);
    }
}
