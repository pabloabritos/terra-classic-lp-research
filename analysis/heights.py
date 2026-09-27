"""Block heights for each daily start date: for d = 0..MAX_DAYS, the last block whose time is at or
before (snapshot time - d days). Writes heights.json {d: [height, block time UTC]}.

Snapshot (end of every window): block 30536384, 2026-09-24 02:05:40 UTC."""
import json
from datetime import datetime, timedelta
from archive import block_time, save

NEW = 30536384
MAX_DAYS = 139


def ts(h):
    return datetime.fromisoformat(block_time(h))


def last_block_at_or_before(target, lo, hi):
    """binary search in [lo, hi] for the highest height with time <= target"""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ts(mid) <= target:
            lo = mid
        else:
            hi = mid - 1
    return lo


t_new = ts(NEW)
out = {0: [NEW, block_time(NEW)]}
hi = NEW
for d in range(1, MAX_DAYS + 1):
    target = t_new - timedelta(days=d)
    guess = hi - 14400  # ~6 s blocks; search a window around the guess
    lo = guess - 3000
    while ts(lo) > target:
        lo -= 3000
    h = last_block_at_or_before(target, lo, hi)
    out[d] = [h, block_time(h)]
    hi = h
    if d % 20 == 0:
        print(d, h, block_time(h), flush=True); save()
save()
json.dump(out, open("heights.json", "w"), indent=0)
print("done", out[MAX_DAYS])
