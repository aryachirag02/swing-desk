"""Research harness: extended simulate with structural variants. Tunes on TRAIN only."""
import itertools, json, pickle, os, sys
import numpy as np, pandas as pd
import config as C, engine as E
from backtest import metrics

CACHE = "research_B.pkl"

def prepare_ext():
    prices, meta = E.load_data()
    wide = {c: prices.pivot(index="date", columns="ticker", values=c).sort_index()
            for c in ["open","high","low","close","volume"]}
    bench = wide["close"][C.BENCHMARK].dropna()
    tickers = [t for t in wide["close"].columns if t != C.BENCHMARK]
    dates = wide["close"].index
    px = wide["close"][tickers]
    comps = {}
    for sec, g in meta.groupby("sector"):
        cols=[t for t in g["ticker"] if t in px.columns]
        if cols: comps[sec]=(px[cols]/px[cols].iloc[0]).mean(axis=1)
    comp=pd.DataFrame(comps)
    b1,b3=bench.pct_change(C.RS_SHORT),bench.pct_change(C.RS_LONG)
    blend=(0.6*comp.pct_change(C.RS_SHORT).sub(b1,axis=0)+0.4*comp.pct_change(C.RS_LONG).sub(b3,axis=0))
    sec_top=blend.rank(axis=1,ascending=False)<=C.TOP_SECTORS
    ma50=bench.rolling(50,min_periods=30).mean(); ma200=bench.rolling(200,min_periods=60).mean()
    reg=pd.Series(np.select([(bench>ma50)&(bench>ma200),(bench<ma50)&(bench<ma200)],
                            ["green","red"],default="yellow"),index=bench.index)
    reg_lbl=reg.reindex(dates).ffill()
    sec_of=dict(zip(meta["ticker"],meta["sector"]))
    nT,nD=len(tickers),len(dates)
    SC=np.full((nD,nT),np.nan); TB=np.zeros((nD,nT),bool); TP=np.zeros((nD,nT),bool)
    ATR=np.full((nD,nT),np.nan); STOP_OK=np.zeros((nD,nT),bool)
    for j,t in enumerate(tickers):
        df=pd.DataFrame({c:wide[c][t] for c in ["open","high","low","close","volume"]}).dropna()
        if len(df)<C.RS_LONG+10: continue
        ind=E.compute_indicators(df,bench)
        st=sec_top[sec_of.get(t,"")] if sec_of.get(t,"") in sec_top.columns else pd.Series(False,index=dates)
        SC[:,j]=E.score_frame(ind,st).reindex(dates).to_numpy()
        liq=ind["turnover_cr"]>=C.MIN_TURNOVER_CR
        TB[:,j]=(ind["trig_breakout"]&liq).reindex(dates).fillna(False).to_numpy()
        TP[:,j]=(ind["trig_pullback"]&liq).reindex(dates).fillna(False).to_numpy()
        ATR[:,j]=ind["atr"].reindex(dates).to_numpy()
        STOP_OK[:,j]=st.reindex(dates).fillna(False).to_numpy()
    arr=lambda c: wide[c][tickers].to_numpy(float)
    B={"tickers":tickers,"dates":dates,"sec_of":sec_of,
       "O":arr("open"),"H":arr("high"),"L":arr("low"),"CL":arr("close"),
       "SC":SC,"TB":TB,"TP":TP,"ATR":ATR,"SECTOP":STOP_OK,
       "REG_LABEL":reg_lbl.to_numpy()}
    pickle.dump(B,open(CACHE,"wb")); print("cached",CACHE)
    return B

def load_B():
    if os.path.exists(CACHE): return pickle.load(open(CACHE,"rb"))
    return prepare_ext()

def simulate2(B,i0,i1,buy_thr=70,stop_mult=2.0,trail_mult=2.5,time_stop=30,
              trig="both",green_only=False,exit_score=C.EXIT_SCORE,cost_bps=0.0):
    O,H,L,CL,SC,TB,TP,ATR,SECTOP=(B[k] for k in ["O","H","L","CL","SC","TB","TP","ATR","SECTOP"])
    REGL=B["REG_LABEL"]; dates,tickers,sec_of=B["dates"],B["tickers"],B["sec_of"]
    reg_mult=np.where(REGL=="green",1.0,np.where(REGL=="red",0.0,0.0 if green_only else 0.5))
    TRIG={"both":TB|TP,"breakout":TB,"pullback":TP}[trig]
    cash,pos,trades,eq=float(C.STARTING_CAPITAL),{},[],[]
    cost=cost_bps/1e4
    def close_trade(j,i,price,reason):
        nonlocal cash
        p=pos.pop(j); px=price*(1-cost)
        cash+=p["qty"]*px
        trades.append({"ticker":tickers[j],"sector":sec_of.get(tickers[j],"?"),
            "entry_date":str(dates[p["i_in"]].date()),"exit_date":str(dates[i].date()),
            "entry":round(p["entry"],2),"exit":round(px,2),"qty":p["qty"],
            "bars":i-p["i_in"],"reason":reason,"regime":p["regime"],
            "pnl":round(p["qty"]*(px-p["entry"]),0),
            "r_mult":round((px-p["entry"])/p["r0"],2)})
    for i in range(i0,i1):
        for j in list(pos):
            p=pos[j]; o,h,l,c=O[i,j],H[i,j],L[i,j],CL[i,j]
            if np.isnan(c): p["bars_held"]+=1; continue
            if not np.isnan(o) and o<=p["stop"]: close_trade(j,i,o,"stop (gap)"); continue
            if l<=p["stop"]: close_trade(j,i,p["stop"],"stop"); continue
            p["hi"]=max(p["hi"],c)
            if c>=p["entry"]+C.BREAKEVEN_AT_R*p["r0"]:
                p["stop"]=max(p["stop"],p["entry"],p["hi"]-trail_mult*p["atr0"])
            sc=SC[i,j]
            if not np.isnan(sc) and sc<exit_score: close_trade(j,i,c,"score decay"); continue
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
                pos[j]={"entry":entry,"stop":entry-r0,"r0":r0,"atr0":atr0,"qty":qty,
                        "hi":entry,"bars_held":0,"i_in":i,"regime":REGL[i-1]}
                sec_count[s]=sec_count.get(s,0)+1
        eq.append(cash+sum(p["qty"]*(CL[i,jj] if not np.isnan(CL[i,jj]) else p["entry"]) for jj,p in pos.items()))
    for j in list(pos):
        c=CL[i1-1,j]; close_trade(j,i1-1,c if not np.isnan(c) else pos[j]["entry"],"end of test")
    return pd.DataFrame(trades),pd.Series(eq,index=dates[i0:i1])

if __name__=="__main__":
    B=load_B()
    nD=len(B["dates"]); i0=C.RS_LONG+10; i_split=i0+int((nD-i0)*0.7)
    # sanity: reproduce baseline
    tr,eq=simulate2(B,i0,i_split)
    print("baseline train:",metrics(tr,eq))
