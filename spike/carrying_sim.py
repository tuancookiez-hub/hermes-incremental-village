"""Carrying-capacity spike: no population cap, only regrowing stocks that people eat.

Offline and free. Each stock regrows logistically (fast when half used, slowly when nearly empty or
nearly full), and each worker's catch falls as the stock thins. Run:  python spike/carrying_sim.py
"""
YEAR = 20
# name: (capacity, regrowth per year, food a worker gets per day from a full stock)
ISLAND = {"shellfish": (900, 1.0, 2.0), "fish": (5000, 0.7, 3.0), "forest food": (1500, 0.5, 2.5)}
MAINLAND = {"game": (20000, 0.4, 3.0), "fields": (60000, 0.9, 4.0)}

def run(stocks, years=300, restraint=None, imports=0.0, people=6.0, nets_year=40, wood_per_person=0.02):
    stock = {k: v[0] for k, v in stocks.items()}
    kids, store, seen = 0.0, 30.0, []
    for day in range(years * YEAR):
        p = people + kids
        if p < 1:
            seen.append((day // YEAR, 0)); break
        # workers go where a day's work pays best, so effort follows the richest stock
        gear = 2.2 if day >= nets_year * YEAR else 1.0  # nets, traps and canoes make taking easy
        pay = {k: gear * stocks[k][2] * stock[k] / stocks[k][0] for k in stocks}
        total = sum(pay.values()) or 1
        food = imports
        for k, (cap, regrow, rate) in stocks.items():
            workers = people * pay[k] / total
            take = min(stock[k], workers * pay[k])
            if restraint is not None:  # a village that has noticed the catch falling and holds back
                take = min(take, restraint * regrow * cap / 4 / YEAR)
            stock[k] -= take
            food += take
            if k == "forest food":  # firewood, huts and boats come out of the same forest
                stock[k] = max(0.0, stock[k] - p * wood_per_person)
            # below a fifth of its size a stock barely recovers: no schools left, no seed trees
            share = stock[k] / cap
            stock[k] += regrow / YEAR * stock[k] * (1 - share) * min(1.0, share / 0.2) ** 2
        store = store * 0.98 + food
        need = people + kids * 0.6
        short = max(0.0, 1 - store / need)
        store = max(0.0, store - need)
        if short:
            dead = p * short * 0.05
            kd = min(kids, dead * 0.6); kids -= kd; people = max(0.0, people - (dead - kd))
        fed = min(1.0, max(0.0, (store / max(need, 1) - 1.5) / 4))
        kids += 0.24 / YEAR * people * fed
        grown = kids / (YEAR * 4); kids -= grown; people += grown
        people -= people * 0.015 / YEAR
        if day % (YEAR * 15) == 0:
            seen.append((day // YEAR, round(p)))
    return seen

sustainable = sum(r * c / 4 for c, r, _ in ISLAND.values()) / YEAR
print(f"island regrows about {sustainable:.0f} food a day at best, so it can feed about that many people forever")
for label, kw in [("island, takes all it can", {}),
                  ("island, holds back once the catch falls", {"restraint": 0.85}),
                  ("island, takes all it can, plus 40 food a day shipped in", {"imports": 40.0}),
                  ("island, holds back, plus 40 food a day shipped in", {"restraint": 0.85, "imports": 40.0})]:
    print(f"\n{label}")
    print("  " + "  ".join(f"y{y}:{n}" for y, n in run(ISLAND, **kw)))
