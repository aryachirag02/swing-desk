# Microcap 250 research — Jul 2026 (honest verdict: WATCH-ONLY, not signal-grade yet)

Goal: extend the system to the Nifty Microcap 250 (rank ~501-750, e.g. Orient Cement),
to capture names below the Nifty 500. Full v3 pipeline, real data, tune-on-train, validate once.

## Data
250 microcaps, 2 years (2024-07-08 to 2026-07-08), real Yahoo EOD. Benchmark ^NSEI.
Liquidity healthier than feared: median turnover Rs 24.8 cr/day, 240/250 clear the Rs 10 cr
floor. Volatility 43% ann (vs 39% smallcap, 35% Nifty500) — modestly higher, not extreme.
NOTE: Orient *Hotels* (the original example) is NOT in the Microcap 250 — it sits below even
this index (rank 750+). Only Orient *Cement* is here. Truly sub-microcap names remain untracked.

## What the backtest found

| Regime basis | Train | Validation |
|---|---|---|
| Nifty v3 regime (adopted) | +9.4% (PF 1.22, 47 trades) | -2.1% (8 trades, 3 green days) |
| Microcap-own regime (rejected) | **-10.4% (PF 0.60)** | +25.5% (PF 5.28) |

The microcap-own-regime's +25.5% validation is a **curve-fitting trap**: it LOSES on the
train window, so it fails our adoption rule. Adopting a rule that only works out-of-sample
would be selecting on the validation set — exactly what we refuse to do. Every microcap-own
regime variant (breadth filters included) lost on train and was rejected.

The honest winner is **v3 unchanged with the Nifty regime**: PF 1.22 on train, survives 30bps
costs (PF 1.25). But this is materially weaker than large-cap v3 (PF 3.92) — the microcap edge
is real but thin.

## Why validation is inconclusive (not a pass, not a clean fail)

The Nifty regime was green on only **3 of ~128 validation days** — H1 2026 was a correction and
the large-cap filter (correctly) kept the microcap book in cash almost the entire window. So the
8 validation trades are noise, not a verdict. We genuinely do not yet have out-of-sample proof
that microcap v3 works.

## Verdict: ship as WATCH-ONLY

- The Microcap 250 tab shows the full universe with real indicators (trend, RS, breakout,
  RSI, liquidity) and applies v3's scoring for context — but it is **labelled watch-only**:
  no capital should be committed on these signals until forward data proves the edge.
- Reason: (1) train edge is thin (PF 1.22), (2) validation is inconclusive (near-zero green
  days), (3) microcaps carry gap/ASM/liquidity risks a 2-year backtest understates.
- This is the same honesty bar as the short-side NO-GO: we don't dress up an unproven edge
  as tradable. Paper-track it; revisit after 3-6 months of live microcap signals + the next
  correction that actually produces microcap green days.

## Reproducibility
mc_research.py (cache build + baseline), mc_prices.csv / mc_meta.csv (real data),
mc_B.pkl (indicator cache). Same simulate4 engine as the main system.

---

# Trend-following variant (multi-bagger thesis) — Jul 2026: also WATCH-ONLY

Hypothesis (user): microcaps trend hard and produce multi-baggers; a trend system
(100d-high breakout, RS>0, wide 4xATR trail, exit on close<50DMA, no time stop) should catch them.

Train looked spectacular: 37 trades, 62% win, PF 4.60, +36.8%, one +20.8R winner (CUPID).
The honest decomposition killed it:
- ONE trade (CUPID +20.8R) = majority of all profit; next-best winner just +1.9R.
  Ex-CUPID, train expectancy ~+0.2R — noise.
- Validation: 10 trades, 0% win rate, -4.8%. Zero out-of-sample confirmation.

Conclusion: multi-baggers exist here (CUPID proves it) but a mechanical EOD system has NOT
demonstrated a repeatable ability to harvest them — 1 hit in 18 months, 0 in validation, and
the "edge" is a single lottery ticket. Signal-grade: NO. The Microcap tab ships watch-only,
showing 100d-high breakout + RS flags as SETUPS for human research, never as validated signals.
Manual watchlist (data/watchlist.txt) covers specific below-index names like ORIENTHOT.NS.
