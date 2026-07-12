# Setup Grade — backtested breakout quality (Jul 2026)

10-year event study: 5,722 breakout events (100d-high + vol>=1.5x + positive 3M momentum) on
current Nifty 500 constituents. Rules derived on 2016-2022 (3,609 events), validated once on
2023-2026 (2,113 events). Regime-at-event was tested and FAILED holdout — excluded.

Grade rules (only holdout-confirmed factors):
- A: 3M momentum 25-120% AND volume >= 2.5x normal
- B: one of the two strong (momentum 25-120% OR volume >= 2.5x)
- C: quiet/early breakout, or momentum > 120% (overextended; historical bucket too thin to trust)

12-month outcomes:
| Grade | Derive: mean / doubled | Holdout: mean / doubled |
|---|---|---|
| A | +61.2% / 21.6% | +49.4% / 18.1% |
| B | +32.2% / 11.1% | +40.4% / 13.4% |
| C | +26.9% / 6.7% | +33.3% / 8.6% |

Honest caveats: absolute numbers are survivorship-inflated (today's constituents = survivors);
the RELATIVE ordering (A > B > C, doubling rate monotonic in both eras) is the trustworthy part.
Win-rate ordering is not monotonic in holdout — the grade predicts MAGNITUDE, not hit rate.
The AI CALL remains unbacktestable (news hindsight contamination) and is graded live via the
forward-test and the source-tagged trade log. Grade and AI CALL together = backtested pattern
quality + current-story judgment.
