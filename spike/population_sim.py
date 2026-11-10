"""Population spike: does the land push back? One tick is a game day; 20 days make a year.

Offline and free. It models headcount only, with no map, leaders or wolves, so it tests the shape of
growth and not the balance. Run:  python spike/population_sim.py
"""
import math, random, statistics as st
YEAR = 20
# stage: name, people the land feeds per worker-day (food), order limit (people before unrest and sickness), growth per year
STAGES = [
    ("Band",    2.10,     40, 0.24),
    ("Village", 2.60,    220, 0.24),
    ("Town",    3.20,   2500, 0.22),
    ("City",    4.00,  40000, 0.20),
    ("Metropolis", 5.0, 2000000, 0.20),
]
SEASON = [1.0, 1.2, 1.5, 0.0]   # spring, summer, autumn harvest, winter nothing grows
def poisson(r, lam):
    if lam > 30: return max(0, int(r.gauss(lam, math.sqrt(lam))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= L: return k
        k += 1
def run(seed, years=400, advance_delay=8, max_stage=4, drought=0.06, housing_share=0.10, overbreed=False):
    r = random.Random(seed)
    adults, kids = 3.0, 0.0
    stage = 0; store = 18.0; beds = 4.0; spoil = 0.02
    log = {}; peak = 3; famines = 0; plagues = 0; waiting = None
    for day in range(years * YEAR):
        year, s = day // YEAR, (day % YEAR) // 5
        name, yld, order, grow = STAGES[stage]
        P = adults + kids
        if P < 1: return dict(fell=year, peak=peak, famines=famines, plagues=plagues, log=log)
        if day % YEAR == 0:
            dry = r.random() < drought
        work = adults * (1 - housing_share)
        # the land gives less per head as the band outgrows what the stage can work
        crowd = 1 / (1 + (P / (order * 1.5)) ** 2)
        food = work * yld * SEASON[s] * crowd * (0.35 if dry else 1)
        store = store * (1 - spoil) + food
        need = adults + kids * 0.6
        short = max(0.0, 1 - store / need) if need else 0
        store = max(0.0, store - need)
        if short > 0:
            dead = P * short * 0.05
            if P < 30: dead = float(poisson(r, dead))
            kd = min(kids, dead * 0.6); kids -= kd; adults = max(0.0, adults - (dead - kd))
            if short > 0.3: famines += 1
        beds += adults * housing_share * 0.25
        beds = min(beds, order * 1.3)
        if s == 3 and P > beds:      # no roof in winter
            adults -= min(adults, (P - beds) * 0.015)
        # stores decide births: a full store means children, a thin one means none
        months = store / max(need, 1)
        fed = min(1.0, max(0.0, (months - 1.5) / 4))
        room = 1.0 if overbreed else min(1.0, max(0.0, 1.15 - P / max(beds, 1)) * 2.5)
        b = grow / YEAR * adults * fed * room
        n = poisson(r, b) if b < 30 else b
        kids += n
        grown = kids / (YEAR * 4)
        kids -= grown; adults += grown
        adults -= adults * 0.015 / YEAR
        if P > order and r.random() < 0.004 * (P / order):
            cull = 0.05 + r.random() * 0.12
            adults *= 1 - cull; kids *= 1 - cull * 1.3; plagues += 1
        peak = max(peak, P)
        for mark in (6, 30, 150, 1000, 10000, 100000, 1000000):
            if P >= mark and mark not in log: log[mark] = year
        if stage < max_stage and P > order * 0.8:
            if waiting is None: waiting = day
            elif day - waiting >= advance_delay * YEAR:
                stage += 1; waiting = None
    return dict(fell=None, peak=peak, famines=famines, plagues=plagues, log=log, end=adults + kids)
def report(label, **kw):
    runs = [run(s, **kw) for s in range(200)]
    fell = [x for x in runs if x["fell"] is not None]
    alive = [x for x in runs if x["fell"] is None]
    marks = {}
    for m in (6, 30, 150, 1000, 10000, 100000, 1000000):
        ys = [x["log"][m] for x in runs if m in x["log"]]
        if ys: marks[m] = f"{st.median(ys):.0f}y({len(ys)*100//len(runs)}%)"
    print(f"{label:30} fell {len(fell)*100//len(runs):3}%  end {st.median([x.get('end',0) for x in alive] or [0]):>10.0f}  famine-days {st.median(x['famines'] for x in runs):>5.0f}  plagues {st.median(x['plagues'] for x in runs):>4.0f}  {marks}")
report("guided, advances on time")
report("slow to advance (30y)", advance_delay=30)
report("never advances past band", max_stage=0, years=200)
report("stops at village", max_stage=1, years=200)
report("no housing built", housing_share=0.0, years=200)
report("harsh droughts (25%)", drought=0.25)
report("breeds past the beds", overbreed=True)
