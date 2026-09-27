"""Compares LVR theory (Milionis et al. 2022: expected loss of an x*y=k LP = sigma^2/8 of pool value
per unit of time) against every constant-product pool of the universe with a tx history. Uses the exact rewind:
daily mid price (reserve ratio), volume (offer_amount of each swap, valued in the quote asset at
the mid price of the moment), growth of sqrt(k)/share = fees retained by the LP."""
import json,math,os,statistics,sys
from datetime import datetime
from rewind import tx_delta
from archive import pool_state as state
# every constant-product pool of the universe that has a tx history (volume needs the swaps)
_U=json.load(open("universe.json"))["pools"]; _L=json.load(open("labels.json"))
POOLS_ALL=[(u["pair"],f'{_L[u["pair"]]} {u["dex"]}') for u in _U
           if not (u["pair_type"] and "concentrated" in u["pair_type"]) and os.path.exists(f'hist_rpc/{u["pair"]}.json')]
DAYS=int(sys.argv[1]) if len(sys.argv)>1 else 120
ONLY=sys.argv[2].split(",") if len(sys.argv)>2 else None
POOLS=[p for p in POOLS_ALL if not ONLY or any(o in p[1] for o in ONLY)]
HEIGHTS={int(d):h for d,(h,_) in json.load(open("heights.json")).items()}
t_new=datetime.strptime(json.load(open("heights.json"))["0"][1],"%Y-%m-%dT%H:%M:%S").timestamp()  # snapshot
t0=t_new-DAYS*86400


def sigma_day(prices):
    """Daily volatility from a price path [(ts, price in force from ts on), newest first].
    Daily closes depend on the hour chosen to cut the day (up to +-15% on sigma for the pools here),
    so the daily variance is averaged over all 24 possible cut hours."""
    path=sorted(prices)
    variances=[]
    for off in range(24):
        closes=[]; j=len(path)-1
        cut=t_new-off*3600
        while cut>=t0:
            while j>=0 and path[j][0]>cut: j-=1
            if j<0: break
            closes.append(path[j][1]); cut-=86400
        rets=[math.log(closes[k]/closes[k+1]) for k in range(len(closes)-1)]
        if len(rets)>2: variances.append(statistics.pvariance(rets))
    return math.sqrt(statistics.mean(variances)) if variances else 0.0


out=[]; skipped=[]
for pair,label in POOLS:
    raw=json.load(open(f"hist_rpc/{pair}.json")); res,sh=state(pair,raw["new_h"]); A0,A1=list(res)
    txs=sorted(raw["txs"],key=lambda t:-t["h"])
    if not txs: continue
    r=dict(res); s=sh; prices=[(t_new,res[A1]/res[A0])]; vol_q=0.0; tvl_q=[]; t_first=t0
    created=False
    at_day={}; nd=1   # rewound state at each daily start height crossed, to check against the archive
    for t in txs:
        while nd<=DAYS and t["h"]<=HEIGHTS[nd]:
            at_day[nd]=(dict(r),s); nd+=1
        ts=datetime.strptime(t["ts"],"%Y-%m-%dT%H:%M:%SZ").timestamp()
        if ts<t0: break
        p=r[A1]/r[A0]                              # price right after this tx
        prices.append((ts,p))                      # ... in force from this tx until the next one
        tvl_q.append(2*r[A1])
        d,ds,sw=tx_delta(t,pair,[A0,A1])
        for a in sw:
            off=int(a.get("offer_amount",0)); oa=a.get("offer_asset")
            if isinstance(oa,str) and oa.startswith("{"): oa=list(json.loads(oa).values())[0]   # Garuda format
            vol_q+= off*p if oa==A0 else off
        nr={k:r[k]-d[k] for k in (A0,A1)}
        if s-ds<=0 or min(nr.values())<=0: created=True; break   # pool creation reached: stop at its first state
        r=nr; s-=ds; t_first=ts
    if not created: prices.append((t0-1,r[A1]/r[A0]))  # price in force at the window start
    while nd<=DAYS and nd not in at_day and HEIGHTS[nd]>=0:
        at_day[nd]=(dict(r),s); nd+=1
    D=min(DAYS,(t_new-t_first)/86400) if created else DAYS   # pools older than the window cover all of it
    # the rewind is only trusted if it lands exactly on the real state at the oldest full day it covers
    dv=min(DAYS,int(D))
    real=state(pair,HEIGHTS[dv]) if dv>=1 else None
    def same(x,y):   # reserves and shares equal to one part in a million
        return x and all(abs(x[0][k]-y[0][k])<=1e-6*y[0][k] for k in y[0]) and abs(x[1]-y[1])<=1e-6*y[1]
    if not real or not same(at_day.get(dv),real):
        skipped.append((label,dv)); continue
    k0=math.sqrt(r[A0]*r[A1])/s; k1=math.sqrt(res[A0]*res[A1])/sh
    fees=k1/k0-1
    sig_d=sigma_day(prices)
    sig_y=sig_d*math.sqrt(365)
    lvr=sig_d**2/8*D
    tvl=statistics.mean(tvl_q) if tvl_q else 2*res[A1]
    turnover=vol_q/tvl
    feerate=fees/turnover if turnover else 0
    breakeven_turnover_per_day=(sig_d**2/8)/feerate if feerate>0 else None   # undefined without fees
    out.append((label+(f' ({D:.0f}d)' if D<DAYS-1 else ''),D,sig_y,fees,lvr,turnover/D,feerate,breakeven_turnover_per_day))
json.dump([dict(zip(("pool","days","sigma_year","fees","lvr","turnover_day","lp_fee_rate","breakeven_turnover_day"),o)) for o in out],
          open(f"lvr_{DAYS}.json","w"),indent=1)
print(f"window {DAYS} days. annual sigma of daily mid price (variance averaged over the 24 possible daily cut hours); theoretical LVR = sigma_day^2/8 x days; fees = actual growth of sqrt(k)/share")
print(f"{'pool':34} {'sigma/yr':>9} {'fees':>9} {'LVR theory':>11} {'net theory':>11} {'turnover/day':>12} {'LP fee':>8} {'breakeven turnover':>19}")
for l,D,sy,f,lv,tpd,fr,be in out:
    print(f"{l:34} {sy*100:>8.0f}% {f*100:>+8.2f}% {-lv*100:>+10.2f}% {(f-lv)*100:>+10.2f}% {tpd*100:>11.1f}% {fr*100:>7.3f}% {('%.1f%%'%(be*100)) if be is not None else 'n/a':>19}")
json.dump([l for l,_ in skipped],open(f"lvr_{DAYS}_excluded.json","w"),indent=1)
print("\nexcluded (rewound state differs from the real state at the window start by more than 1 part in a million, e.g. tokens with non-standard transfers):")
for l,dv in skipped: print(f"  {l} (checked at day {dv})")
