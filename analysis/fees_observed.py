"""Trader fee and LP-retained fee per swap, read from the actual token movements of each tx
(no fee formulas, no documentation assumed).

For a tx holding exactly one swap on the pool:
  - fee taken on the input  : pool received more than offer_amount -> fee = received - offer_amount,
                              rate = fee / received
  - fee taken on the output : otherwise, rate = commission_amount / (return_amount + commission_amount)
  - Garuda                  : total_commission is inside offer_amount -> rate = total_commission / offer_amount
  - LP-retained rate        : trader fee minus what left the pool to anyone other than the swap receiver
                              (in the fee's denom), over the same base. Burn tax on those transfers is
                              counted as leaving the pool.
Prints the median trader rate and LP-retained rate per pool, plus one example tx hash for each.
Usage: python3 fees_observed.py [pair ...]   (default: every history in hist_rpc/)"""
import json, sys, glob, os, re, statistics
from rewind import coins

def denom_of(x):
    if isinstance(x, str) and x.startswith("{"):
        return list(json.loads(x).values())[0]
    return x

def analyse(path):
    raw = json.load(open(path)); pair = raw["pair"]; rows = []
    for t in raw["txs"]:
        sw = [e[1] for e in t["ev"] if e[0] == "pair" and e[1].get("action") == "swap"]
        if len(sw) != 1:
            continue
        a = sw[0]; off = int(a.get("offer_amount", 0)); ret = int(a.get("return_amount", 0))
        com = int(a.get("commission_amount") or a.get("total_commission") or 0)
        oa, aa = denom_of(a.get("offer_asset")), denom_of(a.get("ask_asset") or a.get("return_asset"))
        if not off or not ret or not com:
            continue
        recv = {}; spent = {}; cw_out = {}
        for e in t["ev"]:
            if e[0] == "coin_received":
                for d, v in coins(e[1]).items(): recv[d] = recv.get(d, 0) + v
            elif e[0] == "coin_spent":
                for d, v in coins(e[1]).items(): spent[d] = spent.get(d, 0) + v
            elif e[0] == "cw20" and e[2].get("from") == pair and "amount" in e[2]:
                cw_out[e[1]] = cw_out.get(e[1], 0) + int(e[2]["amount"])
            elif e[0] == "cw20" and e[2].get("to") == pair and "amount" in e[2]:
                recv[e[1]] = recv.get(e[1], 0) + int(e[2]["amount"])
        got = recv.get(oa, 0)
        out_total = spent.get(aa, 0) + cw_out.get(aa, 0)
        if "total_commission" in a:                                        # Garuda: fee inside offer_amount
            leaked = spent.get(oa, 0) + cw_out.get(oa, 0)                  # protocol_fee leaves the pool
            rows.append((com / off, max(0.0, (com - leaked) / off), t["hash"]))
            continue
        if got > off and abs((got - off) - com) <= max(2, com // 1000):   # fee on the input side
            base = got; fee_d = oa
            leaked = spent.get(oa, 0) + cw_out.get(oa, 0)
        else:                                                              # fee on the output side
            base = ret + com; fee_d = aa
            leaked = max(0, out_total - ret)  # anything beyond the receiver's return (incl. burn tax on it)
        rows.append((com / base, max(0.0, (com - leaked) / base), t["hash"]))
    return pair, rows

paths = [f"hist_rpc/{p}.json" for p in sys.argv[1:]] or sorted(glob.glob("hist_rpc/terra1*.json"))
paths = [p for p in paths if re.fullmatch(r"hist_rpc/terra1[0-9a-z]+\.json", p)]
for p in paths:
    pair, rows = analyse(p)
    if not rows:
        continue
    tr = statistics.median(r[0] for r in rows); lp = statistics.median(r[1] for r in rows)
    ex = min(rows, key=lambda r: abs(r[0] - tr))[2]
    print(f"{pair}  n={len(rows):5}  trader fee median {tr*100:.3f}%  LP keeps median {lp*100:.3f}%  example {ex}")
