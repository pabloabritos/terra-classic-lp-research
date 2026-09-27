"""Completeness cross-check: re-counts the txs of each window on ANOTHER RPC node and compares."""
import json,sys,urllib.parse
from fetch_pool_history_rpc import get, RPCS
raw=json.load(open(sys.argv[1])); pair=raw["pair"]; start=int(sys.argv[2]) if len(sys.argv)>2 else 1
diffs=0
for lo,hi,n in raw["windows"]:
    q=f"\"wasm._contract_address='{pair}' AND tx.height>={lo} AND tx.height<{hi}\""
    c=int(get("/tx_search?"+urllib.parse.urlencode({"query":q,"per_page":"1"}),start)["total_count"])
    if c!=n: diffs+=1; print("  DIFF window",lo,hi,"stored",n,"other node",c)
print(pair[:14],"windows",len(raw["windows"]),"with differences:",diffs)
