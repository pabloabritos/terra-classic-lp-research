"""LP vs HODL for every pool in universe.json, for every start date, ending at the snapshot.

Metric (per LP share, so other people's deposits and withdrawals don't affect it):
    LP vs HODL = value(tokens one share holds at the end) / value(tokens one share held at the start) - 1
with BOTH baskets valued at the END price. A falling token price therefore does not count against the
pool; only what the pool itself did does. External rewards (farming, incentives) are not included.

End price: the pool's reserve ratio for constant-product pools (Terraswap, Terraport V2, Terraport V3
"xyk", luncswap, Garuda), and the fee-cancelling mid price from two tiny opposite swap simulations for
concentrated pools (Terraport V3 "concentrated"), whose reserve ratio is not their price.

For constant-product pools the result splits exactly into two factors:
    1 + LP vs HODL = (1 + fees) * (1 + IL)
    fees = growth of sqrt(x*y) per share          (what the pool kept from trading fees)
    IL   = 2*sqrt(r)/(1+r) - 1, r = end price / start price   (divergence loss: depends only on the
                                                             net price move, not on the path)
Reads only archive_cache.json (run heights.py, universe.py, fetch_states.py first). Writes results.json.
"""
import json, math, statistics
from archive import smart, pool_state

NEW = 30536384
FLAT = 0.0005   # |result| below 0.05% counts as flat (typically a pool with almost no trading)
heights = {int(d): h for d, (h, _) in json.load(open("heights.json")).items()}
U = json.load(open("universe.json"))["pools"]


def info(x):
    return {"token": {"contract_addr": x}} if x.startswith("terra1") else {"native_token": {"denom": x}}


def end_price(u, res):
    A0, A1 = list(res)
    if u["pair_type"] and "concentrated" in u["pair_type"]:
        a0, a1 = max(res[A0] // 100000, 1000), max(res[A1] // 100000, 1000)
        f = smart(u["pair"], {"simulation": {"offer_asset": {"info": info(A0), "amount": str(a0)}}}, NEW)
        b = smart(u["pair"], {"simulation": {"offer_asset": {"info": info(A1), "amount": str(a1)}}}, NEW)
        return ((int(f["return_amount"]) / a0) * (a1 / int(b["return_amount"]))) ** 0.5, False
    return res[A1] / res[A0], True


out = []
for u in U:
    rn, sn = pool_state(u["pair"], NEW); A0, A1 = list(rn)
    p, xyk = end_price(u, rn)
    val = lambda r, s: (r[A0] * p + r[A1]) / s
    series = {}
    for d in range(1, max(heights) + 1):
        st = pool_state(u["pair"], heights[d])
        if not st or st[1] == 0 or min(st[0].values()) == 0 or set(st[0]) != set(rn):
            continue
        r0, s0 = st
        row = {"lp_vs_hodl": val(rn, sn) / val(r0, s0) - 1}
        if xyk:
            row["fees"] = math.sqrt(rn[A0] * rn[A1]) / sn / (math.sqrt(r0[A0] * r0[A1]) / s0) - 1
            rr = p / (r0[A1] / r0[A0])
            row["il"] = 2 * math.sqrt(rr) / (1 + rr) - 1
            row["price_move"] = rr - 1
        series[d] = row
    vals = {d: r["lp_vs_hodl"] for d, r in series.items()}
    span = [vals[d] for d in range(30, max(heights) + 1) if d in vals]
    out.append({**u, "constant_product": xyk, "oldest_start_day": max(vals) if vals else None,
                "at": {d: series[d] for d in (30, 60, 90, 120) if d in series},
                "series": {d: round(v, 6) for d, v in vals.items()},
                "starts_30_139": {"n": len(span),
                                  "median": statistics.median(span) if span else None,
                                  "min": min(span) if span else None, "max": max(span) if span else None,
                                  "share_negative": sum(v < -FLAT for v in span) / len(span) if span else None,
                                  "share_flat": sum(abs(v) <= FLAT for v in span) / len(span) if span else None}})

# per start date: how many pools lost / were flat / gained
by_day = {}
for d in range(1, max(heights) + 1):
    v = [o["series"][d] for o in out if d in o["series"]]
    by_day[d] = {"pools": len(v), "lose": sum(x < -FLAT for x in v), "flat": sum(abs(x) <= FLAT for x in v),
                 "gain": sum(x > FLAT for x in v), "median": statistics.median(v) if v else None}
json.dump({"snapshot": NEW, "flat_threshold": FLAT, "pools": out, "by_start_day": by_day},
          open("results.json", "w"), indent=1)

print(f"{'pool':46} {'$':>7} {'120d':>8} {'60d':>8} {'30d':>8} {'median30-139':>12} {'neg%':>5}")
for o in out:
    a = o["at"]; s = o["starts_30_139"]
    f = lambda d: f"{a[d]['lp_vs_hodl']*100:+7.2f}%" if d in a else "      - "
    print(f"{o['dex'][:12]:12} {o['pair'][:32]:33} {o['usd']:>7,} {f(120)} {f(60)} {f(30)} "
          f"{(s['median'] or 0)*100:+11.2f}% {(s['share_negative'] or 0)*100:4.0f}%")
for d in (30, 60, 90, 120, 139):
    b = by_day[d]; print(f"start {d:3}d: {b['pools']} pools, lose {b['lose']}, flat {b['flat']}, gain {b['gain']}, median {b['median']*100:+.2f}%")
