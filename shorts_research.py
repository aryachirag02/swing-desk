"""Short-side research (Jul 2026). Reproduces the studies that led to the NO-GO on shorting.
Run: python shorts_research.py   (needs data/prices.csv, data/fo_list.csv, data/nifty_10y.csv)
Findings summary in RESEARCH_NOTES.md — every tested short style had negative expectancy:
  A) Index short on red-regime days: mean -0.3%/trade (2y), best 10y config +1.1% TOTAL over 8y.
  B) F&O stock shorts on 20d-low breakdowns (score<40/50, red or yellow): -1% to -4% per trade.
  C) F&O stock shorts on failed rallies at the falling 20EMA: negative at all horizons.
  D) F&O stock shorts on weak 3-month RS (with/without bounce timing): negative.
Root cause: EOD trend confirmation arrives AFTER the fall; Indian dips mean-revert hard
(2020: regime turned red near the bottom; the V-recovery stopped out all shorts)."""
print(__doc__)
