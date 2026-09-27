"""Rewinds a pool's reserves and total LP shares backwards from the real state at NEW,
using the actual bank / CW20 token movements of each tx (no fee formulas).

Checks:
  1. Anchors: rewound reserves+shares vs real state queried at heights in the last ~9 days.
  2. Per swap: q = return*(r_in+offer)/(r_out*offer) must fall in [0.95, 1.0005]
     (xyk with a fee on the output <= 5%). A missing tx misaligns the reserves and breaks q.
  3. The rewind stops at the first run of consecutive swaps failing the check;
     reported coverage is only the verified part.

Metric: LP vs HODL = value(basket per share at NEW, price NEW) / value(basket per share at t0, price NEW) - 1
xyk decomposition: 1+LPvsHODL = sqrt(k_ps_new/k_ps_0) * 2*sqrt(r)/(1+r), r = price_new/price_0
  -> 'fees' = sqrt(k_ps) growth, 'misalignment' = the price factor.
"""
import json, sys, base64, urllib.request, math, re
from datetime import datetime

L = "https://lcd.terra-classic.hexxagon.io"
H = {"User-Agent": "curl/8.0"}
ANCHORS = [30430000, 30470000, 30510000]
HORIZONS = [10, 30, 60, 90, 120, 140]


def smart(a, q, h):
    u = L + f"/cosmwasm/wasm/v1/contract/{a}/smart/" + base64.b64encode(json.dumps(q).encode()).decode()
    with urllib.request.urlopen(urllib.request.Request(u, headers={**H, "x-cosmos-block-height": str(h)}), timeout=30) as r:
        return json.load(r)["data"]


_STATE_CACHE_FILE = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "state_cache.json")
try:
    _STATE_CACHE = json.load(open(_STATE_CACHE_FILE))
except Exception:
    _STATE_CACHE = {}


def state(pair, h):
    """pool reserves + LP share supply at height h. Cached on disk (state_cache.json): the Hexxagon
    LCD prunes historical state after ~10 days, so every snapshot the analyses rely on is kept
    locally and never needs the node again."""
    key = f"{pair}@{h}"
    if key in _STATE_CACHE:
        r, s = _STATE_CACHE[key]
        return dict(r), int(s)
    res, s = _state_live(pair, h)
    _STATE_CACHE[key] = [res, str(s)]
    json.dump(_STATE_CACHE, open(_STATE_CACHE_FILE, "w"))
    return res, s


def _state_live(pair, h):
    d = smart(pair, {"pool": {}}, h)
    res = {}
    if "assets" not in d:  # Garuda pair_base format: asset1/asset2, reserve1/reserve2, total_supply
        for k in ("1", "2"):
            res[list(d["asset" + k].values())[0]] = int(d["reserve" + k])
        return res, int(d["total_supply"])
    for a in d["assets"]:
        i = list(a["info"].values())[0]
        res[i.get("denom") or i["contract_addr"]] = int(a["amount"])
    return res, int(d["total_share"])


COIN = re.compile(r"^(\d+)(.+)$")


def coins(s):
    out = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = COIN.match(part)
        out[m.group(2)] = out.get(m.group(2), 0) + int(m.group(1))
    return out


def tx_delta(tx, pair, assets):
    """net change of pool reserves (per asset) and shares caused by this tx"""
    d = {a: 0 for a in assets}
    ds = 0
    swaps = []
    for e in tx["ev"]:
        if e[0] == "coin_received":
            for den, amt in coins(e[1]).items():
                if den in d:
                    d[den] += amt
        elif e[0] == "coin_spent":
            for den, amt in coins(e[1]).items():
                if den in d:
                    d[den] -= amt
        elif e[0] == "cw20":
            c, a = e[1], e[2]
            if c in d and "amount" in a:
                if a.get("to") == pair:
                    d[c] += int(a["amount"])
                if a.get("from") == pair or (a.get("owner") == pair and a.get("action") in ("burn", "burn_from")):
                    d[c] -= int(a["amount"])
        elif e[0] == "pair":
            a = e[1]
            act = a.get("action")
            if act == "provide_liquidity" and "share" in a:
                ds += int(a["share"])
            elif act == "withdraw_liquidity" and "withdrawn_share" in a:
                ds -= int(a["withdrawn_share"])
            elif act == "withdraw_liquidity" and "lp_tokens_burned" in a:  # Garuda
                ds -= int(a["lp_tokens_burned"])
            elif act == "provide_liquidity" and "liquidity_minted" in a:   # Garuda
                ds += int(a["liquidity_minted"])
            elif act == "swap":
                swaps.append(a)
    return d, ds, swaps


def main(path, a0_label, a1_label, pcl=False):
    raw = json.load(open(path))
    pair, NEW = raw["pair"], raw["new_h"]
    res_new, sh_new = state(pair, NEW)
    assets = list(res_new)
    txs = sorted(raw["txs"], key=lambda t: -t["h"])
    from collections import Counter
    block_count = Counter(t["h"] for t in txs)
    # oldest fully-fetched window boundary
    lowest_fetched = min(w[0] for w in raw["windows"])

    r = dict(res_new)
    s = sh_new
    anchors = {h: state(pair, h) for h in ANCHORS}
    anchor_report = []
    timeline = [(NEW, None, dict(r), s)]  # (height, ts, reserves AFTER all txs at <=height, shares)
    bad_streak = 0
    checked = bad = 0
    cutoff = None
    volume_units = {a: 0 for a in assets}
    ai = sorted(ANCHORS, reverse=True)
    for t in txs:
        # anchors: once we pass below an anchor height, compare
        while ai and t["h"] <= ai[0]:
            h = ai.pop(0)
            real_r, real_s = anchors[h]
            anchor_report.append((h, {k: (r[k], real_r[k]) for k in assets}, (s, real_s)))
        d, ds, swaps = tx_delta(t, pair, assets)
        before = {k: r[k] - d[k] for k in assets}
        sb = s - ds
        # per-swap check (single-swap txs only, in blocks where this is the only tx touching
        # the pool -- intra-block tx order is unknown, so 'before' is only exact then)
        if not pcl and len(swaps) == 1 and block_count[t["h"]] == 1 and all(v > 0 for v in before.values()):
            sw = swaps[0]
            oa, aa = sw.get("offer_asset"), sw.get("ask_asset") or sw.get("return_asset")
            # Garuda writes assets as JSON strings: '{"native":"uluna"}' / '{"cw20":"terra1..."}'
            oa, aa = [list(json.loads(x).values())[0] if isinstance(x, str) and x.startswith("{") else x for x in (oa, aa)]
            if oa in before and aa in before:
                off, ret = int(sw["offer_amount"]), int(sw["return_amount"])
                if off > 0 and ret > 0:
                    q = ret * (before[oa] + off) / (before[aa] * off)
                    checked += 1
                    ok = 0.95 <= q <= 1.0005
                    if not ok:
                        bad += 1
                        bad_streak += 1
                    else:
                        bad_streak = 0
                    volume_units[oa] += off
                    if bad_streak >= 5:
                        cutoff = t
                        break
        if any(v < 0 for v in before.values()) or sb <= 0:
            cutoff = t
            break
        r, s = before, sb
        timeline.append((t["h"], t["ts"], dict(r), s))

    # time of NEW
    tkey = f"time@{NEW}"
    if tkey not in _STATE_CACHE:
        with urllib.request.urlopen(urllib.request.Request(L + f"/cosmos/base/tendermint/v1beta1/blocks/{NEW}", headers=H), timeout=30) as x:
            _STATE_CACHE[tkey] = json.load(x)["block"]["header"]["time"][:19]
        json.dump(_STATE_CACHE, open(_STATE_CACHE_FILE, "w"))
    ts_new = datetime.fromisoformat(_STATE_CACHE[tkey])
    oldest_ts = datetime.fromisoformat(timeline[-1][1][:19]) if timeline[-1][1] else ts_new
    cover_days = (ts_new - oldest_ts).total_seconds() / 86400

    A0, A1 = assets
    p_new = res_new[A1] / res_new[A0]
    if pcl:
        # PCL: reserve ratio is not the price; use the fee-cancelling mid from tiny two-way simulations
        mkey = f"mid:{pair}@{NEW}"
        if mkey not in _STATE_CACHE:
            def _info(x): return {"token": {"contract_addr": x}} if x.startswith("terra1") else {"native_token": {"denom": x}}
            a0amt, a1amt = max(res_new[A0] // 100000, 1000), max(res_new[A1] // 100000, 1000)
            f = smart(pair, {"simulation": {"offer_asset": {"info": _info(A0), "amount": str(a0amt)}}}, NEW)
            b = smart(pair, {"simulation": {"offer_asset": {"info": _info(A1), "amount": str(a1amt)}}}, NEW)
            _STATE_CACHE[mkey] = ((int(f["return_amount"]) / a0amt) * (a1amt / int(b["return_amount"]))) ** 0.5
            json.dump(_STATE_CACHE, open(_STATE_CACHE_FILE, "w"))
        p_new = _STATE_CACHE[mkey]

    def val(res, sh, p):
        return (res[A0] * p + res[A1]) / sh

    out = {"pair": pair, "label": f"{a0_label}/{a1_label}", "assets": assets, "checked_swaps": checked,
           "bad_swaps": bad, "cutoff": cutoff and cutoff["h"], "cover_days": cover_days,
           "lowest_fetched_h": lowest_fetched, "anchors": anchor_report, "horizons": {}}
    for hz in HORIZONS:
        if hz > cover_days + 0.01:
            continue
        # state at (ts_new - hz days): timeline[i] is the state just BEFORE tx i, so for the newest
        # tx at or before the target, the state at the target is timeline[i-1] (just after that tx)
        target = ts_new.timestamp() - hz * 86400
        pt = None
        for i in range(1, len(timeline)):
            if datetime.fromisoformat(timeline[i][1][:19]).timestamp() <= target:
                pt = timeline[i - 1]
                break
        if pt is None:
            continue
        _, _, res0, sh0 = pt
        ts0 = datetime.fromtimestamp(target).isoformat()
        lp = val(res_new, sh_new, p_new) / val(res0, sh0, p_new) - 1
        p0 = res0[A1] / res0[A0]
        rr = p_new / p0
        il = 2 * math.sqrt(rr) / (1 + rr) - 1
        kgrowth = math.sqrt((res_new[A0] * res_new[A1] / sh_new ** 2) / (res0[A0] * res0[A1] / sh0 ** 2)) - 1
        out["horizons"][hz] = {"from": ts0, "lp_vs_hodl": lp, "share_change": sh_new / sh0 - 1}
        if not pcl:  # xyk-only decomposition
            out["horizons"][hz].update({"price_move": rr - 1, "il": il, "fees": kgrowth})
    return out


if __name__ == "__main__":
    o = main(sys.argv[1], sys.argv[2], sys.argv[3], pcl=len(sys.argv) > 4 and sys.argv[4] == "pcl")
    print(json.dumps(o, indent=1, default=str))
