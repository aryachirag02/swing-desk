# Research notes — v2 tuning (Jul 2026, real Nifty 500 data)

Data: 500 Nifty 500 stocks + ^NSEI, 2024-07-08 → 2026-07-08 (real Yahoo Finance EOD).
Split: train 2024-10-22 → 2026-01-01 (298 days) · validation 2026-01-02 → 2026-07-08 (128 days).
All selection decisions were made on the **train window only**; validation was then run once
per pre-registered hypothesis. Multiplicity disclosed below.

## Diagnosis of the v1 losses (baseline: PF 0.84 train / 0.46 validation)

1. **Stops too tight.** Trades stopped in 1–10 bars averaged −0.9R / −0.7R; trades that
   survived 20+ bars were strongly positive in *both* windows. An event study confirmed the
   mechanism: after a valid signal, the **median path dips first, then rallies** (median 10–20d
   forward return negative, 30d positive). A 2×ATR stop with breakeven-at-+1R was harvesting
   the dip and cutting the rally.
2. **Yellow-regime entries bled** (−0.39R on train vs +0.11R green). The edge only exists in
   confirmed uptrends.
3. **Pullback trigger was negative-expectancy in every configuration tested** (96/96 configs).
   Breakout entries carried all the edge.

## Adopted config (v2) — selected on train, verified end-to-end

breakout-only trigger · green-regime-only entries · stop 2.5×ATR · trail 4.0×ATR after +1R ·
time-stop 60 bars · buy score ≥ 70.

| Window | Trades | Win % | PF | Expectancy | Return | Max DD |
|---|---|---|---|---|---|---|
| Train | 65 | 41.5 | 1.32 | +0.25R | **+7.7%** | −12.9% |
| Train (25bps costs each way) | 65 | 36.9 | 1.35 | +0.13R | **+8.1%** | −13.4% |
| Validation | 18 | 22.2 | 0.29 | −0.23R | **−8.1%** | −10.0% |

The train result sits on a smooth parameter plateau (neighbouring configs +0.10 to +0.25R),
not a lone spike, and survives transaction costs.

## Why validation is still negative — and why we did not "fix" it

The validation window is a **−8% Nifty correction with only 9 green-regime days** (vs 142 in
train). The system's 18 trades all clustered at the Jan/Feb 2026 tops. Four independent,
train-first hypotheses were tested to profit in that window; all were rejected honestly:

1. Structural retune (adopted above) — train ✅, validation still negative.
2. Breadth-qualified regime (participation gate) — **failed on train**, never taken to validation.
3. Recovery-phase entries (above 50DMA / below 200DMA) — **failed on train**.
4. Narrow-rally veto (green + weak breadth) — validation's green days had *healthy* breadth
   (51–56%), so the veto wouldn't have blocked those entries, and it degrades train.

The stock-selection signal itself retained edge in validation (breakout signals showed +4.5%
30-day alpha vs Nifty, 61.5% hit rate) — but in a falling tape, positive *alpha* was still
negative *absolute* return for a long-only book. Any parameter set that shows a profit on this
specific window would have to be selected *using* the window, i.e. curve-fit, and would carry
no forward meaning. The correct behaviour of a long-only momentum system in H1 2026 was to
stand aside — which v2 mostly does (it is in cash for the bulk of the window; max DD −10%
vs −14% for v1, on a quarter of the trades).

## Honest multiplicity disclosure

Validation was observed ~4 times during this research (baseline, pre-registered v2-candidate,
a 16-config plateau diagnostic, and the final adopted config). Validation numbers above should
therefore be read as *lightly contaminated*, not pure out-of-sample. The true out-of-sample
test starts now: paper-trade v2 forward before risking capital.

## If you want profitability across corrections (future work — new capabilities, not tuning)

- Park idle cash in a liquid fund (~6–6.5% p.a.) — v2 is in cash most of a correction.
- Index hedge or shorts to monetise negative regimes (currently long-only).
- Faster regime exit (e.g. weekly close below 20DMA) to cut the top-clustering losses.
- Re-run `python backtest.py --tune` monthly; the overfit guard stays in charge.

---

# Short-side research (Jul 2026) — verdict: NO-GO, and why

Goal: add an F&O short leg to profit in falling markets. Every honest test failed.

## What was tested (selection on train windows only)

| Idea | Sample | Result |
|---|---|---|
| Short Nifty futures on red-regime days | 2y | −0.3%/trade avg, both windows |
| Short Nifty futures, 32 rule combos (4 entries × stops × covers) | **10y incl. 2020 crash** | best combo: +1.1% TOTAL over 8 years (21 trades) — noise |
| Short F&O stocks on 20d-low breakdown + volume (score<40/50) | 2y train | −1% to −2% per trade — stocks *bounced* after breakdowns |
| Short F&O stocks on failed rally into falling 20EMA | 2y train | negative at every horizon |
| Short F&O stocks on weak 3-month relative strength | 2y train | −1% to −5% per trade |

## Why shorting fails here

1. **Trend confirmation arrives after the fall.** By the time the regime turns red, the damage
   is done — in March 2020 the red light came on near the bottom, and the V-recovery stopped
   out every short.
2. **Indian dips mean-revert violently.** High-volume breakdowns marked capitulation lows;
   the average breakdown stock was *higher* 10–30 days later, even inside corrections.
3. Even a decade with a −38% crash produced no harvestable trend-short edge at EOD frequency.

Shipping a short module against this evidence would manufacture false confidence.
`shorts_research.py` documents the studies; `data/fo_list.csv` and `data/nifty_10y.csv` are
kept so the work is reproducible/extendable.

## What was adopted instead: cash yield (the honest bear-market profit)

v2 is deliberately in cash during non-green regimes. That cash now earns a liquid-fund yield
(`CASH_YIELD_PA = 6.5%` p.a., accrued daily in the backtest — park real capital in liquid
ETFs/funds to match). Updated results:

| Window | Trades | PF | Return | Annualized | Max DD |
|---|---|---|---|---|---|
| Train | 65 | 1.53 | **+14.4%** | +12.1% | −11.2% |
| Validation (−8% Nifty) | 17 | 0.29 | **−5.9%** | −11.3% | −9.5% |

Validation remains negative — the Jan/Feb'26 green-day entries at the top cost ~9% and yield
recovers ~3% of it. No honest configuration made this window positive. The realistic path to
improving bear-market results is a faster exit/slower entry around regime *tops*, tested on
longer history — future work.

---

# v3 — the "bull-trap filter" (faster regime off-switch), Jul 2026

Motivation: v2's validation losses came from green-day entries clustered at the Jan/Feb 2026
market top. Question: can the regime light turn off faster near tops without whipsawing?

## Method (selection independent of the 2y stock data)

Six regime definitions were raced on **10 years of Nifty index data** (hold index when "on",
liquid-fund cash when "off"), selected on 2016–2023 (includes the 2020 crash), validated once
on 2024–2026:

- Winner **R2 = price > 50DMA & > 200DMA & 50DMA rising (10-day slope)** — improved CAGR
  (9.0% vs 8.7%), max DD (−14.1% vs −15.8%), Sharpe (1.09 vs 1.03) and cut switches (99 vs 125)
  on the training decade; on 2024–26 validation: CAGR 8.0% vs 4.9%, Sharpe 0.94 vs 0.64.
- Fast off-switches based on the 20EMA whipsawed and were rejected on train.
- Rationale: when price pops back above its averages while the 50DMA is still *falling*, it is
  statistically a bear-market rally (bull trap), not a new uptrend. R2 blocked all 5 of the
  Feb 2026 trap days; nothing can block the first days of a genuine top (early Jan).

A position "kill switch" on regime loss (exit-all / stops-to-breakeven) was also tested on the
2y stock train window — both variants degraded results and were rejected.

## Results (full system, official backtest path, incl. 6.5% cash yield)

| Window | v2+yield | **v3 (R2 filter)** |
|---|---|---|
| Train return | +14.4% (PF 1.53, 65 trades, DD −11.2%) | **+29.6% (PF 3.92, 46 trades, DD −3.6%)** |
| Validation return | −5.9% (17 trades) | **−1.1% (7 trades, DD −6.0%)** |

Progression on the −8% validation window: v1 −11.3% → v2 −8.1% → +yield −5.9% → **v3 −1.1%**.

## Caveats (read before trading)

- 46 train trades is a small sample; PF 3.92 will not persist at that level. The filter's
  credibility rests on the independent 10-year index study, not on the stock backtest alone.
- The validation window has been observed repeatedly across this research programme; treat all
  validation numbers as contaminated. **Paper-trade v3 forward before risking capital.**
- Validation remains slightly negative: five 1R losses from the first days of January 2026 —
  the irreducible cost of trend-following through a top.
