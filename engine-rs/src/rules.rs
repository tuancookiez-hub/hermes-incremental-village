//! Constants and tables. `village/rules.json` is the single source of truth and is embedded
//! at build time. Scalars used in hot loops are also Rust consts; a unit test asserts each
//! equals the value in rules.json.

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::sync::OnceLock;

pub const RULES_JSON: &str = include_str!("../../village/rules.json");

pub const SCHEMA_VERSION: i64 = 10;
pub const DAY_SECONDS: i64 = 120;
pub const DAWN_FRACTION: f64 = 0.1;
pub const WALK_PER_SLOT: i64 = 3;
pub const HOME_REACH: i64 = 12;
pub const WORK_FRACTION: f64 = 0.8;
pub const MAX_CATCHUP_DAYS: i64 = 30;
pub const SPEED_IDLE_SECONDS: i64 = 30;
pub const CHUNK: i64 = 16;
pub const CAMP_CLEARING: i64 = 3;
pub const CAMP_WATER: i64 = 6;
pub const CLIMATE_PULL: f64 = 0.3;
pub const WATER_BELOW: f64 = 0.337;
pub const ROCK_ABOVE: f64 = 0.684;
pub const FOREST_ABOVE: f64 = 0.562;
pub const BERRIES_ABOVE: f64 = 0.77;
pub const SEARCH_REACH: i64 = 40;
pub const SLOTS_PER_DAY: i64 = 8;
pub const VISION: i64 = 4;
pub const TALK_RANGE: i64 = 2;
pub const MAX_ACTIONS: usize = 6;
pub const MAX_ENERGY: i64 = 10;
pub const OVERNIGHT_ENERGY: i64 = 4;
pub const HUNGRY_ENERGY: i64 = 2;
pub const MEMORY_LINES: usize = 4;
pub const HEARD_LINES: usize = 3;
pub const MAX_VILLAGERS: i64 = 6;
pub const MAX_HEALTH: i64 = 5;
pub const SEASON_DAYS: i64 = 5;
pub const BUSH_FOOD: i64 = 4;
pub const TREE_WOOD: i64 = 3;
pub const TREE_REGROW_DAYS: i64 = 6;
pub const SEEDING_CHANCE: f64 = 0.4;
pub const WOODLOT_GROW_DAYS: i64 = 4;
pub const CARRY_LIMIT: i64 = 12;
pub const PACK_FRAME_BONUS: i64 = 6;
pub const STORE_REACH: i64 = 2;
pub const BUILD_REACH: i64 = 5;
pub const FIRE_FUEL_REACH: i64 = 6;
pub const WATER_RANGE: i64 = 7;
pub const SOIL_LOSS: f64 = 0.12;
pub const SOIL_REST: f64 = 0.03;
pub const HUNT_REACH: i64 = 2;
pub const HUNT_SLOTS: i64 = 3;
pub const MEAT_PER_KILL: i64 = 6;
pub const GORE_DAMAGE: i64 = 2;
pub const HERD_LIMIT: i64 = 6;
pub const HERD_CHANCE: f64 = 0.67;
pub const BUSH_REGROW_DAYS: i64 = 3;
pub const FIELD_FOOD: i64 = 8;
pub const FIELD_GROWTH: i64 = 2;
pub const SHELTER_RANGE: i64 = 5;
pub const WOLF_CHANCE: f64 = 0.05;
pub const WOLF_BITE: i64 = 2;
pub const EMPTIED_FOR_FARMING: i64 = 4;
pub const FIELD_WATER_RANGE: i64 = 3;
pub const START_TRUST: i64 = 50;
pub const TRUST_HEEDED: i64 = 40;
pub const TRUST_EAGER: i64 = 70;
pub const FOCUS_DAYS: i64 = 5;
pub const EXPERIMENT_SLOTS: i64 = 3;

#[derive(Debug, Clone)]
pub struct Building {
    pub cost: Vec<(String, i64)>,
    pub skill: Option<String>,
    pub slots: i64,
    pub max: i64,
    pub rest: i64,
    pub food: i64,
    pub near_water: Option<i64>,
    pub idea: Option<String>,
}

#[derive(Debug, Clone)]
pub struct Idea {
    pub name: String,
    pub cost: i64,
    pub needs: Vec<String>,
    pub try_: Vec<(String, i64)>,
    pub near: Option<String>,
    pub skill: Option<String>,
}

#[derive(Debug, Clone)]
pub struct Animal {
    pub kind: String,
    pub odds: f64,
    pub gore: f64,
}

#[derive(Debug, Clone)]
pub struct StartVillager {
    pub name: String,
    pub trait_: String,
    pub skills: Vec<String>,
}

pub struct Rules {
    pub value: Value,
    pub sha256: String,
    pub items: Vec<String>,
    pub edible: Vec<String>,
    pub verbs: Vec<String>,
    pub skills: Vec<String>,
    pub seasons: Vec<String>,
    pub wanderers: Vec<String>,
    pub weights: Vec<(String, i64)>,
    pub yield_: Vec<(String, String)>,
    pub tile_chars: Vec<(String, char)>,
    pub buildings: Vec<(String, Building)>,
    pub ideas: Vec<(String, Idea)>,
    pub upgrades: Vec<(String, String, i64)>,
    pub focuses: Vec<(String, String)>,
    pub animals: Vec<Animal>,
    pub rot_by_item: Vec<(String, i64)>,
    pub levels: Vec<(i64, String)>,
    pub starting: Vec<StartVillager>,
    pub full_stock: Vec<(char, i64)>,
}

fn strs(v: &Value) -> Vec<String> {
    v.as_array().expect("array").iter().map(|s| s.as_str().expect("string").to_string()).collect()
}

fn pairs(v: &Value) -> Vec<(String, i64)> {
    v.as_object().expect("object").iter().map(|(k, n)| (k.clone(), n.as_i64().expect("int"))).collect()
}

fn opt_str(m: &Map<String, Value>, k: &str) -> Option<String> {
    m.get(k).and_then(|v| v.as_str()).map(|s| s.to_string())
}

impl Rules {
    fn load() -> Rules {
        let value: Value = serde_json::from_str(RULES_JSON).expect("rules.json is valid JSON");
        let sha256 = sha256_hex(RULES_JSON.as_bytes());
        let o = value.as_object().expect("rules.json is an object");
        let tile_chars: Vec<(String, char)> = o["TILE_CHARS"]
            .as_object()
            .expect("TILE_CHARS")
            .iter()
            .map(|(k, c)| (k.clone(), c.as_str().expect("char").chars().next().expect("char")))
            .collect();
        let buildings = o["BUILDINGS"]
            .as_object()
            .expect("BUILDINGS")
            .iter()
            .map(|(name, b)| {
                let b = b.as_object().expect("building");
                (
                    name.clone(),
                    Building {
                        cost: pairs(&b["cost"]),
                        skill: opt_str(b, "skill"),
                        slots: b["slots"].as_i64().expect("slots"),
                        max: b["max"].as_i64().expect("max"),
                        rest: b.get("rest").and_then(|v| v.as_i64()).unwrap_or(0),
                        food: b.get("food").and_then(|v| v.as_i64()).unwrap_or(0),
                        near_water: b.get("near_water").and_then(|v| v.as_i64()),
                        idea: opt_str(b, "idea"),
                    },
                )
            })
            .collect();
        let ideas = o["IDEAS"]
            .as_object()
            .expect("IDEAS")
            .iter()
            .map(|(name, i)| {
                let i = i.as_object().expect("idea");
                (
                    name.clone(),
                    Idea {
                        name: i["name"].as_str().expect("name").to_string(),
                        cost: i["cost"].as_i64().expect("cost"),
                        needs: strs(&i["needs"]),
                        try_: pairs(&i["try"]),
                        near: opt_str(i, "near"),
                        skill: opt_str(i, "skill"),
                    },
                )
            })
            .collect();
        let upgrades = o["UPGRADES"]
            .as_object()
            .expect("UPGRADES")
            .iter()
            .map(|(k, u)| (k.clone(), u["name"].as_str().expect("name").to_string(), u["cost"].as_i64().expect("cost")))
            .collect();
        let focuses = o["FOCUSES"]
            .as_object()
            .expect("FOCUSES")
            .iter()
            .map(|(k, t)| (k.clone(), t.as_str().expect("text").to_string()))
            .collect();
        let animals = o["ANIMALS"]
            .as_object()
            .expect("ANIMALS")
            .iter()
            .map(|(k, a)| Animal {
                kind: k.clone(),
                odds: a["odds"].as_f64().expect("odds"),
                gore: a["gore"].as_f64().expect("gore"),
            })
            .collect();
        let levels = o["LEVELS"]
            .as_array()
            .expect("LEVELS")
            .iter()
            .map(|l| (l[0].as_i64().expect("need"), l[1].as_str().expect("label").to_string()))
            .collect();
        let starting = o["STARTING_VILLAGERS"]
            .as_array()
            .expect("STARTING_VILLAGERS")
            .iter()
            .map(|s| StartVillager {
                name: s["name"].as_str().expect("name").to_string(),
                trait_: s["trait"].as_str().expect("trait").to_string(),
                skills: strs(&s["skills"]),
            })
            .collect();
        let full_stock = o["FULL_STOCK"]
            .as_object()
            .expect("FULL_STOCK")
            .iter()
            .map(|(tile, n)| {
                let ch = tile_chars.iter().find(|(t, _)| t == tile).expect("tile").1;
                (ch, n.as_i64().expect("int"))
            })
            .collect();
        Rules {
            sha256,
            items: strs(&o["ITEMS"]),
            edible: strs(&o["EDIBLE"]),
            verbs: strs(&o["VERBS"]),
            skills: strs(&o["SKILLS"]),
            seasons: strs(&o["SEASONS"]),
            wanderers: strs(&o["WANDERERS"]),
            weights: pairs(&o["WEIGHTS"]),
            yield_: o["YIELD"]
                .as_object()
                .expect("YIELD")
                .iter()
                .map(|(k, v)| (k.clone(), v.as_str().expect("item").to_string()))
                .collect(),
            tile_chars,
            buildings,
            ideas,
            upgrades,
            focuses,
            animals,
            rot_by_item: pairs(&o["ROT_BY_ITEM"]),
            levels,
            starting,
            full_stock,
            value,
        }
    }

    pub fn building(&self, name: &str) -> Option<&Building> {
        self.buildings.iter().find(|(n, _)| n == name).map(|(_, b)| b)
    }
    pub fn idea(&self, name: &str) -> Option<&Idea> {
        self.ideas.iter().find(|(n, _)| n == name).map(|(_, b)| b)
    }
    pub fn animal(&self, kind: &str) -> Option<&Animal> {
        self.animals.iter().find(|a| a.kind == kind)
    }
    pub fn weight(&self, item: &str) -> i64 {
        self.weights.iter().find(|(k, _)| k == item).map(|(_, w)| *w).unwrap_or(1)
    }
    pub fn is_item(&self, s: &str) -> bool {
        self.items.iter().any(|i| i == s)
    }
    pub fn is_verb(&self, s: &str) -> bool {
        self.verbs.iter().any(|i| i == s)
    }
    pub fn tile_of(&self, c: char) -> Option<&str> {
        self.tile_chars.iter().find(|(_, ch)| *ch == c).map(|(t, _)| t.as_str())
    }
    pub fn char_of(&self, tile: &str) -> char {
        self.tile_chars.iter().find(|(t, _)| t == tile).map(|(_, c)| *c).expect("tile name")
    }
    pub fn yields(&self, tile: &str) -> Option<&str> {
        self.yield_.iter().find(|(t, _)| t == tile).map(|(_, i)| i.as_str())
    }
    pub fn full_stock_of(&self, c: char) -> Option<i64> {
        self.full_stock.iter().find(|(ch, _)| *ch == c).map(|(_, n)| *n)
    }
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    digest.iter().map(|b| format!("{:02x}", b)).collect()
}

static RULES: OnceLock<Rules> = OnceLock::new();

pub fn rules() -> &'static Rules {
    RULES.get_or_init(Rules::load)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rust_consts_equal_rules_json() {
        let v = &rules().value;
        macro_rules! same {
            ($($name:ident),* $(,)?) => {$(
                let want = v[stringify!($name)].as_f64().unwrap_or_else(|| panic!("{} missing from rules.json", stringify!($name)));
                assert_eq!($name as f64, want, "{} differs from rules.json", stringify!($name));
            )*};
        }
        same!(
            SCHEMA_VERSION, DAY_SECONDS, DAWN_FRACTION, WALK_PER_SLOT, HOME_REACH, WORK_FRACTION, MAX_CATCHUP_DAYS,
            SPEED_IDLE_SECONDS, CHUNK, CAMP_CLEARING, CAMP_WATER, CLIMATE_PULL, WATER_BELOW, ROCK_ABOVE, FOREST_ABOVE,
            BERRIES_ABOVE, SEARCH_REACH, SLOTS_PER_DAY, VISION, TALK_RANGE, MAX_ACTIONS, MAX_ENERGY, OVERNIGHT_ENERGY,
            HUNGRY_ENERGY, MEMORY_LINES, HEARD_LINES, MAX_VILLAGERS, MAX_HEALTH, SEASON_DAYS, BUSH_FOOD, TREE_WOOD,
            TREE_REGROW_DAYS, SEEDING_CHANCE, WOODLOT_GROW_DAYS, CARRY_LIMIT, PACK_FRAME_BONUS, STORE_REACH, BUILD_REACH,
            FIRE_FUEL_REACH, WATER_RANGE, SOIL_LOSS, SOIL_REST, HUNT_REACH, HUNT_SLOTS, MEAT_PER_KILL, GORE_DAMAGE,
            HERD_LIMIT, HERD_CHANCE, BUSH_REGROW_DAYS, FIELD_FOOD, FIELD_GROWTH, SHELTER_RANGE, WOLF_CHANCE,
            WOLF_BITE, EMPTIED_FOR_FARMING, FIELD_WATER_RANGE, START_TRUST, TRUST_HEEDED, TRUST_EAGER, FOCUS_DAYS,
            EXPERIMENT_SLOTS,
        );
    }

    #[test]
    fn tile_characters_used_in_code_match_rules_json() {
        use crate::engine::{BERRIES, FOREST, GRASS, ROCK, WATER};
        let r = rules();
        assert_eq!(
            [r.char_of("grass"), r.char_of("forest"), r.char_of("rock"), r.char_of("berries"), r.char_of("water")],
            [GRASS, FOREST, ROCK, BERRIES, WATER]
        );
    }

    #[test]
    fn tables_load() {
        let r = rules();
        assert_eq!(r.sha256.len(), 64);
        assert_eq!(r.buildings.len(), 9);
        assert_eq!(r.verbs.len(), 12);
        assert_eq!(r.seasons[3], "winter");
        assert_eq!(r.full_stock.len(), 2);
    }
}
