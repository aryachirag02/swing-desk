"""v3 simulator: v2 rules + pluggable regime label array + optional kill-switch."""
import numpy as np, pandas as pd
import config as C
from backtest import metrics

def simulate4(B,lbl,a,b,kill="none",cost_bps=0,ret_trades=False):
    O,H,L,CL,SC,TB,ATR,SECTOP=(B[k] for k in ["O","H","L","CL","SC","TB","ATR","SECTOP"])
    tickers,sec_of,dates=B["tickers"],B["sec_of"],B["dates"]
    cash,pos,trades,eq=float(C.STARTING_CAPITAL),{},[],[]
    cost=cost_bps/1e4; YD=getattr(C,"CASH_YIELD_PA",0.0)/252
    def close(j,i,price,reason):
        nonlocal cash
        p=pos.pop(j); pxx=price*(1-cost); cash+=p["qty"]*pxx
        trades.append({"ticker":tickers[j],"entry_date":str(dates[p["i_in"]].date()),
                       "exit_date":str(dates[i].date()),"pnl":round(p["qty"]*(pxx-p["entry"]),0),
                       "r_mult":round((pxx-p["entry"])/p["r0"],2),"bars":i-p["i_in"],"reason":reason})
    for i in range(a,b):
        cash*=(1+YD)
        gtoday=lbl[i]=="green"
        for j in list(pos):
            p=pos[j]; o,hh,ll,cc=O[i,j],H[i,j],L[i,j],CL[i,j]
            if np.isnan(cc): p["bars"]+=1; continue
            if not np.isnan(o) and o<=p["stop"]: close(j,i,o,"stop(gap)"); continue
            if ll<=p["stop"]: close(j,i,p["stop"],"stop"); continue
            p["hi"]=max(p["hi"],cc)
            if cc>=p["entry"]+C.BREAKEVEN_AT_R*p["r0"]:
                p["stop"]=max(p["stop"],p["entry"],p["hi"]-C.TRAIL_ATR_MULT*p["atr0"])
            if not gtoday:
                if kill=="exit": close(j,i,cc,"regime kill"); continue
                if kill=="be": p["stop"]=max(p["stop"],p["entry"])
            sc=SC[i,j]
            if not np.isnan(sc) and sc<C.EXIT_SCORE: close(j,i,cc,"score decay"); continue
            p["bars"]+=1
            if p["bars"]>=C.TIME_STOP_BARS: close(j,i,cc,"time stop"); continue
        if i>0 and lbl[i-1]=="green" and len(pos)<C.MAX_POSITIONS:
            elig=(SC[i-1]>=C.BUY_SCORE)&TB[i-1]&SECTOP[i-1]
            cand=[j for j in np.where(elig)[0] if j not in pos and not np.isnan(O[i,j])]
            cand.sort(key=lambda j:-SC[i-1,j])
            teq=cash+sum(p["qty"]*(CL[i-1,jj] if not np.isnan(CL[i-1,jj]) else p["entry"]) for jj,p in pos.items())
            scount={}
            for jj,p in pos.items():
                s=sec_of.get(tickers[jj],"?"); scount[s]=scount.get(s,0)+1
            for j in cand:
                if len(pos)>=C.MAX_POSITIONS: break
                s=sec_of.get(tickers[j],"?")
                if scount.get(s,0)>=C.MAX_PER_SECTOR: continue
                atr0=ATR[i-1,j]
                if np.isnan(atr0) or atr0<=0: continue
                r0=C.STOP_ATR_MULT*atr0
                qty=int((teq*C.RISK_PER_TRADE)//r0)
                entry=O[i,j]*(1+cost)
                if qty*entry>cash: qty=int(cash//entry)
                if qty<1: continue
                cash-=qty*entry
                pos[j]={"entry":entry,"stop":entry-r0,"r0":r0,"atr0":atr0,"qty":qty,"hi":entry,"bars":0,"i_in":i}
                scount[s]=scount.get(s,0)+1
        eq.append(cash+sum(p["qty"]*(CL[i,jj] if not np.isnan(CL[i,jj]) else p["entry"]) for jj,p in pos.items()))
    for j in list(pos):
        cc=CL[b-1,j]; close(j,b-1,cc if not np.isnan(cc) else pos[j]["entry"],"eot")
    tr=pd.DataFrame(trades); e=pd.Series(eq,index=dates[a:b])
    m=metrics(tr,e) if len(tr) else {"trades":0,"total_return_pct":round((e.iloc[-1]/e.iloc[0]-1)*100,1)}
    return (m,tr,e) if ret_trades else m
