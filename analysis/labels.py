"""Human-readable labels for the pools in universe.json: token symbols from each CW20's token_info at
the snapshot, fixed names for native and IBC denoms. Writes labels.json {pair: "SYM/SYM"}."""
import json
from archive import smart, save

NEW = 30536384
NATIVE = {"uluna": "LUNC", "uusd": "USTC",
          # sha256("transfer/channel-113/uusdc"); channel-113 -> noble-1
          "ibc/0BB9D8513E8E8E9AE6A9D211D9136E6DA42288DDE6CFAA453A150A4566054DC5": "USDC",
          # sha256("transfer/channel-19/uusdc"); channel-19 -> axelar-dojo-1
          "ibc/E1E3674A0E4E1EF9C69646F9AF8D9497173821826074622D831BAB73CCB99A2D": "axlUSDC",
          # origin not identified (the LCD's denom-trace endpoint is not implemented on the nodes tried)
          "ibc/2E13104D0924DDB574E98CF01E1FD2D8913779BCB5B514B6468C6EC6037A15DC": "IBC-2E13",
          # transfer/channel-143/erc20:0xa00C...235a, channel-143 -> injective-1
          "ibc/F52112392095A6D6D1B17EF1FE19BE0B39B2A79B8A2B2F55CD721FC7DBF5081F": "USDC.inj"}


def sym(d):
    if d in NATIVE:
        return NATIVE[d]
    if d.startswith("terra1"):
        r = smart(d, {"token_info": {}}, NEW)
        return r.get("symbol") or d[:10]
    return d[:12]


out = {}
for u in json.load(open("universe.json"))["pools"]:
    out[u["pair"]] = "/".join(sym(a) for a in u["assets"])
save()
json.dump(out, open("labels.json", "w"), indent=1)
for p, l in out.items():
    print(p[:16], l)
