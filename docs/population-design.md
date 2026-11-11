# Population design

Status: proposal, nothing built. Numbers come from two offline spikes, `spike/population_sim.py`
(growth through stages) and `spike/carrying_sim.py` (limits set by regrowing resources). Both model
headcount only, with no map, leaders or wolves. They test the shape of the rules, not the balance.

## The problem

- The game is capped at 6 villagers, and there are no births.
- 20 unguided villages run for 240 days stayed at 3, built only a lean-to and never fell. They lost
  about 7 villagers each, and wanderers replaced them for free, which undercuts lethal survival.
- A council's worst case climbs with every villager Hermes plays: about 3,900 tokens at 3, 5,400 at 6,
  18,000 at 30 and 66,000 at 100.
- The engine copes with 1,000 people at about 300 ms a day, but the save grows to 2.7 MB. Each villager
  on the page is a full animated model. The page's limit has not been measured.

## The start: stranded on an island

A small group washes up on an island. The world is still endless, but it is mostly sea, with other
islands and, far off, a mainland. Fog of war covers the sea as well as the land.

The island is not a level with a size limit. It is a place whose shellfish, fish and forest regrow at
their own pace, and that pace decides how many people it can feed.

## Leaders and crews

Population is a number. Up to 6 **leaders** stay exactly as villagers are today: named, simulated tile
by tile, and played by Hermes. Everyone else is **folk**, a headcount shared out into each leader's
**crew**, plus children and elders who eat but do not work.

A crew multiplies what its leader does:

- Gathering and fishing yield more, but each stock holds what it holds, so a big crew empties it
  faster.
- A crew carries more, builds faster and goes where its leader goes.

This keeps the map, fog, finite resources and validation unchanged. Hermes still decides; the game
still owns time and resources. Council cost stays near the 6-villager figure at any population.

## What limits growth

There is no population cap anywhere. The limits are calculated from the world.

**Resources regrow.** Every stock (shellfish beds, fish, game, forest, fields) regrows quickly when
half used and slowly when nearly empty or nearly full. That sets how much food a place can give
forever. A village that takes more than that grows for a while, then the stock thins and people starve.

**Some stocks can tip.** Below about a fifth of its size a stock barely comes back: no schools left to
spawn, no seed trees left to reseed. Better tools (nets, traps, canoes) make it easy to cross that
line, which is when collapses happen.

**Wood is shared.** Firewood, huts and boats all come out of the same forest that feeds people.

**Beds.** Births need a full store and a free bed. Winter cold kills people without a roof.

**Crowding.** Sickness grows with people per tile, and with distance from clean water. It is calculated
from the settlement, not set per stage.

Children take years to become workers, so a boom eats long before it works, and a crash echoes years
later. The page shows the numbers that matter: food produced against food eaten, each stock's trend,
and what is holding the village back.

### Carrying-capacity results

The island regrows about 64 food a day at best. Nets arrive in year 40.

| Island run | Result |
|---|---|
| Takes all it can | Grows to 56, crashes after nets, everyone dead by year 47 |
| Holds back once the catch falls | Steady at 54 |
| Takes all it can, plus 40 food a day shipped in | Island stocks destroyed; lives on imports alone at 40 |
| Holds back, plus 40 food a day shipped in | Steady at about 86 |

Restraint is decided by Hermes, not the game. The game only makes the signs visible: each trip brings
back less, and the story says so. Whether the village holds back is a council decision.

The total collapse is too fast and too complete. Real island collapses left survivors. This needs tuning.

## Discovering the sea

Ideas need **clues**. A villager only notices what they can see, so clues depend on exploring.

| Clue | Idea it opens | Experiment |
|---|---|---|
| Shellfish at low tide | None needed | Gather on the shore from day 1 |
| Fish leaping in the shallows | Fishing | A sharpened stick near water |
| A log carried out on the tide | Rafts | Logs lashed with cord (weaving) |
| Fire burning a hollow into a fallen trunk | Dugout canoe | Burn and scrape a log; needs fire and stone tools |
| Birds flying out to sea every evening | Wayfinding | Follow them past sight of land |
| A cloud that never moves on the horizon | A known landfall | A voyage to it |

Verbs only exist once their idea is learned, so Hermes cannot build a boat on day 1 just because it
knows boats exist. Villagers can work ideas out alone, slowly; the player's Insight makes it sooner.

Voyages are lethal. Rafts can break up in rough water, and a voyage past the horizon is a bet the
council has to choose.

## Settlements and trade

The first island stays a home after the mainland is found. Each place keeps its own people, stores and
stocks, so places specialise: the island fishes, the mainland farms and cuts wood.

- **Routes.** A boat crew can be given a standing route, like taking dried fish to the mainland each
  week and bringing back grain. Boats have a capacity, and voyages take days.
- **Spoilage.** Fresh fish rots before it arrives. Drying, smoking and later salt make it worth
  shipping, so preservation and logistics depend on each other.
- **Dependence.** A place living on imports starves if its boats stop.
- **Leaders.** There are still 6 leaders in total. A settlement without one runs on standing orders.

## Stages

Stages are not population thresholds. Each one needs ideas, and each raises what land can give per
person, how far goods can travel, or how crowded a place can be before sickness spreads.

| Stage | Opens with |
|---|---|
| Castaways | Shore gathering, fire, shelter |
| Fishers | Fishing, rafts, drying |
| Voyagers | Dugouts, wayfinding, the first other island |
| Settlers | The mainland, sowing, storage, routes |
| Town | Bronze, tallies, walls |
| City | Writing, law, roads, sewers |
| Metropolis | Steam, steel, then flight |

## Death and arrivals

- The death of a leader matters. Someone from their crew steps up, with a line in the story.
- A village falls only when nobody is left in any settlement.
- Wanderers no longer replace the dead for free. Arrivals come as occasional groups after good years.
- Threats scale with the village, so a large one is never safe. Storms and droughts are forecast a
  season ahead, which gives councils something real to plan for.

## Borrowed from games that made it work

Mechanics only, not their content.

| From | What works | Used here |
|---|---|---|
| Civilization VI | Growth limited by food, housing and amenities | Food, beds, crowding |
| Banished | Houses gate births; generations boom and collapse | Beds gate births; child delay |
| Kittens Game, A Dark Room | Headcount and job counts are the interface | People tab; population as a number |
| Crusader Kings | Named rulers carry the story at any scale | Leaders, succession, Legacy |
| Anno | Islands specialise and trade routes carry goods between them | Settlements and routes |
| Frostpunk | Large groups read as workforce numbers | Crews |
| Dwarf Fortress | Migrants arrive in waves after good seasons | Group arrivals |
| RimWorld | A storyteller paces threats to how the colony is doing | Threats scale with the village |
| Timberborn | Forecast droughts make stockpiling a real plan | Storm and drought forecasts |
| Songs of Syx | Huge crowds work as many tiny simple figures | Crowd drawing |

Dwarf Fortress and RimWorld also show the limit: simulating every person in detail stops scaling, and
players stop tracking individuals well before that point.

## Growth pace

From `spike/population_sim.py`, 200 runs each, with stage limits still fixed in that spike. A game year
is 20 days, or 2.5 minutes at x16 and 40 minutes at x1.

| Scenario | Falls | Reaches 30 | 1,000 | 1,000,000 |
|---|---|---|---|---|
| Guided, advances on time | 0% | year 18 | year 56 | year 122 |
| Slow to advance | 0% | year 18 | year 99 | year 207 |
| Harsh droughts | 18% | year 36 | year 100 | year 168 |

At x16 that is about 45 minutes to 30 people and 5 hours to a million when played well. Neglect stalls
growth, and building no housing keeps the village at about 4.

## Page

- Top bar: population, and what is holding it back.
- People tab: counts by job and by settlement, leaders first, full list one click away. Clicking an egg
  still works.
- Stocks: each resource's trend, so a falling catch is visible before it becomes a famine.
- Bottom bar: speed, councils and time only.
- World: a crowd of tiny eggs working near their leaders, using shared meshes. Past a few hundred,
  buildings and density show the scale.

## Engine and saves

- Population stays a few numbers per crew and per stock, so saves stay small.
- The frozen reference engine remains the check on existing rules. New worlds carry a flag; worlds
  without it behave as they do now, so the differential tests keep working. New rules get their own
  tests.
- Terrain needs sea and islands, which also goes behind the flag.
- `MAX_CATCHUP_DAYS` is 30, about 1.5 game years, which is too short for an incremental game.

## Build order

1. Run one real council in Hermes Desktop. Leaders only work if councils do, and this is still unproven.
2. Replace the villager bar with the People tab and population count.
3. Island terrain, shore gathering, regrowing stocks, folk, births, beds and crews.
4. Fix deaths and arrivals: succession, group arrivals, falling only at zero, scaling threats.
5. Clues, fishing and rafts.
6. Draw crowds, and measure what the page can really handle.
7. Dugouts, wayfinding, a second island, then settlements and routes.
8. The mainland, then later stages one at a time.

## Open decisions

- Do leaders age and die of old age? Yes gives dynasties and more story, but adds rules.
- How long may the village catch up while you are away?
- Are there other peoples on other islands, and when?
