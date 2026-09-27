"""Fetches, from the archive node, the state of every pool in universe.json at every daily start height
in heights.json, plus the fee-cancelling mid price at the snapshot for concentrated pools.
Everything lands in archive_cache.json; nothing is computed here."""
import json, concurrent.futures as cf
from archive import smart, pool_state, save

NEW = 30536384
U = json.load(open("universe.json"))["pools"]
heights = [h for h, _ in json.load(open("heights.json")).values()]


def info(x):
    return {"token": {"contract_addr": x}} if x.startswith("terra1") else {"native_token": {"denom": x}}


jobs = [(u["pair"], h) for u in U for h in heights]
done = 0
with cf.ThreadPoolExecutor(6) as ex:
    for _ in ex.map(lambda j: pool_state(*j), jobs):
        done += 1
        if done % 500 == 0:
            save(); print(done, "/", len(jobs), flush=True)
save()

# fee-cancelling mid price at the snapshot: geometric mean of two tiny opposite simulations
for u in U:
    if u["pair_type"] and "concentrated" in u["pair_type"]:
        res, _ = pool_state(u["pair"], NEW); A0, A1 = list(res)
        a0, a1 = max(res[A0] // 100000, 1000), max(res[A1] // 100000, 1000)
        smart(u["pair"], {"simulation": {"offer_asset": {"info": info(A0), "amount": str(a0)}}}, NEW)
        smart(u["pair"], {"simulation": {"offer_asset": {"info": info(A1), "amount": str(a1)}}}, NEW)
save()
print("done", len(jobs))
