"""Same as fetch_pool_history.py but via RPC tx_search on network nodes (Hashed, FRG, ov and
Stakely agree with each other; the Hexxagon LCD drops txs older than ~10 days).
Timestamps: real time of each window boundary (/header), linearly interpolated inside the window."""
import json,sys,time,urllib.request,urllib.parse
from datetime import datetime,timezone
from fetch_pool_history import compact, WIN
RPCS=["http://67.213.123.159:26657","http://135.181.79.188:26657","http://131.153.242.219:26657","https://terraclassic-rpc-server-01.stakely.io"]
H={"User-Agent":"curl/8.0"}
def get(path, start=0):
    last=None
    for i in range(8):
        u=RPCS[(start+i)%len(RPCS)]+path
        try:
            with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=60) as r:
                j=json.load(r)
            if "result" in j: return j["result"]
            last=j.get("error")
        except Exception as e: last=str(e)
        time.sleep(2)
    raise RuntimeError(f"all RPCs failed: {last}")
def htime(h,start):
    t=get(f"/header?height={h}",start)["header"]["time"]
    return datetime.strptime(t[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
def main(pair,new_h,days,out,start=0):
    res={"pair":pair,"new_h":new_h,"windows":[],"txs":[],"source":"rpc tx_search"}
    seen=set(); hi=new_h+1; t_hi=htime(new_h,start)
    for w in range(int(days)):
        lo=hi-WIN; t_lo=htime(lo,start); page=1; n=0; failed=0; total=None
        while True:
            q=f"\"wasm._contract_address='{pair}' AND tx.height>={lo} AND tx.height<{hi}\""
            r=get("/tx_search?"+urllib.parse.urlencode({"query":q,"per_page":"100","page":str(page),"order_by":"\"desc\""}),start)
            total=int(r["total_count"])
            for t in r["txs"]:
                if t["hash"] in seen: continue
                seen.add(t["hash"])
                if t["tx_result"].get("code",0)!=0: failed+=1; continue
                h=int(t["height"])
                ts=t_lo+(t_hi-t_lo)*(h-lo)/(hi-lo)
                c=compact({"height":h,"timestamp":datetime.fromtimestamp(ts,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "txhash":t["hash"],"code":0,"events":t["tx_result"]["events"]},pair)
                res["txs"].append(c); n+=1
            if page*100>=total: break
            page+=1
        if n+failed!=total:  # pagination lost or duplicated txs: never store an incomplete window
            raise RuntimeError(f"{pair} window {lo}-{hi}: node reports {total} txs, got {n} ok + {failed} failed")
        res["windows"].append([lo,hi,total]); hi=lo; t_hi=t_lo
        if w%10==0:
            print(pair[:12],"window",w,"txs so far",len(res["txs"]),flush=True); json.dump(res,open(out,"w"))
    json.dump(res,open(out,"w")); print(pair[:12],"DONE",len(res["txs"]),flush=True)
if __name__=="__main__":
    main(sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4],int(sys.argv[5]) if len(sys.argv)>5 else 0)
