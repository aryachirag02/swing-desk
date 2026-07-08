import itertools, pandas as pd, numpy as np
import config as C
from research import load_B, simulate2
from backtest import metrics
B=load_B(); nD=len(B["dates"]); i0=C.RS_LONG+10; i_split=i0+int((nD-i0)*0.7)
rows=[]
grid=list(itertools.product(["both","pullback","breakout"],[False,True],
                            [2.0,2.5,3.0,3.5],[2.5,3.0,3.5],[30,45],[70,75]))
for k,(tg,go,sm,tm,ts,bt) in enumerate(grid):
    tr,eq=simulate2(B,i0,i_split,buy_thr=bt,stop_mult=sm,trail_mult=tm,time_stop=ts,trig=tg,green_only=go)
    m=metrics(tr,eq)
    rows.append({"trig":tg,"green_only":go,"stop":sm,"trail":tm,"tstop":ts,"buy":bt,**m})
    if (k+1)%48==0: print(f"{k+1}/{len(grid)}",flush=True)
df=pd.DataFrame(rows)
df.to_csv("grid_train_results.csv",index=False)
ok=df[df.trades>=25].sort_values(["expectancy_R","profit_factor"],ascending=False)
print("\nTOP 15 ON TRAIN (n>=25):")
cols=["trig","green_only","stop","trail","tstop","buy","trades","win_rate","profit_factor","expectancy_R","total_return_pct","max_drawdown_pct"]
print(ok[cols].head(15).to_string(index=False))
print("\nBy structural family (mean expectancy):")
print(df[df.trades>=25].groupby(["trig","green_only"])["expectancy_R"].agg(["mean","max","count"]).round(3))
