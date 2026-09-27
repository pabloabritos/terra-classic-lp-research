"""Downloads a pool's tx history in ~1-day windows (tx.height in [lo,hi)), keeping only what is
needed to rewind reserves: the pool's bank movements (coin_received / coin_spent), the pool's
wasm sections (swap/provide/withdraw) and CW20 transfers to/from the pool. Empty windows are
recorded so 'no activity' can be told apart from 'indexing gap'.
Note: the report's data was fetched with fetch_pool_history_rpc.py (this module provides
compact() and WIN to it); the Hexxagon LCD used here drops txs older than ~10 days."""
import json,sys,time,urllib.request,urllib.parse,os
L="https://lcd.terra-classic.hexxagon.io"; H={"User-Agent":"curl/8.0"}
BPD=14538; WIN=BPD
def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=H),timeout=60) as r: return json.load(r)
        except Exception as e:
            if i==3: raise
            time.sleep(3*(i+1))
def sections(ev):
    """wasm events can hold several contract sections; split on _contract_address"""
    cur=None; attrs=[]
    for a in ev["attributes"]:
        if a["key"]=="_contract_address":
            if cur: yield cur,attrs
            cur=a["value"]; attrs=[]
        else: attrs.append((a["key"],a["value"]))
    if cur: yield cur,attrs
def compact(t,pair):
    keep=[]
    for e in t.get("events",[]):
        A=e["attributes"]
        if e["type"] in ("coin_received","coin_spent"):
            # pairs of (receiver|spender, amount), possibly repeated in one event (legacy logs);
            # attribute order varies (newer events put amount before receiver), so pair them
            # up as soon as both halves are seen, in whichever order they arrive
            who=amt=None
            for a in A:
                if a["key"] in ("receiver","spender"): who=a["value"]
                elif a["key"]=="amount": amt=a["value"]
                if who is not None and amt is not None:
                    if who==pair: keep.append([e["type"],amt])
                    who=amt=None
        elif e["type"]=="wasm":
            for c,at in sections(e):
                d=dict(at)
                if c==pair: keep.append(["pair",d])
                elif d.get("from")==pair or d.get("to")==pair or d.get("owner")==pair:
                    keep.append(["cw20",c,d])
    return {"h":int(t["height"]),"ts":t["timestamp"],"hash":t["txhash"],"code":t.get("code",0),"ev":keep}
def main(pair,new_h,days,out):
    res={"pair":pair,"new_h":new_h,"windows":[],"txs":[]}
    seen=set()
    hi=new_h+1
    for w in range(int(days)):
        lo=hi-WIN; n=0; key=None; page=0
        while True:
            q={"query":f"wasm._contract_address='{pair}' AND tx.height>={lo} AND tx.height<{hi}","order_by":"ORDER_BY_DESC","pagination.limit":"100"}
            if key: q["pagination.key"]=key
            else: q["page"]=str(page+1)
            d=get(L+"/cosmos/tx/v1beta1/txs?"+urllib.parse.urlencode(q))
            txs=d.get("tx_responses",[])
            for t in txs:
                if t["txhash"] in seen: continue
                seen.add(t["txhash"])
                if t.get("code",0)!=0: continue
                res["txs"].append(compact(t,pair)); n+=1
            key=(d.get("pagination") or {}).get("next_key")
            page+=1
            if len(txs)<100 and not key: break
            if page>60: break
        res["windows"].append([lo,hi,n]); hi=lo
        if w%10==0:
            print(pair[:12],"window",w,"txs so far",len(res["txs"]),flush=True)
            json.dump(res,open(out,"w"))
    json.dump(res,open(out,"w")); print(pair[:12],"DONE",len(res["txs"]),flush=True)
if __name__=="__main__":
    main(sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4])
