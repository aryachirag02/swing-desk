"""Backtests the exact rules the dashboard shows, with no lookahead:
signal on day T close -> entry at day T+1 open. 70% of history = tuning window,
last 30% = untouched validation. `--tune` grid-searches BUY_SCORE / stop / trail on the
tuning window, then checks the winner on validation; params are adopted (written to
params_tuned.json, auto-loaded by config) ONLY if they also work on unseen data.

Run:  python backtest.py            # test current params
      python backtest.py --tune     # tune -> validate -> maybe adopt
"""
import argparse, itertools, json, os
import numpy as np
import pandas as pd
import config as C
import engine as E


# ---------------- data prep ----------------
def prepare(prices, meta):
    wide = {c: prices.pivot(index="date", columns="ticker", values=c).sort_index()
            for c in ["open", "high", "low", "close", "volume"]}
    bench = wide["close"][C.BENCHMARK].dropna()
    tickers = [t for t in wide["close"].columns if t != C.BENCHMARK]
    dates = wide["close"].index

    # daily sector leadership (top-N sectors by blended 1M/3M RS vs Nifty)
    px = wide["close"][tickers]
    comps = {}
    for sec, g in meta.groupby("sector"):
        cols = [t for t in g["ticker"] if t in px.columns]
        if cols:
            comps[sec] = (px[cols] / px[cols].iloc[0]).mean(axis=1)
    comp = pd.DataFrame(comps)
    b1, b3 = bench.pct_change(C.RS_SHORT), bench.pct_change(C.RS_LONG)
    blend = (0.6 * comp.pct_change(C.RS_SHORT).sub(b1, axis=0)
             + 0.4 * comp.pct_change(C.RS_LONG).sub(b3, axis=0))
    sec_rank = blend.rank(axis=1, ascending=False)
    sec_top = sec_rank <= C.TOP_SECTORS

    # regime risk multiplier per day (min_periods so the first year isn't all-NaN)
    ma50 = bench.rolling(50, min_periods=30).mean()
    ma200 = bench.rolling(200, min_periods=60).mean()
    slope_up = ma50.diff(10) > 0  # v3: green also needs a RISING 50DMA (bull-trap filter,
    # selected on 2016-2023 index data — see RESEARCH_NOTES.md)
    reg = pd.Series(np.select([(bench > ma50) & (bench > ma200) & slope_up,
                               (bench < ma50) & (bench < ma200)],
                              ["green", "red"], default="yellow"), index=bench.index)

    reg_mult = reg.map(C.REGIME_RISK).reindex(dates).ffill().fillna(0.5)

    sec_of = dict(zip(meta["ticker"], meta["sector"]))
    nT, nD = len(tickers), len(dates)
    SC = np.full((nD, nT), np.nan); TRIG = np.zeros((nD, nT), bool)
    ATR = np.full((nD, nT), np.nan); STOP_OK = np.zeros((nD, nT), bool)

    for j, t in enumerate(tickers):
        df = pd.DataFrame({c: wide[c][t] for c in ["open", "high", "low", "close", "volume"]}).dropna()
        if len(df) < C.RS_LONG + 10:
            continue
        ind = E.compute_indicators(df, bench)
        stop_series = sec_top[sec_of.get(t, "")] if sec_of.get(t, "") in sec_top.columns \
            else pd.Series(False, index=dates)
        sc = E.score_frame(ind, stop_series)
        SC[:, j] = sc.reindex(dates).to_numpy()
        liquid = ind["turnover_cr"] >= C.MIN_TURNOVER_CR
        TRIG[:, j] = (ind["trigger"] & liquid).reindex(dates).fillna(False).to_numpy()
        ATR[:, j] = ind["atr"].reindex(dates).to_numpy()
        STOP_OK[:, j] = stop_series.reindex(dates).fillna(False).to_numpy()

    arr = lambda c: wide[c][tickers].to_numpy(float)
    return {"tickers": tickers, "dates": dates, "sec_of": sec_of,
            "O": arr("open"), "H": arr("high"), "L": arr("low"), "CL": arr("close"),
            "SC": SC, "TRIG": TRIG, "ATR": ATR, "SECTOP": STOP_OK,
            "REG": reg_mult.to_numpy(), "REG_LABEL": reg.reindex(dates).ffill().to_numpy()}


# ---------------- simulation ----------------
def simulate(B, i0, i1, buy_thr=None, stop_mult=None, trail_mult=None):
    buy_thr = buy_thr or C.BUY_SCORE
    stop_mult = stop_mult or C.STOP_ATR_MULT
    trail_mult = trail_mult or C.TRAIL_ATR_MULT
    O, H, L, CL, SC, TRIG, ATR, SECTOP, REG = (B[k] for k in
        ["O", "H", "L", "CL", "SC", "TRIG", "ATR", "SECTOP", "REG"])
    dates, tickers, sec_of = B["dates"], B["tickers"], B["sec_of"]

    cash, pos, trades, eq_curve = float(C.STARTING_CAPITAL), {}, [], []

    def close_trade(j, i, price, reason):
        nonlocal cash
        p = pos.pop(j)
        cash += p["qty"] * price
        trades.append({"ticker": tickers[j], "sector": sec_of.get(tickers[j], "?"),
                       "entry_date": str(dates[p["i_in"]].date()), "exit_date": str(dates[i].date()),
                       "entry": round(p["entry"], 2), "exit": round(price, 2), "qty": p["qty"],
                       "bars": i - p["i_in"], "reason": reason, "regime": p["regime"],
                       "pnl": round(p["qty"] * (price - p["entry"]), 0),
                       "r_mult": round((price - p["entry"]) / p["r0"], 2)})

    daily_y = 1 + getattr(C, "CASH_YIELD_PA", 0.0) / 252
    for i in range(i0, i1):
        cash *= daily_y  # idle cash earns liquid-fund yield
        # ---- manage open positions on today's bar ----
        for j in list(pos):
            p = pos[j]
            o, h, l, c = O[i, j], H[i, j], L[i, j], CL[i, j]
            if np.isnan(c):
                p["bars_held"] += 1
                continue
            if not np.isnan(o) and o <= p["stop"]:
                close_trade(j, i, o, "stop (gap)"); continue
            if l <= p["stop"]:
                close_trade(j, i, p["stop"], "stop"); continue
            p["hi"] = max(p["hi"], c)
            if c >= p["entry"] + C.BREAKEVEN_AT_R * p["r0"]:
                p["stop"] = max(p["stop"], p["entry"], p["hi"] - trail_mult * p["atr0"])
            sc_now = SC[i, j]
            if not np.isnan(sc_now) and sc_now < C.EXIT_SCORE:
                close_trade(j, i, c, "score decay"); continue
            p["bars_held"] += 1
            if p["bars_held"] >= C.TIME_STOP_BARS:
                close_trade(j, i, c, "time stop"); continue

        # ---- new entries from yesterday's signals ----
        if i > 0 and REG[i - 1] > 0 and len(pos) < C.MAX_POSITIONS:
            elig = (SC[i - 1] >= buy_thr) & TRIG[i - 1] & SECTOP[i - 1]
            cand = [j for j in np.where(elig)[0] if j not in pos and not np.isnan(O[i, j])]
            cand.sort(key=lambda j: -SC[i - 1, j])
            total_eq = cash + sum(p["qty"] * (CL[i - 1, j] if not np.isnan(CL[i - 1, j]) else p["entry"])
                                  for j, p in pos.items())
            sec_count = {}
            for j, p in pos.items():
                s = sec_of.get(tickers[j], "?"); sec_count[s] = sec_count.get(s, 0) + 1
            for j in cand:
                if len(pos) >= C.MAX_POSITIONS: break
                s = sec_of.get(tickers[j], "?")
                if sec_count.get(s, 0) >= C.MAX_PER_SECTOR: continue
                atr0 = ATR[i - 1, j]
                if np.isnan(atr0) or atr0 <= 0: continue
                r0 = stop_mult * atr0
                qty = int((total_eq * C.RISK_PER_TRADE * REG[i - 1]) // r0)
                entry = O[i, j]
                if qty * entry > cash:
                    qty = int(cash // entry)
                if qty < 1: continue
                cash -= qty * entry
                pos[j] = {"entry": entry, "stop": entry - r0, "r0": r0, "atr0": atr0,
                          "qty": qty, "hi": entry, "bars_held": 0, "i_in": i,
                          "regime": B["REG_LABEL"][i - 1]}
                sec_count[s] = sec_count.get(s, 0) + 1

        mark = cash + sum(p["qty"] * (CL[i, j] if not np.isnan(CL[i, j]) else p["entry"])
                          for j, p in pos.items())
        eq_curve.append(mark)

    for j in list(pos):  # liquidate remainder for clean accounting
        c = CL[i1 - 1, j]
        close_trade(j, i1 - 1, c if not np.isnan(c) else pos[j]["entry"], "end of test")
    return pd.DataFrame(trades), pd.Series(eq_curve, index=dates[i0:i1])


# ---------------- metrics ----------------
def metrics(trades, equity):
    if trades.empty or equity.empty:
        return {"trades": 0}
    wins, losses = trades[trades["pnl"] > 0], trades[trades["pnl"] <= 0]
    gross_w, gross_l = wins["pnl"].sum(), -losses["pnl"].sum()
    dd = (equity / equity.cummax() - 1).min()
    yrs = len(equity) / 252
    return {"trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "avg_win": round(wins["pnl"].mean(), 0) if len(wins) else 0,
            "avg_loss": round(losses["pnl"].mean(), 0) if len(losses) else 0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else float("inf"),
            "expectancy_R": round(trades["r_mult"].mean(), 3),
            "avg_hold_days": round(trades["bars"].mean(), 1),
            "total_return_pct": round((equity.iloc[-1] / equity.iloc[0] - 1) * 100, 1),
            "annualized_pct": round(((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(yrs, 1e-9)) - 1) * 100, 1),
            "max_drawdown_pct": round(dd * 100, 1)}


def by_reason(trades):
    if trades.empty: return {}
    g = trades.groupby("reason")["r_mult"].agg(["count", "mean"]).round(2)
    return {k: {"n": int(v["count"]), "avg_R": float(v["mean"])} for k, v in g.iterrows()}


# ---------------- tune -> validate -> adopt ----------------
GRID = {"buy_thr": [70, 75, 80], "stop_mult": [2.0, 2.5, 3.0], "trail_mult": [3.0, 3.5, 4.0]}

def tune(B, i0, i_split):
    results = []
    for bt, sm, tm in itertools.product(GRID["buy_thr"], GRID["stop_mult"], GRID["trail_mult"]):
        tr, eq = simulate(B, i0, i_split, bt, sm, tm)
        m = metrics(tr, eq)
        if m["trades"] >= 15:  # don't trust params picked from a handful of trades
            results.append({"buy_thr": bt, "stop_mult": sm, "trail_mult": tm, **m})
    if not results:
        return None, []
    results.sort(key=lambda r: (r["expectancy_R"], r["profit_factor"]), reverse=True)
    return results[0], results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    args = ap.parse_args()

    prices, meta = E.load_data()
    B = prepare(prices, meta)
    nD = len(B["dates"])
    i0 = C.RS_LONG + 10                       # indicator warm-up
    i_split = i0 + int((nD - i0) * 0.7)       # 70% tune / 30% validate
    seg = {"train": (i0, i_split), "validate": (i_split, nD)}
    print(f"Days: {nD} | tuning window: {B['dates'][i0].date()} -> {B['dates'][i_split-1].date()}"
          f" | validation: {B['dates'][i_split].date()} -> {B['dates'][-1].date()}")

    report = {"windows": {k: [str(B['dates'][a].date()), str(B['dates'][b-1].date())]
                          for k, (a, b) in seg.items()},
              "params_used": {"BUY_SCORE": C.BUY_SCORE, "STOP_ATR_MULT": C.STOP_ATR_MULT,
                              "TRAIL_ATR_MULT": C.TRAIL_ATR_MULT}}

    for name, (a, b) in seg.items():
        tr, eq = simulate(B, a, b)
        report[name] = metrics(tr, eq)
        report[name + "_exit_breakdown"] = by_reason(tr)
        tr.to_csv(f"trades_{name}.csv", index=False)

    if args.tune:
        best, allres = tune(B, i0, i_split)
        if best:
            vt, ve = simulate(B, i_split, nD, best["buy_thr"], best["stop_mult"], best["trail_mult"])
            vm = metrics(vt, ve)
            report["tuning"] = {"best_on_train": best, "best_on_validation": vm,
                                "grid_size": len(allres)}
            adopted = vm.get("trades", 0) >= 8 and vm.get("profit_factor", 0) >= 1.1
            report["tuning"]["adopted"] = adopted
            if adopted:
                with open(C.TUNED_FILE, "w") as f:
                    json.dump({"BUY_SCORE": best["buy_thr"], "STOP_ATR_MULT": best["stop_mult"],
                               "TRAIL_ATR_MULT": best["trail_mult"]}, f, indent=2)
                print(f"ADOPTED tuned params (validated): {best['buy_thr']}/{best['stop_mult']}/{best['trail_mult']}")
            else:
                print("Tuned params did NOT hold up on validation -> keeping defaults (this is the overfit guard working)")

    with open("backtest_summary.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    lines = ["# Backtest report", ""]
    for name in ["train", "validate"]:
        m = report[name]
        lines += [f"## {name.title()} window ({report['windows'][name][0]} to {report['windows'][name][1]})",
                  "", *(f"- **{k.replace('_', ' ')}**: {v}" for k, v in m.items()), ""]
    if "tuning" in report:
        t = report["tuning"]
        lines += ["## Tuning", f"- Best params on tuning window: {t['best_on_train']}",
                  f"- Same params on validation: {t['best_on_validation']}",
                  f"- Adopted: {t['adopted']}", ""]
    with open("backtest_report.md", "w") as f:
        f.write("\n".join(lines))
    print(json.dumps({k: report[k] for k in ["train", "validate"]}, indent=2))


if __name__ == "__main__":
    main()
