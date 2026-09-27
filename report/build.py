"""Builds report/index.html from report/template.html and the analysis outputs.
Every number the page shows comes from ../analysis/*.json; run the analysis first, then:
    cd report && python3 build.py"""
import json, os, statistics

A = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "analysis")
load = lambda f: json.load(open(os.path.join(A, f)))
R = load("results.json"); L = load("labels.json"); LV = load("lvr_120.json"); DP = load("dao_position.json")
H = load("heights.json")

pools = []
for p in R["pools"]:
    at = p["at"]
    g = lambda d, k="lp_vs_hodl": at[str(d)][k] if str(d) in at and k in at[str(d)] else None
    s = p["starts_30_139"]
    pools.append({"label": L[p["pair"]], "dex": p["dex"], "pair": p["pair"], "usd": p["usd"],
                  "type": "concentrated" if p["pair_type"] and "concentrated" in p["pair_type"] else "constant product",
                  "d30": g(30), "d60": g(60), "d90": g(90), "d120": g(120),
                  "fees120": g(120, "fees"), "il120": g(120, "il"), "move120": g(120, "price_move"),
                  "median": s["median"], "min": s["min"], "max": s["max"], "neg": s["share_negative"],
                  "flat": s["share_flat"], "n": s["n"], "oldest": p["oldest_start_day"],
                  "series": p["series"]})

by_day = {int(d): v for d, v in R["by_start_day"].items()}
cp120 = [p for p in pools if p["fees120"] is not None]
stats = {
    "n_pools": len(pools),
    "n_full": sum(1 for p in pools if p["d120"] is not None),
    "by_dex": {d: sum(1 for p in pools if p["dex"] == d) for d in sorted({p["dex"] for p in pools})},
    "usd_total": sum(p["usd"] for p in pools),
    "lose_range": [min(v["lose"] for d, v in by_day.items() if 30 <= d <= 139 and v["pools"] == 44),
                   max(v["lose"] for d, v in by_day.items() if 30 <= d <= 139 and v["pools"] == 44)],
    "lose_median": statistics.median(v["lose"] for d, v in by_day.items() if 30 <= d <= 139 and v["pools"] == 44),
    "gain_max": max(v["gain"] for d, v in by_day.items() if 30 <= d <= 139 and v["pools"] == 44),
    "per_pool": {"lose": sum(1 for p in pools if p["median"] < -R["flat_threshold"]),
                 "flat": sum(1 for p in pools if abs(p["median"]) <= R["flat_threshold"]),
                 "gain": sum(1 for p in pools if p["median"] > R["flat_threshold"])},
    "always_lose": sum(1 for p in pools if p["neg"] == 1.0),
    "cp120": len(cp120),
    "fees120_under1": sum(1 for p in cp120 if p["fees120"] < 0.01),
    "fees120_max": max(p["fees120"] for p in cp120),
    "fees120_max_pool": max(cp120, key=lambda p: p["fees120"])["label"],
    "snapshot": R["snapshot"], "snapshot_time": H["0"][1], "start120": H["120"], "start139": H["139"],
}
data = {"pools": pools, "by_day": by_day, "lvr": LV, "lvr_excluded": load("lvr_120_excluded.json"), "dao": DP, "stats": stats, "flat": R["flat_threshold"]}
tpl = open("template.html").read()
open("index.html", "w").write(tpl.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"))))
print(json.dumps(stats, indent=1))
