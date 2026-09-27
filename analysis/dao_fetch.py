"""Governance-funded LUNC/USDC pools: fetch the DAO's proposals and its liquidity actions.

  1. Finds the DAO's proposal module from the execution tx of proposal 55 -> dao_modules.json
  2. Lists every proposal of that module (list_proposals) -> dao_proposals.json
  3. Lists every provide/withdraw_liquidity sent by the DAO to the three pools -> dao_lp_actions.json
Prints the liquidity-related proposals with their messages and funds, for manual checking."""
import json, base64, urllib.request, urllib.parse

L = "https://lcd.terra-classic.hexxagon.io"
H = {"User-Agent": "curl/8.0"}
RPCS = ["http://67.213.123.159:26657", "http://135.181.79.188:26657", "http://131.153.242.219:26657"]
DAO = "terra132qeqedz0yztuztj0rjav4rzlkashpsdxsmh64jpgp2ul0wdlkzquzvln6"
POOLS = {"Terraswap": "terra19h62lw77rluxf6yg4szcclcgk9tsalx72cv7dlzvzs8gy20g70js7c9jkc",
         "Terraport V3": "terra1a29fltd5h5y8se0xanw48wkmqg7nfpmv5jsl472uun0274h8xatqd3yzfh",
         "Garuda": "terra1vnt3tjg0v98hgp0vx8nynvklnjqzkzsqvtpzv9v56r800gdhmxwstv5y64"}


def rpc(path):
    last = None
    for u in RPCS:
        try:
            with urllib.request.urlopen(urllib.request.Request(u + path, headers=H), timeout=90) as r:
                j = json.load(r)
                if "result" in j:
                    return j["result"]
                last = j
        except Exception as e:
            last = str(e)
    raise RuntimeError(last)


def smart(a, q):
    try:
        u = L + f"/cosmwasm/wasm/v1/contract/{a}/smart/" + base64.b64encode(json.dumps(q).encode()).decode()
        with urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30) as r:
            return json.load(r)["data"]
    except urllib.error.HTTPError as e:
        return {"_err": e.read()[:300].decode()}


# 1. proposal module, from the execution tx of proposal 55
q = f"\"wasm.proposal_id='55' AND wasm.dao='{DAO}'\""
mods = set()
for t in rpc("/tx_search?" + urllib.parse.urlencode({"query": q, "per_page": "5"}))["txs"]:
    for e in t["tx_result"]["events"]:
        if e["type"] == "wasm":
            A = [(a["key"], a["value"]) for a in e["attributes"]]
            for i, (k, v) in enumerate(A):
                if k == "_contract_address" and i + 1 < len(A) and A[i + 1] == ("action", "execute"):
                    mods.add(v)
print("proposal module(s):", mods)
json.dump(sorted(mods), open("dao_modules.json", "w"))
M = sorted(mods)[0]

# 2. all proposals
props, sa = [], None
while True:
    q = {"list_proposals": {"limit": 30}}
    if sa is not None:
        q["list_proposals"]["start_after"] = sa
    d = smart(M, q)
    if "_err" in d:
        print(d["_err"]); break
    ps = d.get("proposals", []); props += ps
    if len(ps) < 30:
        break
    sa = ps[-1]["id"]
print("proposals:", len(props))
json.dump(props, open("dao_proposals.json", "w"))
by_addr = {v: k for k, v in POOLS.items()}
for p in props:
    pr = p["proposal"]; txt = json.dumps(pr)
    hit = [n for a, n in by_addr.items() if a in txt]
    if hit or "provide_liquidity" in txt or "liquidity" in pr.get("title", "").lower():
        print(f"\n#{p['id']} [{pr.get('status')}] {pr.get('title')[:90]}  pools={hit}")
        for m in pr.get("msgs", []):
            w = m.get("wasm", {}).get("execute")
            if w:
                inner = json.loads(base64.b64decode(w["msg"]))
                print("   ->", w["contract_addr"][:16], by_addr.get(w["contract_addr"], ""), json.dumps(inner)[:260], "| funds:", w.get("funds"))
            else:
                print("   ->", json.dumps(m)[:200])

# 3. the DAO's liquidity actions on the three pools
found = []
for name, P in POOLS.items():
    for act in ("provide_liquidity", "withdraw_liquidity"):
        q = f"\"wasm._contract_address='{P}' AND wasm.action='{act}'\""
        page = 1
        while True:
            r = rpc("/tx_search?" + urllib.parse.urlencode({"query": q, "per_page": "100", "page": str(page), "order_by": "\"asc\""}))
            for t in r["txs"]:
                for e in t["tx_result"]["events"]:
                    if e["type"] != "wasm":
                        continue
                    cur = None; sec = []
                    for a in e["attributes"] + [{"key": "_contract_address", "value": "END"}]:
                        if a["key"] == "_contract_address":
                            if cur == P and sec:
                                d = dict(sec)
                                if d.get("action") == act and d.get("sender") == DAO:
                                    found.append((name, int(t["height"]), act, d))
                            cur = a["value"]; sec = []
                        else:
                            sec.append((a["key"], a["value"]))
            if page * 100 >= int(r["total_count"]):
                break
            page += 1
        print(name, act, "total on the node:", r["total_count"])
for x in sorted(found, key=lambda x: x[1]):
    print(x[0], x[1], x[2], json.dumps(x[3])[:300])
json.dump(found, open("dao_lp_actions.json", "w"), indent=1)
