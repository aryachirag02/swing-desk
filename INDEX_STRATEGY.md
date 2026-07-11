# Index F&O strategy — "Dip-Buy" (validated Jul 2026)

The only strategy in this project to pass BOTH train (2016-2023, incl. 2020 crash) and
one-shot validation (2024-2026). Trend/breakout approaches on indices failed validation.

## The rules (evening check, ~5 min after close)
1. Compute on the INDEX (NIFTY or BANK NIFTY): 200-day moving average and RSI(2) of closes.
2. ENTRY: if close > 200DMA AND RSI(2) < 10 -> BUY next morning at open.
3. EXIT: when RSI(2) > 70 -> SELL next morning at open. Safety: exit if close < 200DMA.
4. One position per index at a time. Typical hold 2-5 days, ~10-12 trades/yr/index, in market ~20% of days.

## Threshold choice (frequency vs strictness)
RSI<10 adopted for live: ~2x the trades of RSI<5 with equal-or-better validation
(NIFTY 9.9% CAGR / 70% win / Sharpe 1.98; BANKNIFTY 11.5% / Sharpe 1.78). RSI<15 dilutes the
edge (Sharpe ~1.0) — rejected. Disclosure: RSI<10 was a family neighbor whose validation was
observed alongside the pre-registered RSI<5; both were strong on train, which drove selection.

## Validated results (unleveraged, 5bps/side, cash yield when flat)
| | Train 16-23 | Validation 24-26 | B&H validation |
|---|---|---|---|
| NIFTY rsi<5 | 7.4% CAGR, -5.6% DD, Sharpe 1.48 | 8.3% CAGR, -3.1% DD, Sharpe 2.01 | 4.5% CAGR |
| NIFTY rsi<10 (live) | 6.9% CAGR, -8.8% DD, Sharpe 1.09 | 9.9% CAGR, -3.5% DD, Sharpe 1.98 | 4.5% CAGR |
| BANKNIFTY rsi<5 | 10.3% CAGR, -8.0% DD, Sharpe 1.64 | 10.2% CAGR, -5.1% DD, Sharpe 1.90 | 7.8% CAGR |
| BANKNIFTY rsi<10 (live) | 8.9% CAGR, -16.6% DD, Sharpe 1.14 | 11.5% CAGR, -5.1% DD, Sharpe 1.78 | 7.8% CAGR |

## F&O implementation (read carefully — leverage is the whole risk)
- Instrument: near-month index FUTURES (roll ~2 days before expiry). One NIFTY lot ≈ Rs 15-16L
  notional (~Rs 1.6-1.8L margin). BANKNIFTY lot similar order — check current lot sizes.
- LEVERAGE RULE: total notional <= 1.5-2x your allocated capital. At 2x, expect roughly double
  the CAGR AND double the drawdown. Never size by "margin available" — size by notional.
- Tail risk is real and unhedged: this strategy BUYS FALLING MARKETS and holds overnight.
  A 2020-style -13% gap day at 2x leverage = -26% of capital in one day. If that is
  unacceptable, trade 1x (futures or simply index ETFs) — the edge is identical.
- Options: NOT backtested (no option-chain history). If you must use options, deep-ITM calls
  approximate futures; selling puts changes the risk profile entirely — not validated.

## Honest caveats
- Validation n = 13-15 trades per index. Real, but small — treat first months live as the test.
- Psychologically hard: entries trigger on scary red days. The discipline IS the edge.
- No shorting; below the 200DMA the system stays in cash (liquid fund).
- Frozen like v3: no parameter changes until 3+ months and 20+ live trades.
