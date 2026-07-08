# Swing Desk — NSE Nifty 500 swing-signal system

End-of-day swing-trading signals (4–6 week horizon) with a self-contained HTML dashboard,
a 2-year backtester with an overfit guard, and a daily brief.

**Universe:** Nifty 500 — which by construction already contains the entire
Nifty Midcap 150 and Smallcap 250 (Nifty 500 = Nifty 100 + Midcap 150 + Smallcap 250).
Every stock is tagged **Large / Mid / Small** from the official index lists, and the
dashboard has a size filter so you can trade just the segment you want.

> Not financial advice — a decision-support tool. You own every trade.

## Quick start (local machine)

```bash
pip install -r requirements.txt
python fetch_data.py          # pulls 2 years of Nifty 500 EOD data from Yahoo Finance
python backtest.py --tune     # 70/30 tune + validate; adopts better params only if they pass
python run_daily.py           # writes dashboard.html + brief.md
```

Open `dashboard.html` in any browser. No server needed — your trade log lives in the
browser (localStorage) with Export/Import JSON backup buttons.

Daily after market close (~7 pm IST): `python run_daily.py --fetch`

## Running inside Claude

The Claude sandbox blocks Yahoo Finance by default. To let Claude fetch real data,
add these to **Settings → Capabilities → network allowed domains**:

- `query1.finance.yahoo.com`
- `query2.finance.yahoo.com`
- `fc.yahoo.com`
- `nsearchives.nseindia.com` (optional — official Nifty 500 constituents list)

Without network access the system now **stops with an error** instead of generating sample data — it runs on real data only.

## Files

| File | What it does |
|---|---|
| `config.py` | Every rule and threshold in one place (auto-overridden by `params_tuned.json`) |
| `fetch_data.py` | Nifty 500 list + 2y OHLCV from Yahoo → `data/prices.csv`, `data/meta.csv` |
| `engine.py` | Indicators, 0–100 composite score, states, regime light, sector strength |
| `backtest.py` | Event-driven backtest, 70/30 tune-validate grid, overfit guard |
| `generate_dashboard.py` | Injects latest snapshot + backtest into `template.html` → `dashboard.html` |
| `run_daily.py` | One-command daily: (fetch) → dashboard → `brief.md` |

## The rules (v3 — tuned on 2y stock + 10y index data, see RESEARCH_NOTES.md)

- **Score (0–100):** Trend 25 · Momentum 25 · Relative strength 30 (incl. sector-leader bonus) · Volume 10 · Volatility sanity 10
- **States:** Strong Buy ≥80 + trigger · Buy ≥70 + trigger · Watchlist ≥60 · Exit <40 (held) · Reduce <50 (held)
- **Trigger:** 20-day-high breakout on ≥1.4× volume (pullback entries tested negative — disabled, re-enable via `TRIGGER_MODE`)
- **Risk:** 1% of capital per trade · stop = entry − 2.5×ATR · breakeven at +1R, then trail 4×ATR · time-stop 60 bars
- **Portfolio:** max 10 positions · max 3 per sector · top-4 sectors only · min ₹10 cr daily turnover · regime light gates entries (🟢 full / 🟡 none / 🔴 none) — green needs price > 50 & 200DMA **and a rising 50DMA** (bull-trap filter) · idle cash modelled at 6.5% p.a. liquid-fund yield
- **Market internals:** breadth (% of universe above 50-DMA + advance/decline) computed from our own data every run; narrow-rally caution when the index is green but participation is weak
- **Safety flags:** ASM/GSM surveillance stocks are hard-blocked from Buy states · 📅 flag when results fall inside the next 30 days · trade log warns on sector-cap / position-cap breaches

## Extra data feeds (light up automatically when their file exists)

| File | Feeds | How it fills |
|---|---|---|
| `data/flows.csv` | FII/DII header strip + selling-streak warning | `fetch_data.py` pulls from NSE (allow `www.nseindia.com`), or drop the CSV manually: `date,fii_net_cr,dii_net_cr` |
| `data/asm_gsm.csv` | Surveillance flags + Buy-state block | `fetch_data.py` pulls ASM/GSM lists from NSE, or manual: `ticker,list` |
| `data/earnings.csv` | 📅 results-due flags on rows, brief, and trade log | `python fetch_data.py --earnings` (slow — run weekly), or manual: `ticker,next_earnings` |

## Updating the system

Re-run `python backtest.py --tune` monthly. It tunes on the first 70% of history and
only adopts new parameters if they also work on the untouched last 30%
(min 8 trades, profit factor ≥ 1.1). Change one rule at a time; keep the trade log honest.
