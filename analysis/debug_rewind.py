"""Validates the rewind against the real on-chain state at the close of every block with activity (last ~9 days)."""
import json,sys
from itertools import groupby
from rewind import *
raw=json.load(open(sys.argv[1])); pair=raw["pair"]; NEW=raw["new_h"]
MIN_H=int(sys.argv[2]) if len(sys.argv)>2 else 30400000
res,sh=state(pair,NEW); assets=list(res)
txs=sorted([t for t in raw["txs"] if t["h"]>MIN_H],key=lambda t:-t["h"])
r=dict(res); s=sh; nblocks=0
for h,grp in groupby(txs,key=lambda t:t["h"]):
    real,rs=state(pair,h)
    diff={k:r[k]-real[k] for k in assets}
    if any(diff.values()) or s!=rs:
        print("MISMATCH at close of block",h,"diff",diff,"shares",s-rs); sys.exit(1)
    nblocks+=1
    for t in grp:
        d,ds,_=tx_delta(t,pair,assets); r={k:r[k]-d[k] for k in assets}; s-=ds
print(f"OK: {nblocks} blocks, {len(txs)} txs, exact match")
