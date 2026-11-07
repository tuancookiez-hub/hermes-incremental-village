//! The land: a pure function of the seed and the position, cached per chunk.

use crate::rules::*;
use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::rc::Rc;

pub type Chunk = [[u8; 16]; 16];

const CACHE_CAP: usize = 16384;

struct Cache {
    map: HashMap<(i64, i64, i64), (Rc<Chunk>, u64)>,
    tick: u64,
    last: Option<((i64, i64, i64), Rc<Chunk>)>,
}

thread_local! {
    static CACHE: RefCell<Cache> = RefCell::new(Cache { map: HashMap::new(), tick: 0, last: None });
}

pub fn dist(ax: i64, ay: i64, bx: i64, by: i64) -> i64 {
    (ax - bx).abs().max((ay - by).abs())
}

fn lattice(seed: i64, x: i64, y: i64) -> f64 {
    // Python ints are unbounded; i128 keeps every low bit for the coordinates we can meet.
    let h: i128 = x as i128 * 374761393 + y as i128 * 668265263 + seed as i128 * 2147483647;
    let mut h = (h & 0xFFFF_FFFF) as u64;
    h = ((h ^ (h >> 13)).wrapping_mul(1274126177)) & 0xFFFF_FFFF;
    ((h ^ (h >> 16)) % 100000) as f64 / 100000.0
}

fn noise(seed: i64, x: f64, y: f64) -> f64 {
    let xi = x.floor() as i64;
    let yi = y.floor() as i64;
    let (u, v) = (x - xi as f64, y - yi as f64);
    let (u, v) = (u * u * (3.0 - 2.0 * u), v * v * (3.0 - 2.0 * v));
    let top = lattice(seed, xi, yi) * (1.0 - u) + lattice(seed, xi + 1, yi) * u;
    let low = lattice(seed, xi, yi + 1) * (1.0 - u) + lattice(seed, xi + 1, yi + 1) * u;
    top * (1.0 - v) + low * v
}

fn layered(seed: i64, x: f64, y: f64, octaves: i32) -> f64 {
    let (mut total, mut amp, mut scale) = (0.0f64, 0.5f64, 1.0f64);
    for i in 0..octaves {
        total += noise(seed + i as i64 * 101, x * scale, y * scale) * amp;
        amp *= 0.5;
        scale *= 2.03;
    }
    total / (1.0 - 0.5f64.powi(octaves))
}

fn climate(seed: i64, x: i64, y: i64) -> (f64, f64) {
    (layered(seed + 31, x as f64 / 150.0, y as f64 / 150.0, 2), layered(seed + 37, x as f64 / 110.0, y as f64 / 110.0, 2))
}

fn make_chunk(seed: i64, cx: i64, cy: i64) -> Chunk {
    let (x0, y0) = (cx * CHUNK, cy * CHUNK);
    let mut corners = [(0.0, 0.0); 4];
    let mut n = 0;
    for b in 0..2 {
        for a in 0..2 {
            corners[n] = climate(seed, x0 + a * CHUNK, y0 + b * CHUNK);
            n += 1;
        }
    }
    let mut out = [[b'.'; 16]; 16];
    for dy in 0..CHUNK {
        let v = dy as f64 / CHUNK as f64;
        let y = y0 + dy;
        for dx in 0..CHUNK {
            let u = dx as f64 / CHUNK as f64;
            let x = x0 + dx;
            let top = (corners[0].0 * (1.0 - u) + corners[1].0 * u, corners[0].1 * (1.0 - u) + corners[1].1 * u);
            let low = (corners[2].0 * (1.0 - u) + corners[3].0 * u, corners[2].1 * (1.0 - u) + corners[3].1 * u);
            let rise = top.0 * (1.0 - v) + low.0 * v;
            let moist = top.1 * (1.0 - v) + low.1 * v;
            let height = layered(seed, x as f64 / 13.0, y as f64 / 13.0, 4) + (rise - 0.5) * CLIMATE_PULL;
            let c = if height < WATER_BELOW {
                b'~'
            } else if height > ROCK_ABOVE {
                b'R'
            } else if layered(seed + 7, x as f64 / 9.0, y as f64 / 9.0, 4) + (moist - 0.5) * CLIMATE_PULL > FOREST_ABOVE {
                b'T'
            } else if noise(seed + 13, x as f64 / 2.7, y as f64 / 2.7) > BERRIES_ABOVE {
                b'b'
            } else {
                b'.'
            };
            out[dy as usize][dx as usize] = c;
        }
    }
    out
}

/// `_land(seed, cx, cy)`
pub fn land(seed: i64, cx: i64, cy: i64) -> Rc<Chunk> {
    let key = (seed, cx, cy);
    CACHE.with(|c| {
        let mut c = c.borrow_mut();
        if let Some((k, chunk)) = &c.last {
            if *k == key {
                return chunk.clone();
            }
        }
        c.tick += 1;
        let tick = c.tick;
        let chunk = if let Some(entry) = c.map.get_mut(&key) {
            entry.1 = tick;
            entry.0.clone()
        } else {
            let chunk = Rc::new(make_chunk(seed, cx, cy));
            if c.map.len() >= CACHE_CAP {
                let mut ticks: Vec<u64> = c.map.values().map(|e| e.1).collect();
                ticks.sort_unstable();
                let cut = ticks[ticks.len() / 4];
                c.map.retain(|_, e| e.1 > cut);
            }
            c.map.insert(key, (chunk.clone(), tick));
            chunk
        };
        c.last = Some((key, chunk.clone()));
        chunk
    })
}

pub fn land_char(seed: i64, x: i64, y: i64) -> char {
    land(seed, x >> 4, y >> 4)[(y & 15) as usize][(x & 15) as usize] as char
}

fn open_country(seed: i64, x: i64, y: i64, reach: i64) -> bool {
    let mut done = std::collections::HashSet::new();
    done.insert((x, y));
    let mut queue = VecDeque::new();
    queue.push_back((x, y));
    while let Some((cx, cy)) = queue.pop_front() {
        if dist(cx, cy, x, y) >= reach {
            return true;
        }
        for (nx, ny) in [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)] {
            if !done.contains(&(nx, ny)) && land_char(seed, nx, ny) != '~' {
                done.insert((nx, ny));
                queue.push_back((nx, ny));
            }
        }
    }
    false
}

fn suits(seed: i64, x: i64, y: i64) -> bool {
    let mut any_close = false;
    let mut any_wide = false;
    for dy in -CAMP_WATER..=CAMP_WATER {
        for dx in -CAMP_WATER..=CAMP_WATER {
            if land_char(seed, x + dx, y + dy) == '~' {
                any_wide = true;
                if dx.abs().max(dy.abs()) <= CAMP_CLEARING {
                    any_close = true;
                }
            }
        }
    }
    !any_close && any_wide && open_country(seed, x, y, 40)
}

/// `_find_camp(seed)`
pub fn find_camp(seed: i64) -> (i64, i64) {
    let mut reach = 0;
    while reach < 800 {
        let mut step = -reach;
        while step <= reach {
            for (x, y) in [(step, -reach), (step, reach), (-reach, step), (reach, step)] {
                if suits(seed, x, y) {
                    return (x, y);
                }
            }
            step += 4;
        }
        reach += 4;
    }
    (0, 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(seed: i64, cx: i64, cy: i64, r: usize) -> String {
        String::from_utf8(land(seed, cx, cy)[r].to_vec()).unwrap()
    }

    // Expected values come from CPython running tests/reference_engine.py.
    #[test]
    fn land_matches_python_including_negative_and_huge_chunks() {
        assert_eq!(row(5, 0, 0, 0), "................");
        assert_eq!(row(5, -3, 4, 7), "TTTTTTTRRRRRRTTT");
        assert_eq!(row(9, 100_000_000_000, -100_000_000_000, 3), "~~....bb.~~~~..b");
    }

    #[test]
    fn lattice_keeps_python_low_bits() {
        assert_eq!(lattice(5, -1_000_000_000_000, 1_000_000_000_000), 0.96087);
        assert_eq!(lattice(123456, 1_000_000_000_000, -7), 0.01388);
        assert_eq!(layered(7, -123456.789, 98765.4321, 4), 0.43734509350968753);
    }

    #[test]
    fn camps_match_python() {
        assert_eq!(find_camp(5), (4, -4));
        assert_eq!(find_camp(77), (-4, -8));
    }

    #[test]
    fn land_char_indexes_like_python() {
        assert_eq!(land_char(9, -1, -1), land(9, -1, -1)[15][15] as char);
        assert_eq!(land_char(9, -16, -16), land(9, -1, -1)[0][0] as char);
        assert_eq!(land_char(9, -17, 0), land(9, -2, 0)[0][15] as char);
    }
}
