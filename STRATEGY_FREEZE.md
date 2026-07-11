# v3 FREEZE — pre-live robustness audit (Jul 10, 2026)

Before going live, v3 was stress-tested four ways WITHOUT changing any parameter.
Purpose: confirm the edge is structural, not fragile. Verdict: PASS — frozen as-is.

| Audit | Result | Verdict |
|---|---|---|
| Profit concentration | Top trade = 12% of gross; ex-top-3 expectancy still +0.29R | PASS — edge is distributed, not one lucky trade |
| Bootstrap (10k resamples, 46 trades) | Expectancy 90% CI [+0.11R, +0.87R]; P(edge<=0) = 1.7%; PF CI [1.24, 4.03] | PASS — statistically real; true PF likely ~2, not 3.9 |
| Entry delay (T+2 instead of T+1) | PF 3.88 -> 2.17, still solidly profitable (+19.4%) | PASS — edge survives execution slippage in timing |
| Split-point stability (60-80%) | PF 2.5-3.9, expectancy +0.30 to +0.48R at every split | PASS — not an artifact of one lucky window |

## Realistic expectations (write these down, not the headline numbers)
- Live expectancy likely +0.2R to +0.4R per trade, PF ~1.5-2.5, not backtest's 3.9.
- ~25-45 trades/year depending on how much green-regime time the market gives.
- Long cash stretches in yellow/red are NORMAL and correct, not a malfunction.
- Losing streaks of 5-7 trades are statistically expected at a ~40% win rate.

## Freeze terms
- No parameter or rule changes until BOTH: (a) 3+ months live AND (b) 20+ logged trades.
- The monthly auto-tune may adopt changes ONLY via its overfit guard (validation-gated).
- Any future idea gets tested on data v3 has never seen (forward data), not the same 2 years.
