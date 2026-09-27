"""Builds report/index.html (for the Claude artifact) and docs/index.html (standalone, for GitHub Pages)
from report/template.html and the analysis outputs.
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
last = max(by_day)
full_n = by_day[last]["pools"]  # pools that existed at the earliest start date
cohort = [v for d, v in by_day.items() if 30 <= d <= last and v["pools"] == full_n]
med = [p for p in pools if p["median"] is not None]
cp120 = [p for p in pools if p["fees120"] is not None]
stats = {
    "n_pools": len(pools),
    "n_full": full_n,
    "by_dex": {d: sum(1 for p in pools if p["dex"] == d) for d in sorted({p["dex"] for p in pools})},
    "usd_total": sum(p["usd"] for p in pools),
    "lose_range": [min(v["lose"] for v in cohort), max(v["lose"] for v in cohort)],
    "lose_median": statistics.median(v["lose"] for v in cohort),
    "gain_max": max(v["gain"] for v in cohort),
    "per_pool": {"lose": sum(1 for p in med if p["median"] < -R["flat_threshold"]),
                 "flat": sum(1 for p in med if abs(p["median"]) <= R["flat_threshold"]),
                 "gain": sum(1 for p in med if p["median"] > R["flat_threshold"]),
                 "no_median": len(pools) - len(med)},
    "always_lose": sum(1 for p in pools if p["neg"] == 1.0),
    "cp120": len(cp120),
    "fees120_under1": sum(1 for p in cp120 if p["fees120"] < 0.01),
    "fees120_max": max(p["fees120"] for p in cp120),
    "fees120_max_pool": max(cp120, key=lambda p: p["fees120"])["label"],
    "snapshot": R["snapshot"], "snapshot_time": H["0"][1], "start120": H["120"], "start139": H["139"],
}
data = {"pools": pools, "by_day": by_day, "lvr": LV, "lvr_excluded": load("lvr_120_excluded.json"), "dao": DP, "stats": stats, "flat": R["flat_threshold"]}
tpl = open("template.html").read()
# token symbols are chosen by whoever creates a token: escape "<" so no value can close the <script> tag
payload = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
page = tpl.replace("/*__DATA__*/null", payload)
# report/index.html: page body only (the Claude artifact host adds the document skeleton)
open("index.html", "w").write(page)
# docs/index.html: standalone document for GitHub Pages or any web server
head = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        '<style>html{color-scheme:light dark}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n')
title_end = page.index("</title>") + len("</title>")
os.makedirs(os.path.join("..", "docs"), exist_ok=True)
open(os.path.join("..", "docs", "index.html"), "w").write(
    head + page[:title_end] + "\n" + page[title_end:page.index("<div class=\"wrap\">")] + "</head>\n<body>\n"
    + page[page.index("<div class=\"wrap\">"):] + "\n</body>\n</html>\n")
print(json.dumps(stats, indent=1))
