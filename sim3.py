import numpy as np, pandas as pd
import config as C

def simulate3(B,i0,i1,buy_thr=70,stop_mult=3.0,trail_mult=3.5,time_stop=45,
              trig="both",regime="normal",be_at=2.0,cost_bps=0.0):
    O,H,L,CL,SC,TB,TP,ATR,SECTOP=(B[k] for k in ["O","H","L","CL","SC","TB","TP","ATR","SECTOP"])
    REGL=B["REG_LABEL"]; dates,tickers,sec_of=B["dates"],B["tickers"],B["sec_of"]
    if regime=="green_only": reg_mult=np.where(REGL=="green",1.0,0.0)
    else: reg_mult=np.where(REGL=="green",1.0,np.where(REGL=="red",0.0,0.5))
    TRIG={"both":TB|TP,"breakout":TB,"pullback":TP}[trig]
    cash,pos,trades,eq=float(C.STARTING_CAPITAL),{},[],[]
    cost=cost_bps/1e4
    def close_trade(j,i,price,reason):
        nonlocal cash
        p=pos.pop(j); px=price*(1-cost); cash+=p["qty"]*px
        trades.append({"ticker":tickers[j],"bars":i-p["i_in"],"reason":reason,
                       "pnl":round(p["qty"]*(px-p["entry"]),0),
                       "r_mult":round((px-p["entry"])/p["r0"],2)})
    for i in range(i0,i1):
        for j in list(pos):
            p=pos[j]; o,h,l,c=O[i,j],H[i,j],L[i,j],CL[i,j]
            if np.isnan(c): p["bars_held"]+=1; continue
            if not np.isnan(o) and o<=p["stop"]: close_trade(j,i,o,"stop (gap)"); continue
            if l<=p["stop"]: close_trade(j,i,p["stop"],"stop"); continue
            p["hi"]=max(p["hi"],c)
            if c>=p["entry"]+be_at*p["r0"]:
                p["stop"]=max(p["stop"],p["entry"],p["hi"]-trail_mult*p["atr0"])
            sc=SC[i,j]
            if not np.isnan(sc) and sc<C.EXIT_SCORE: close_trade(j,i,c,"score decay"); continue
            p["bars_held"]+=1
            if p["bars_held"]>=time_stop: close_trade(j,i,c,"time stop"); continue
        if i>0 and reg_mult[i-1]>0 and len(pos)<C.MAX_POSITIONS:
            elig=(SC[i-1]>=buy_thr)&TRIG[i-1]&SECTOP[i-1]
            cand=[j for j in np.where(elig)[0] if j not in pos and not np.isnan(O[i,j])]
            cand.sort(key=lambda j:-SC[i-1,j])
            total_eq=cash+sum(p["qty"]*(CL[i-1,jj] if not np.isnan(CL[i-1,jj]) else p["entry"]) for jj,p in pos.items())
            sec_count={}
            for jj,p in pos.items():
                s=sec_of.get(tickers[jj],"?"); sec_count[s]=sec_count.get(s,0)+1
            for j in cand:
                if len(pos)>=C.MAX_POSITIONS: break
                s=sec_of.get(tickers[j],"?")
                if sec_count.get(s,0)>=C.MAX_PER_SECTOR: continue
                atr0=ATR[i-1,j]
                if np.isnan(atr0) or atr0<=0: continue
                r0=stop_mult*atr0
                qty=int((total_eq*C.RISK_PER_TRADE*reg_mult[i-1])//r0)
                entry=O[i,j]*(1+cost)
                if qty*entry>cash: qty=int(cash//entry)
                if qty<1: continue
                cash-=qty*entry
                pos[j]={"entry":entry,"stop":entry-r0,"r0":r0,"atr0":atr0,"qty":qty,"hi":entry,"bars_held":0,"i_in":i}
                sec_count[s]=sec_count.get(s,0)+1
        eq.append(cash+sum(p["qty"]*(CL[i,jj] if not np.isnan(CL[i,jj]) else p["entry"]) for jj,p in pos.items()))
    for j in list(pos):
        c=CL[i1-1,j]; close_trade(j,i1-1,c if not np.isnan(c) else pos[j]["entry"],"end of test")
    return pd.DataFrame(trades),pd.Series(eq,index=dates[i0:i1])
