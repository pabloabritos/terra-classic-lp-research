"""Read-only queries against a Terra Classic archive node (RPC abci_query), with an on-disk cache.

Every answer used by the analysis is stored in archive_cache.json, keyed by (contract, query, height),
so the whole analysis can be re-run offline, and every cached value can be re-checked online against
any node that still keeps state at that height.

Default node: Stakely's public RPC, which (as of Sep 2026) serves contract state back to ~height 28.5M.
Override with the ARCHIVE_RPC environment variable.
"""
import json, os, base64, time, threading, urllib.request, urllib.parse

RPC = os.environ.get("ARCHIVE_RPC", "https://terraclassic-rpc-server-01.stakely.io")
H = {"User-Agent": "curl/8.0"}
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive_cache.json")
try:
    CACHE = json.load(open(CACHE_FILE))
except FileNotFoundError:
    CACHE = {}
_lock = threading.Lock()


def save():
    """Merge this process's answers into the file (other processes may be writing too), atomically."""
    with _lock:
        try:
            disk = json.load(open(CACHE_FILE))
        except (FileNotFoundError, json.JSONDecodeError):
            disk = {}
        disk.update(CACHE)
        CACHE.update(disk)
        tmp = f"{CACHE_FILE}.{os.getpid()}.tmp"
        with open(tmp, "w") as fh:
            json.dump(disk, fh, sort_keys=True)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, CACHE_FILE)


def _varint(n):
    b = b""
    while True:
        t = n & 0x7F; n >>= 7
        if n:
            b += bytes([t | 0x80])
        else:
            return b + bytes([t])


def _field(num, data):
    return _varint(num << 3 | 2) + _varint(len(data)) + data


def _readvarint(b, i):
    s = r = 0
    while True:
        c = b[i]; r |= (c & 0x7F) << s; i += 1; s += 7
        if not c & 0x80:
            return r, i


def _get(url):
    last = None
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url[:120]}: {last}")


def smart(addr, query, height):
    """Contract smart query at a height. Returns the decoded JSON answer, or {"_err": msg} if the
    node refuses (e.g. the contract did not exist yet). Raises if the height is pruned on the node."""
    key = f"{addr}|{json.dumps(query, sort_keys=True)}|{height}"
    if key in CACHE:
        return CACHE[key]
    req = _field(1, addr.encode()) + _field(2, json.dumps(query).encode())
    u = RPC + "/abci_query?" + urllib.parse.urlencode(
        {"path": '"/cosmwasm.wasm.v1.Query/SmartContractState"', "data": "0x" + req.hex(), "height": str(height)})
    r = _get(u)["result"]["response"]
    if r.get("code"):
        log = r.get("log", "")
        if "pruned" in log or "version does not exist" in log:
            raise RuntimeError(f"height {height} not available on {RPC}: {log[:120]}")
        out = {"_err": log[:300]}
    else:
        b = base64.b64decode(r["value"]); _, i = _readvarint(b, 0); ln, i = _readvarint(b, i)
        out = json.loads(b[i:i + ln])
    with _lock:
        CACHE[key] = out
    return out


def block_time(height):
    """UTC time of a block, 'YYYY-MM-DDTHH:MM:SS'."""
    key = f"time|{height}"
    if key not in CACHE:
        t = _get(f"{RPC}/header?height={height}")["result"]["header"]["time"][:19]
        with _lock:
            CACHE[key] = t
    return CACHE[key]


def pool_state(pair, height):
    """(reserves {denom_or_cw20: int}, total LP shares) for Terraswap/Terraport/luncswap/Astroport-style
    pairs and for Garuda's pair format. None if the pair did not exist at that height."""
    d = smart(pair, {"pool": {}}, height)
    if "_err" in d:
        return None
    res = {}
    if "assets" not in d:  # Garuda: asset1/asset2, reserve1/reserve2, total_supply
        for k in ("1", "2"):
            res[list(d["asset" + k].values())[0]] = int(d["reserve" + k])
        return res, int(d["total_supply"])
    for a in d["assets"]:
        i = list(a["info"].values())[0]
        res[i.get("denom") or i["contract_addr"]] = int(a["amount"])
    return res, int(d["total_share"])
