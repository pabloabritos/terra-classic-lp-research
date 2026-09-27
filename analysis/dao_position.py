"""Governance-funded LUNC/USDC pools: the DAO's position at block NEW vs. what it deposited.

Deposits come from the funds attached to the DAO proposals (dao_proposals.json, from dao_fetch.py).
The DAO's share of each pool is its LP-token balance over total shares; the LP-token addresses are
read from proposal 55 (a small test withdrawal from each pool).
For each pool: USDC/LUNC deposited, USDC/LUNC held now (plus anything the DAO withdrew before NEW), the USDC an xyk pool would hold from the
price move alone (no fees), and position value vs. holding what was deposited, at today's price.
Terraport V3 is a concentrated pool: its reserve ratio is not the price, so its "vs holding" figure
uses the fee-cancelling mid price from rewind.py's cache, and the xyk-theory column does not apply.
Writes dao_position.json."""
import json, base64, urllib.request, math, sys
sys.path.insert(0, ".")
from rewind import state, coins, _STATE_CACHE

L = "https://lcd.terra-classic.hexxagon.io"
H = {"User-Agent": "curl/8.0"}
NEW = 30536384
DAO = "terra132qeqedz0yztuztj0rjav4rzlkashpsdxsmh64jpgp2ul0wdlkzquzvln6"
USDC = "ibc/0BB9D8513E8E8E9AE6A9D211D9136E6DA42288DDE6CFAA453A150A4566054DC5"
POOLS = [("Terraswap", "terra19h62lw77rluxf6yg4szcclcgk9tsalx72cv7dlzvzs8gy20g70js7c9jkc", [17, 46, 52]),
         ("Terraport V3", "terra1a29fltd5h5y8se0xanw48wkmqg7nfpmv5jsl472uun0274h8xatqd3yzfh", [29, 45, 50]),
         ("Garuda", "terra1vnt3tjg0v98hgp0vx8nynvklnjqzkzsqvtpzv9v56r800gdhmxwstv5y64", [38, 44, 49])]


def smart(a, q, h=NEW):
    u = L + f"/cosmwasm/wasm/v1/contract/{a}/smart/" + base64.b64encode(json.dumps(q).encode()).decode()
    with urllib.request.urlopen(urllib.request.Request(u, headers={**H, "x-cosmos-block-height": str(h)}), timeout=30) as r:
        return json.load(r)["data"]


props = {p["id"]: p["proposal"] for p in json.load(open("dao_proposals.json"))}
lp_of = {}
for m in props[55]["msgs"]:
    w = m["wasm"]["execute"]; inner = json.loads(base64.b64decode(w["msg"]))
    if "send" in inner:
        lp_of[inner["send"]["contract"]] = w["contract_addr"]
    if "increase_allowance" in inner:
        lp_of[inner["increase_allowance"]["spender"]] = w["contract_addr"]

out = {}
for name, P, ids in POOLS:
    res, sh = state(P, NEW)
    # the DAO's LP-token balance at NEW; cached like pool state because nodes prune historical state
    bkey = f"lpbal:{lp_of[P]}:{DAO}@{NEW}"
    if bkey not in _STATE_CACHE:
        _STATE_CACHE[bkey] = smart(lp_of[P], {"balance": {"address": DAO}})["balance"]
        json.dump(_STATE_CACHE, open("state_cache.json", "w"))
    bal = int(_STATE_CACHE[bkey])
    frac = bal / sh
    u_now = res[USDC] * frac / 1e6; l_now = res["uluna"] * frac / 1e6
    p_now = res[USDC] / res["uluna"]  # USD per LUNC (xyk mid)
    if name == "Terraport V3":
        mid = _STATE_CACHE[f"mid:{P}@{NEW}"]
        p_now = mid if mid < 1 else 1 / mid
    dep = []
    for i in ids:
        f = {x["denom"]: int(x["amount"]) for x in props[i]["msgs"][0]["wasm"]["execute"]["funds"]}
        dep.append((f[USDC] / 1e6, f["uluna"] / 1e6))
    U = sum(d[0] for d in dep); Lx = sum(d[1] for d in dep)
    # xyk, no fees: each deposit's USDC scales by sqrt(p_now / p_deposit)
    u_theory = sum(u * math.sqrt(p_now / (u / l)) for u, l in dep) if name != "Terraport V3" else None
    # add back what the DAO itself withdrew before NEW (proposal #55, a ~$100 test withdrawal per pool):
    # it left the pool but is still the DAO's, so it belongs in "value now"
    wu = wl = 0.0
    for pool, h, act, d in json.load(open("dao_lp_actions.json")):
        if pool != name or act != "withdraw_liquidity" or h > NEW:
            continue
        if "refund_assets" in d:
            got = coins(d["refund_assets"])
        else:  # Garuda: withdrawn_asset1/2 in the pool's asset1/asset2 order
            got = dict(zip(list(res), (int(d["withdrawn_asset1"]), int(d["withdrawn_asset2"]))))
        wu += got.get(USDC, 0) / 1e6; wl += got.get("uluna", 0) / 1e6
    hodl = U + Lx * p_now; val = u_now + wu + (l_now + wl) * p_now
    out[name] = dict(usdc_in=U, lunc_in=Lx, usdc_now=u_now, lunc_now=l_now, dao_share=frac, usdc_pool=res[USDC] / 1e6,
                     usdc_theory_xyk=u_theory, withdrawn_usdc=wu, withdrawn_lunc=wl, value_now=val, hodl_now=hodl, p_now=p_now, dep_prices=[u / l for u, l in dep])
    print(f"\n{name}: DAO holds {frac*100:.1f}% of the pool (whole pool: {res[USDC]/1e6:,.0f} USDC + {res['uluna']/1e12:,.1f}M LUNC)")
    print(f"  deposited: {U:,.0f} USDC + {Lx/1e6:,.1f}M LUNC   (deposit prices: {', '.join(f'${u/l:.8f}' for u, l in dep)})")
    print(f"  holds now: {u_now:,.0f} USDC + {l_now/1e6:,.1f}M LUNC   (LUNC now ${p_now:.8f})")
    print(f"  USDC: {u_now-U:+,.0f} ({(u_now/U-1)*100:+.1f}%)   | expected from price alone (xyk, no fees): {u_theory and f'{u_theory:,.0f}' or 'n/a'}")
    print(f"  withdrawn by the DAO before the snapshot (added back): {wu:,.2f} USDC + {wl/1e6:,.2f}M LUNC")
    print(f"  position ${val:,.0f} vs holding the deposit ${hodl:,.0f} -> {val-hodl:+,.0f} ({(val/hodl-1)*100:+.2f}%)")
json.dump(out, open("dao_position.json", "w"), indent=1)
