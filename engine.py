"""Indicator + scoring engine. Everything downstream (dashboard, backtest, daily brief) uses this."""
import os

import numpy as np
import pandas as pd
import config as C


# ---------------- low-level indicators ----------------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(close, n=C.RSI_LEN):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)

def atr(df, n=C.ATR_LEN):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


# ---------------- per-stock indicator table ----------------
def compute_indicators(df, bench_close):
    """df: one ticker's OHLCV indexed by date. bench_close: benchmark close aligned to same dates."""
    out = df.copy()
    c = out["close"]
    out["ema_f"] = ema(c, C.EMA_FAST)
    out["ema_s"] = ema(c, C.EMA_SLOW)
    out["rsi"] = rsi(c)
    macd_line = ema(c, C.MACD_FAST) - ema(c, C.MACD_SLOW)
    out["macd_hist"] = macd_line - ema(macd_line, C.MACD_SIG)
    out["atr"] = atr(out)
    out["atr_pct"] = out["atr"] / c * 100

    b = bench_close.reindex(out.index).ffill()
    out["rs_1m"] = (c.pct_change(C.RS_SHORT) - b.pct_change(C.RS_SHORT)) * 100
    out["rs_3m"] = (c.pct_change(C.RS_LONG) - b.pct_change(C.RS_LONG)) * 100

    out["vol_ratio"] = out["volume"] / out["volume"].rolling(C.VOL_AVG_LEN).mean()
    out["high20"] = out["high"].rolling(C.BREAKOUT_LOOKBACK).max().shift(1)
    out["turnover_cr"] = (c * out["volume"]).rolling(C.VOL_AVG_LEN).mean() / 1e7

    slope_ok = out["ema_s"].diff(10) > 0
    up = (c > out["ema_s"]) & (out["ema_f"] > out["ema_s"]) & slope_ok
    down = (c < out["ema_s"]) & (out["ema_f"] < out["ema_s"])
    out["trend"] = np.select([up, down], [2, 0], default=1)  # 2 up, 1 sideways, 0 down

    # entry triggers
    out["trig_breakout"] = (c > out["high20"]) & (out["vol_ratio"] >= 1.4)
    near_ema = (out["low"] <= out["ema_f"] * 1.01).rolling(3).max().astype(bool)
    out["trig_pullback"] = (out["trend"] == 2) & near_ema & (c > out["ema_f"]) & (c > c.shift(1))
    mode = getattr(C, "TRIGGER_MODE", "both")
    out["trigger"] = (out["trig_breakout"] if mode == "breakout"
                      else out["trig_pullback"] if mode == "pullback"
                      else out["trig_breakout"] | out["trig_pullback"])
    return out


# ---------------- composite score (vectorized; one source of truth) ----------------
def score_frame(ind, sector_top):
    """Composite 0-100 score for a full indicator frame.
    ind: output of compute_indicators. sector_top: bool Series aligned to ind.index
    (is this stock's sector in the top-N strongest sectors on that day)."""
    # Trend (25)
    s = np.select([ind["trend"] == 2, ind["trend"] == 1], [C.W_TREND, C.W_TREND * 0.45], 0.0)
    # Momentum (25): RSI sweet spot + MACD state
    rv = ind["rsi"]
    s = s + np.select([(rv >= 55) & (rv <= 70), (rv >= 50) & (rv < 55),
                       (rv > 70) & (rv <= 78), (rv >= 45) & (rv < 50)], [13, 9, 7, 4], 0)
    mh = ind["macd_hist"]; rising = mh.diff() > 0
    s = s + np.select([(mh > 0) & rising, (mh > 0), rising], [12, 8, 4], 0)
    # Relative strength (30): vs Nifty 1M + 3M, bonus for a leading sector
    r1, r3 = ind["rs_1m"], ind["rs_3m"]
    s = s + np.select([r1 > 5, r1 > 0, r1 > -3], [12, 8, 3], 0)
    s = s + np.select([r3 > 8, r3 > 0], [12, 8], 0)
    s = s + np.where(sector_top.reindex(ind.index).fillna(False).to_numpy(), 6, 0)
    # Volume (10): confirmation on up days
    vr = ind["vol_ratio"]; upday = ind["close"] > ind["close"].shift(1)
    s = s + np.select([(vr >= 1.5) & upday, vr >= 1.2, vr >= 0.8], [10, 6, 3], 0)
    # Volatility sanity (10): tradable, not wild
    ap = ind["atr_pct"]
    s = s + np.select([ap <= 3.5, ap <= 5, ap <= 7], [10, 6, 3], 0)
    return pd.Series(np.minimum(s, 100), index=ind.index).round(1)


# ---------------- friendly labels ----------------
def labels(r):
    return {
        "trend_label": {2: "Up ↑", 1: "Sideways →", 0: "Down ↓"}[int(r["trend"])],
        "rsi_label": ("Overheated" if r["rsi"] > 70 else "Strong" if r["rsi"] >= 55
                      else "Neutral" if r["rsi"] >= 45 else "Weak"),
        "vs_market": ("Beating" if r["rs_1m"] > 2 else "Matching" if r["rs_1m"] >= -2 else "Lagging"),
        "volume_label": ("Surge" if r["vol_ratio"] >= 1.5 else "Active" if r["vol_ratio"] >= 1.1
                         else "Normal" if r["vol_ratio"] >= 0.7 else "Dry"),
        "trigger_label": (f"Breakout — new {C.BREAKOUT_LOOKBACK}-day high on {float(r['vol_ratio']):.1f}× volume"
                          if r.get("trig_breakout")
                          else f"Pullback bounce — held the rising {C.EMA_FAST} EMA"
                          if r.get("trig_pullback") else ""),
    }


def state_for(score, trigger, liquid=True):
    """Market-side state for a stock we do NOT hold. (Held stocks -> Hold/Reduce/Exit in backtest/log.)"""
    if not liquid: return "—"
    if score >= C.STRONG_BUY_SCORE and trigger: return "Strong Buy"
    if score >= C.BUY_SCORE and trigger: return "Buy"
    if score >= C.WATCHLIST_SCORE: return "Watchlist"
    return "—"


# ---------------- market regime & sectors ----------------
def market_breadth(px_stocks):
    """Advance/decline today + % of the universe above its own 50-DMA (broad vs narrow rally)."""
    ma50 = px_stocks.rolling(50).mean()
    last, prev = px_stocks.iloc[-1], px_stocks.iloc[-2]
    valid = last.notna() & prev.notna()
    adv = int((last[valid] > prev[valid]).sum())
    dec = int((last[valid] < prev[valid]).sum())
    pct50 = round(float((last[valid] > ma50.iloc[-1][valid]).mean() * 100), 1)
    label = ("Broad participation" if pct50 >= 60 else
             "Selective" if pct50 >= 40 else "Narrow / weak")
    return {"advancers": adv, "decliners": dec, "ad_ratio": round(adv / max(dec, 1), 2),
            "pct_above_50dma": pct50, "label": label}


def load_extras(asof=None):
    """Optional data files -> earnings flags, ASM/GSM surveillance list, FII/DII flows.
    Each is graceful: feature simply stays dark until its CSV exists."""
    ex = {"earnings": {}, "surveillance": {}, "flows": None}
    if os.path.exists(C.EARNINGS_FILE):
        df = pd.read_csv(C.EARNINGS_FILE)
        ex["earnings"] = dict(zip(df["ticker"], df["next_earnings"].astype(str)))
    if os.path.exists(C.SURVEILLANCE_FILE):
        df = pd.read_csv(C.SURVEILLANCE_FILE)
        ex["surveillance"] = dict(zip(df["ticker"], df["list"].astype(str)))
    if os.path.exists(C.FLOWS_FILE):
        df = pd.read_csv(C.FLOWS_FILE).sort_values("date")
        if len(df):
            last = df.iloc[-1]
            fii = df["fii_net_cr"].tolist()
            streak, sign = 0, fii[-1] < 0
            for v in reversed(fii):
                if v != 0 and (v < 0) == sign: streak += 1
                else: break
            ex["flows"] = {"date": str(last["date"]),
                           "fii_net_cr": round(float(last["fii_net_cr"])),
                           "dii_net_cr": round(float(last["dii_net_cr"])),
                           "fii_5d_cr": round(float(df["fii_net_cr"].tail(5).sum())),
                           "dii_5d_cr": round(float(df["dii_net_cr"].tail(5).sum())),
                           "fii_streak": streak, "fii_selling": bool(sign)}
    return ex


def market_regime(bench_close):
    ma50 = bench_close.rolling(50).mean()
    ma200 = bench_close.rolling(200).mean()
    c, m50, m200 = bench_close.iloc[-1], ma50.iloc[-1], ma200.iloc[-1]
    m50_rising = bench_close.rolling(50, min_periods=30).mean().diff(10).iloc[-1] > 0
    if c > m50 and c > m200 and m50_rising:
        light, advice = "green", "Full position size — trend supports new buys"
    elif c > m50 and c > m200:
        light, advice = "yellow", "No new buys — price above averages but 50DMA still falling (bull-trap filter)"
    elif c < m50 and c < m200: light, advice = "red", "No new buys — protect capital, manage exits"
    else: light, advice = "yellow", ("No new buys — mixed market (v2: yellow entries tested negative); manage holdings"
                                    if C.REGIME_RISK.get("yellow", 0) == 0 else
                                    "Half position size — mixed market, be selective")
    return {"light": light, "advice": advice, "nifty": round(float(c), 1),
            "ma50": round(float(m50), 1), "ma200": round(float(m200), 1),
            "chg_1m": round(float(bench_close.pct_change(21).iloc[-1] * 100), 2)}

def regime_series(bench_close):
    ma50 = bench_close.rolling(50).mean(); ma200 = bench_close.rolling(200).mean()
    g = (bench_close > ma50) & (bench_close > ma200)
    r = (bench_close < ma50) & (bench_close < ma200)
    return pd.Series(np.select([g, r], ["green", "red"], default="yellow"), index=bench_close.index)

def sector_strength(prices_wide, meta, bench_close, asof=None):
    """Equal-weight sector composites from our own universe -> rank by blended 1M/3M RS vs Nifty."""
    px = prices_wide if asof is None else prices_wide.loc[:asof]
    b = bench_close.reindex(px.index).ffill()
    rows = []
    for sec, g in meta.groupby("sector"):
        cols = [t for t in g["ticker"] if t in px.columns]
        if not cols: continue
        comp = (px[cols] / px[cols].iloc[0]).mean(axis=1)
        r1 = comp.pct_change(C.RS_SHORT).iloc[-1] - b.pct_change(C.RS_SHORT).iloc[-1]
        r3 = comp.pct_change(C.RS_LONG).iloc[-1] - b.pct_change(C.RS_LONG).iloc[-1]
        rows.append({"sector": sec, "rs_1m": round(r1 * 100, 2), "rs_3m": round(r3 * 100, 2),
                     "blend": round((0.6 * r1 + 0.4 * r3) * 100, 2), "n": len(cols)})
    df = pd.DataFrame(rows).sort_values("blend", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    df["top"] = df["rank"] <= C.TOP_SECTORS
    return df


# ---------------- full-universe snapshot (for dashboard & daily brief) ----------------
def snapshot(prices_long, meta):
    """Latest-day view for every stock: indicators, labels, score, state, trade levels, sparkline."""
    px_close = prices_long.pivot(index="date", columns="ticker", values="close").sort_index()
    bench = px_close[C.BENCHMARK].dropna()
    stocks_wide = px_close.drop(columns=[C.BENCHMARK])
    sect = sector_strength(stocks_wide, meta, bench)
    top_secs = set(sect[sect["top"]]["sector"])
    regime = market_regime(bench)
    breadth = market_breadth(stocks_wide)
    extras = load_extras()
    asof_date = px_close.index[-1]

    rows = []
    for t, g in prices_long[prices_long["ticker"] != C.BENCHMARK].groupby("ticker"):
        g = g.sort_values("date").set_index("date")
        if len(g) < C.RS_LONG + 10: continue
        ind = compute_indicators(g, bench)
        m = meta[meta["ticker"] == t].iloc[0]
        cap = m.get("cap", "")
        cap = "" if pd.isna(cap) else str(cap)
        sec_top = pd.Series(m["sector"] in top_secs, index=ind.index)
        sc = float(score_frame(ind, sec_top).iloc[-1])
        r = ind.iloc[-1].copy()
        r["prev_close"] = ind["close"].iloc[-2]
        surv = extras["surveillance"].get(t, "")
        liquid = r["turnover_cr"] >= C.MIN_TURNOVER_CR
        st = state_for(sc, bool(r["trigger"]), liquid and not surv)  # surveillance list = never a Buy
        earn = extras["earnings"].get(t, "")
        earn_soon = False
        if earn:
            try:
                d = pd.Timestamp(earn)
                earn_soon = 0 <= (d - asof_date).days <= C.EARNINGS_WARN_DAYS
                earn = str(d.date())
            except Exception:
                earn, earn_soon = "", False
        lab = labels(r)
        entry = float(r["close"]); stop = entry - C.STOP_ATR_MULT * float(r["atr"])
        spark = ind["close"].iloc[-30:]
        rows.append({
            "ticker": t.replace(".NS", ""), "yahoo": t, "name": m["name"], "sector": m["sector"], "cap": cap,
            "close": round(entry, 1), "chg_1d": round((entry / float(r["prev_close"]) - 1) * 100, 2),
            "score": sc, "state": st, **lab,
            "rsi": round(float(r["rsi"]), 0), "rs_1m": round(float(r["rs_1m"]), 1),
            "atr": round(float(r["atr"]), 1), "atr_pct": round(float(r["atr_pct"]), 1),
            "entry": round(entry, 1), "stop": round(stop, 1),
            "target": round(entry + C.TARGET_R * (entry - stop), 1),
            "risk_per_share": round(entry - stop, 1),
            "turnover_cr": round(float(r["turnover_cr"]), 1), "liquid": bool(liquid),
            "surveillance": surv, "earnings": earn, "earnings_soon": bool(earn_soon),
            "spark": [round(x, 1) for x in (spark / spark.iloc[0] * 100).tolist()],
        })
    rows.sort(key=lambda x: -x["score"])
    return {"asof": str(px_close.index[-1].date()), "regime": regime, "breadth": breadth,
            "flows": extras["flows"], "sectors": sect.to_dict("records"), "rows": rows}


def load_data():
    prices = pd.read_csv(C.PRICES_FILE, parse_dates=["date"])
    meta = pd.read_csv(C.META_FILE)
    return prices, meta


# ---------------- index snapshot (Indices tab) ----------------
def index_snapshot(path=os.path.join(C.DATA_DIR, "indices.csv")):
    """Per-index dashboard rows from real Yahoo index data. Returns [] if file absent."""
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, parse_dates=["date"])
    rows = []
    for (sym, name), g in df.groupby(["ticker", "name"], sort=False):
        g = g.sort_values("date")
        c = g["close"]
        if len(c) < 60:
            continue
        ma50 = c.rolling(50).mean(); ma200 = c.rolling(200).mean()
        slope_up = ma50.diff(10).iloc[-1] > 0 if len(c) >= 60 else False
        last = float(c.iloc[-1])
        r = rsi(c).iloc[-1]
        hi52 = float(c.tail(252).max()); lo52 = float(c.tail(252).min())
        up = last > ma50.iloc[-1] and (len(c) < 200 or last > ma200.iloc[-1]) and slope_up
        dn = last < ma50.iloc[-1] and (len(c) >= 200 and last < ma200.iloc[-1])
        pct = lambda n: round((last / float(c.iloc[-n-1]) - 1) * 100, 1) if len(c) > n else None
        rows.append({
            "ticker": sym, "name": name, "close": round(last, 1),
            "chg_1d": pct(1), "chg_1w": pct(5), "chg_1m": pct(21), "chg_3m": pct(63),
            "vs_50dma": round((last / float(ma50.iloc[-1]) - 1) * 100, 1),
            "vs_200dma": round((last / float(ma200.iloc[-1]) - 1) * 100, 1) if len(c) >= 200 else None,
            "rsi": round(float(r), 0),
            "from_52w_high": round((last / hi52 - 1) * 100, 1),
            "trend_label": "Up ↑" if up else "Down ↓" if dn else "Sideways →",
        })
        if sym in ("^NSEI", "^NSEBANK"):
            delta = c.diff(); u = delta.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
            dwn = (-delta.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
            rsi2 = float((100 - 100/(1 + u/dwn.replace(0, np.nan))).iloc[-1])
            above200 = len(c) >= 200 and last > float(ma200.iloc[-1])
            rows[-1]["rsi2"] = round(rsi2, 0)
            rows[-1]["fno_dip"] = ("BUY-DIP setup (RSI2<10, above 200DMA)" if (above200 and rsi2 < 10)
                                   else "in-dip: exit when RSI2>70" if (above200 and rsi2 < 70) and False
                                   else "no setup" if above200 else "below 200DMA — stand aside")
    order = {s: i for i, s in enumerate(["^NSEI", "^NSEBANK", "NIFTY_FIN_SERVICE.NS", "^NSEMDCP50",
                                          "NIFTY_MIDCAP_100.NS"])}
    rows.sort(key=lambda r: (order.get(r["ticker"], 99), -(r["chg_1m"] or -999)))
    return rows


# ---------------- microcap watch-only snapshot ----------------
def microcap_snapshot(px_path=os.path.join(C.DATA_DIR, "mc_prices.csv"),
                      meta_path=os.path.join(C.DATA_DIR, "mc_meta.csv")):
    """Watch-only rows for the Microcap tab. NO validated edge (MICROCAP_RESEARCH.md):
    flags are setups for human research, never trade signals."""
    if not (os.path.exists(px_path) and os.path.exists(meta_path)):
        return []
    px = pd.read_csv(px_path, parse_dates=["date"])
    meta = pd.read_csv(meta_path)
    bench = pd.read_csv(C.PRICES_FILE, parse_dates=["date"])
    bench = bench[bench.ticker == C.BENCHMARK].set_index("date")["close"]
    rows = []
    for t, g in px.groupby("ticker"):
        g = g.sort_values("date").set_index("date")
        if len(g) < 60: continue
        c = g["close"]; last = float(c.iloc[-1])
        ma50 = c.rolling(50, min_periods=30).mean()
        e20 = c.ewm(span=20, adjust=False).mean()
        hi100 = g["high"].rolling(100).max().shift(1)
        vr = g["volume"] / g["volume"].rolling(20).mean()
        b = bench.reindex(g.index).ffill()
        rs3 = (c.pct_change(63).iloc[-1] - b.pct_change(63).iloc[-1]) * 100 if len(c) > 63 else np.nan
        turn = float((c * g["volume"] / 1e7).tail(20).mean())
        mrow = meta[meta.ticker == t]
        rows.append({
            "ticker": t.replace(".NS", ""),
            "name": (mrow["name"].iloc[0] if len(mrow) else t)[:34],
            "sector": mrow["sector"].iloc[0] if len(mrow) else "?",
            "manual": bool(len(mrow) and mrow["cap"].iloc[0] == "Manual"),
            "close": round(last, 1),
            "chg_1m": round((last / float(c.iloc[-22]) - 1) * 100, 1) if len(c) > 22 else None,
            "rs_3m": round(float(rs3), 1) if rs3 == rs3 else None,
            "vs_50dma": round((last / float(ma50.iloc[-1]) - 1) * 100, 1) if ma50.iloc[-1] == ma50.iloc[-1] else None,
            "turnover_cr": round(turn, 1),
            "thin": turn < C.MIN_TURNOVER_CR,
            "setup_hi100": bool(len(g) > 101 and last > float(hi100.iloc[-1]) and float(vr.iloc[-1]) >= 1.5),
            "trend": "Up" if (last > ma50.iloc[-1] and last > e20.iloc[-1]) else
                     "Down" if (last < ma50.iloc[-1] and last < e20.iloc[-1]) else "Mixed",
        })
    rows.sort(key=lambda r: (not r["manual"], -(r["rs_3m"] if r["rs_3m"] is not None else -999)))
    return rows


# ---------------- radar: accumulation + fresh breakouts (both universes) ----------------
def radar_snapshot():
    """Early-stage scan across Nifty500 + Microcap250 + watchlist.
    ACCUMULATION = long tight base + volume quietly rising + RS turning up (pre-breakout footprint).
    BREAKOUT = fresh 100d-high on volume. Research flags, not signals."""
    accum, brk = [], []
    earn = {}
    try:
        _e = pd.read_csv(os.path.join(C.DATA_DIR, "earnings.csv"))
        tcol = "ticker" if "ticker" in _e.columns else _e.columns[0]
        dcol = [c0 for c0 in _e.columns if "date" in c0.lower() or "earn" in c0.lower()]
        dcol = dcol[0] if dcol else _e.columns[1]
        for _, r0 in _e.iterrows():
            earn[str(r0[tcol]).replace(".NS", "")] = str(r0[dcol])[:10]
    except Exception:
        pass
    bench = pd.read_csv(C.PRICES_FILE, parse_dates=["date"])
    bench = bench[bench.ticker == C.BENCHMARK].set_index("date")["close"]
    for pf, mf, uni in [(C.PRICES_FILE, C.META_FILE, "N500"),
                        (os.path.join(C.DATA_DIR, "mc_prices.csv"), os.path.join(C.DATA_DIR, "mc_meta.csv"), "Micro")]:
        if not os.path.exists(pf): continue
        px = pd.read_csv(pf, parse_dates=["date"])
        meta = pd.read_csv(mf).set_index("ticker")
        for t, g in px.groupby("ticker"):
            if t == C.BENCHMARK or len(g) < 130: continue
            g = g.sort_values("date").set_index("date")
            c = g.close
            turn = float((c * g.volume / 1e7).tail(20).mean())
            if turn < C.MIN_TURNOVER_CR: continue
            b = bench.reindex(g.index).ffill()
            rs_now = float((c.pct_change(63).iloc[-1] - b.pct_change(63).iloc[-1]) * 100)
            rs_prev = float((c.pct_change(63).iloc[-21] - b.pct_change(63).iloc[-21]) * 100) if len(c) > 85 else rs_now
            v20, v60 = float(g.volume.tail(20).mean()), float(g.volume.tail(60).mean())
            hi100 = float(g.high.rolling(100).max().shift(1).iloc[-1])
            vr = float(g.volume.iloc[-1] / max(1, g.volume.rolling(20).mean().iloc[-1]))
            last = float(c.iloc[-1])
            nm = str(meta.loc[t, "name"])[:30] if t in meta.index else t
            sec = str(meta.loc[t, "sector"]) if t in meta.index else "?"
            base = c.tail(60)
            tight = float(base.max() / base.min())
            row = {"ticker": t.replace(".NS", ""), "name": nm, "sector": sec, "uni": uni,
                   "close": round(last, 1), "rs_3m": round(rs_now, 0), "turnover_cr": round(turn, 0)}
            hi100s = g["high"].rolling(100).max().shift(1)
            v20s = g["volume"].rolling(20).mean()
            sigs = (c > hi100s) & (g["volume"] >= 1.5 * v20s) & (c.pct_change(63) > 0)
            fires = sigs[sigs].index
            in_window = False
            camp_days, camp_run, window_day, sig_price, fired_today = 0, 0.0, 0, None, False
            mom_sig, vr_sig = 0.0, 0.0
            if len(fires):
                first = fires[0]
                for _k in range(1, len(fires)):
                    if (fires[_k] - fires[_k-1]).days > 45: first = fires[_k]
                camp_days = int((g.index[-1] - first).days)
                camp_run = float(last / float(c.loc[first]) - 1) * 100
                last_fire = fires[-1]
                window_day = int(len(c) - 1 - g.index.get_loc(last_fire))
                sig_price = float(c.loc[first])
                fired_today = window_day == 0
                fi = g.index.get_loc(first)
                if fi > 63:
                    mom_sig = float(c.iloc[fi] / c.iloc[fi - 63] - 1) * 100
                    vr_sig = float(g["volume"].iloc[fi] / max(1, g["volume"].iloc[fi-20:fi].mean()))
                # active buy window: signal within 10 sessions AND not failed (>7% below campaign signal price)
                in_window = window_day <= 10 and last >= sig_price * 0.93
            if in_window:
                mom = mom_sig if mom_sig else rs_now
                vr_g = vr_sig if vr_sig else vr
                p_m = 0 if mom < 25 else 1 if mom < 60 else 2 if mom < 120 else 1
                p_v = 0 if vr_g < 2.5 else 1 if vr_g < 5 else 2
                sc = p_m + p_v
                grade = "A" if sc >= 3 else "B" if sc >= 1 else "C"
                why = (f"momentum {mom:+.0f}% + volume {vr:.1f}x — "
                       + {"A": "historically the strongest bucket (10y study)",
                          "B": "middle bucket historically",
                          "C": "weakest bucket historically"}[grade])
                ed = earn.get(row["ticker"])
                try:
                    soon = bool(ed) and 0 <= (pd.Timestamp(ed) - pd.Timestamp.now()).days <= 21
                except Exception:
                    soon = False
                # informational levels (context, NOT a grade input — backtested as non-predictive)
                _hist = g.iloc[max(0, len(g)-504):len(g)]
                _c = float(c.iloc[-1])
                _ceil = _hist["high"].values[(_hist["high"].values > _c) & (_hist["high"].values < _c*1.5)]
                _floor = _hist["low"].values[(_hist["low"].values < _c) & (_hist["low"].values > _c*0.6)]
                headroom = round(float(np.percentile(_ceil, 20)/_c - 1)*100) if len(_ceil) >= 3 else None
                support_dist = round(float(1 - np.percentile(_floor, 80)/_c)*100) if len(_floor) >= 3 else None
                brk.append({**row, "vol_x": round(vr, 1), "grade": grade, "grade_why": why,
                            "camp_days": camp_days, "camp_run": round(camp_run), "window_day": window_day, "sig_price": round(sig_price or 0, 1), "fired_today": fired_today, "vol_sig": round(vr_sig, 1) if vr_sig else round(vr, 1), "headroom": headroom, "support_dist": support_dist,
                            "results": ed if soon else None})
            elif (tight <= 1.30 and v20 > v60 * 1.25 and rs_now > -5 and rs_now > rs_prev + 3
                  and last > hi100 * 0.85):
                accum.append({**row, "base_pct": round((tight - 1) * 100, 0),
                              "vol_trend": round(v20 / v60, 2)})
    accum.sort(key=lambda r: -r["vol_trend"])
    # fresh first (day 0-5 of campaign can never be crowded out), then grade, then momentum
    brk.sort(key=lambda r: (0 if (r.get("camp_days") is not None and r["camp_days"] <= 5) else 1,
                            {"A": 0, "B": 1, "C": 2}.get(r.get("grade"), 3), -r["rs_3m"]))
    return {"accum": accum[:25], "breakouts": brk[:30]}
