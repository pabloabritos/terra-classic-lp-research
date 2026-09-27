"""The pool universe at the snapshot block (30536384): every pair of the five DEX factories, its state,
its type, a USD value for its liquidity, and whether it already existed at the earliest start date.

Selection rule used by the report: liquidity >= MIN_USD at the snapshot. Nothing else is filtered here;
pools too young for a given window simply have no value for that window.

USD prices: USDC (Noble IBC denom) = $1. Every other token is priced from the deepest pool that pairs it
with an already-priced token (at least $50 on the priced side), propagating outward from USDC. LUNC is
priced from the Terraswap LUNC/USDC pool, a constant-product pool whose reserve ratio is its price.
Writes universe.json."""
import json, concurrent.futures as cf
from archive import smart, pool_state, save

NEW = 30536384
MIN_USD = 2000
USDC = "ibc/0BB9D8513E8E8E9AE6A9D211D9136E6DA42288DDE6CFAA453A150A4566054DC5"
LUNC_USDC_TS = "terra19h62lw77rluxf6yg4szcclcgk9tsalx72cv7dlzvzs8gy20g70js7c9jkc"
heights = json.load(open("heights.json"))
EARLIEST = heights[str(max(int(d) for d in heights))][0]

FACTORIES = {  # address: (DEX label, pagination style)
    "terra1jkndu9w5attpz09ut02sgey5dd3e8sq5watzm0": ("Terraswap", "asset_infos"),
    "terra1n75fgfc8clsssrm2k0fswgtzsvstdaah7la6sfu96szdu22xta0q57rqqr": ("Terraport V2", "asset_infos"),
    "terra1y55punu6m5cm8sgqdgt6ngevtyklaylc09qxputn6ksye4ptf9ysxmtyl6": ("Terraport V3", "asset_infos"),
    "terra154r5ft4dktg9kt9r980zw4ywry6krh9ncevu0ya54p6j50kncptsm8sdup": ("luncswap", "asset_infos"),
    "terra1ypwj6sw25g0qcykv7mzmcvsndvx56r3yrgkaw3fds7yzwl7fwwcsnxkeh7": ("Garuda DeFi", "garuda"),
}


def list_pairs(factory, style):
    out = []
    if style == "garuda":  # same query shape as the public DefiLlama adapter for Garuda
        page = smart(factory, {"pairs": {"limit": 20}}, NEW)["pairs"]
        while page:
            out += [p["contract"] for p in page]
            l = page[-1]
            r = smart(factory, {"pairs": {"pagination": {"limit": 20, "start_after": [l["asset1"], l["asset2"]]}}}, NEW)
            page = r.get("pairs", []) if "_err" not in r else []
        return out
    sa = None
    while True:
        q = {"pairs": {"limit": 30}}
        if sa:
            q["pairs"]["start_after"] = sa
        ps = smart(factory, q, NEW)["pairs"]
        out += [p["contract_addr"] for p in ps]
        if len(ps) < 30:
            return out
        sa = ps[-1]["asset_infos"]


pairs = []
for f, (dex, style) in FACTORIES.items():
    ps = list_pairs(f, style)
    print(dex, len(ps), "pairs", flush=True)
    pairs += [(p, dex) for p in ps]
save()


def load(item):
    p, dex = item
    st = pool_state(p, NEW)
    return p, dex, st


with cf.ThreadPoolExecutor(6) as ex:
    rows = [r for r in ex.map(load, pairs) if r[2]]
save()
rows = [(p, dex, res, sh) for p, dex, (res, sh) in rows if len(res) == 2 and sh > 0 and all(v > 0 for v in res.values())]

# USD prices, propagated from USDC through the deepest pools
price = {USDC: 1e-6}  # USD per base unit (6 decimals)
r = pool_state(LUNC_USDC_TS, NEW)[0]
price["uluna"] = r[USDC] * 1e-6 / r["uluna"]
changed = True
while changed:
    changed = False
    best = {}
    for p, dex, res, sh in rows:
        (a, ra), (b, rb) = res.items()
        for (x, rx), (y, ry) in (((a, ra), (b, rb)), ((b, rb), (a, ra))):
            if x in price and y not in price:
                v = rx * price[x]
                if v > best.get(y, (0,))[0]:
                    best[y] = (v, v / ry)
    for y, (v, pr) in best.items():
        if v >= 50:
            price[y] = pr; changed = True

universe = []
for p, dex, res, sh in rows:
    vals = [amt * price[d] for d, amt in res.items() if d in price]
    usd = sum(vals) if len(vals) == 2 else (2 * vals[0] if vals else 0)
    if usd < MIN_USD:
        continue
    pt = smart(p, {"pair": {}}, NEW)
    ptype = json.dumps(pt.get("pair_type")) if "_err" not in pt else None
    universe.append({"pair": p, "dex": dex, "assets": list(res), "usd": round(usd), "pair_type": ptype,
                     "existed_at_earliest": pool_state(p, EARLIEST) is not None})
save()
universe.sort(key=lambda u: -u["usd"])
json.dump({"snapshot": NEW, "min_usd": MIN_USD, "prices_usd_per_base_unit": price, "pools": universe},
          open("universe.json", "w"), indent=1)
print(f"{len(rows)} pools with reserves; {len(universe)} with >= ${MIN_USD}")
for u in universe:
    print(f"{u['usd']:>8,} {u['dex']:13} {u['pair'][:16]} {u['pair_type']} full={u['existed_at_earliest']}")
