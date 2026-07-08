"""Central config for the NSE swing system. Tune everything here.
If params_tuned.json exists (written by backtest.py --tune), those values override defaults."""
import json, os

# ---------- Universe & data ----------
UNIVERSE = "nifty500"          # official list fetched live; falls back to EMBEDDED_UNIVERSE
BENCHMARK = "^NSEI"            # Nifty 50 index on Yahoo
YEARS_OF_DATA = 2
DATA_DIR = "data"
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")   # long format: date,ticker,open,high,low,close,volume
META_FILE = os.path.join(DATA_DIR, "meta.csv")       # ticker,name,sector
EARNINGS_FILE = os.path.join(DATA_DIR, "earnings.csv")      # ticker,next_earnings (optional)
SURVEILLANCE_FILE = os.path.join(DATA_DIR, "asm_gsm.csv")   # ticker,list  e.g. "ASM Stage I" (optional)
FLOWS_FILE = os.path.join(DATA_DIR, "flows.csv")            # date,fii_net_cr,dii_net_cr (optional)
EARNINGS_WARN_DAYS = 30        # flag stocks reporting results within this many days (holding window)

# ---------- Indicator parameters ----------
EMA_FAST, EMA_SLOW = 20, 50
RSI_LEN = 14
ATR_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
RS_SHORT, RS_LONG = 21, 63     # ~1 month / ~3 months of trading days
VOL_AVG_LEN = 20
BREAKOUT_LOOKBACK = 20         # 20-day high breakout

# ---------- Scoring (out of 100) ----------
W_TREND, W_MOMENTUM, W_RELSTRENGTH, W_VOLUME, W_VOLATILITY = 25, 25, 30, 10, 10

# ---------- Signal thresholds ----------
STRONG_BUY_SCORE = 80
BUY_SCORE = 70
WATCHLIST_SCORE = 60
EXIT_SCORE = 40                # score decay exit
REDUCE_SCORE = 50              # held + score below this -> Reduce

# ---------- Trade management ----------
# v2 (Jul 2026 research, see RESEARCH_NOTES.md): median winner dips before it runs,
# so the old tight stop (2.0 ATR) + short time-stop (30 bars) was harvesting the dip.
STOP_ATR_MULT = 2.5            # hard stop = entry - 2.5 x ATR
TRAIL_ATR_MULT = 4.0           # after +1R, trail stop 4 x ATR below highest close (let winners breathe)
BREAKEVEN_AT_R = 1.0           # move stop to entry once trade is +1R
TARGET_R = 2.0                 # dashboard target = entry + 2R (informational)
TIME_STOP_BARS = 60            # winners need room; median hold stays ~3-4 weeks (losers stop out early)
RISK_PER_TRADE = 0.01          # 1% of capital risked per trade
MAX_POSITIONS = 10
MAX_PER_SECTOR = 3
TOP_SECTORS = 4                # only buy stocks from the top-N strongest sectors
MIN_TURNOVER_CR = 10.0         # min avg daily turnover in Rs crore (liquidity filter)
STARTING_CAPITAL = 1_000_000   # for backtest, Rs 10L notional
CASH_YIELD_PA = 0.065          # idle cash parked in a liquid fund (~6.5% p.a.) — the honest
                               # way to be net-positive while the system sits out corrections

# Regime -> risk multiplier. v2: yellow set to 0 — yellow-day entries averaged -0.39R across
# 2 years of data; this signal set only has edge in confirmed uptrends (green).
REGIME_RISK = {"green": 1.0, "yellow": 0.0, "red": 0.0}

# Entry trigger mode: "breakout", "pullback", or "both".
# v2: breakout-only — pullback entries were negative-expectancy in every tested configuration.
TRIGGER_MODE = "breakout"

# ---------- Friendly labels ----------
STATE_ORDER = ["Strong Buy", "Buy", "Watchlist", "Hold", "Reduce", "Exit", "—"]

# ---------- Tuned-parameter override ----------
TUNED_FILE = "params_tuned.json"
def load_tuned():
    """backtest.py --tune writes the winning params here; run_daily picks them up automatically."""
    if os.path.exists(TUNED_FILE):
        with open(TUNED_FILE) as f:
            return json.load(f)
    return {}

_t = load_tuned()
BUY_SCORE = _t.get("BUY_SCORE", BUY_SCORE)
STOP_ATR_MULT = _t.get("STOP_ATR_MULT", STOP_ATR_MULT)
TRAIL_ATR_MULT = _t.get("TRAIL_ATR_MULT", TRAIL_ATR_MULT)

# Fallback universe if the official Nifty 500 list can't be fetched (subset; full list downloads live)
EMBEDDED_UNIVERSE = {
    "RELIANCE.NS": ("Reliance Industries", "Energy"), "ONGC.NS": ("ONGC", "Energy"),
    "NTPC.NS": ("NTPC", "Energy"), "POWERGRID.NS": ("Power Grid", "Energy"),
    "TCS.NS": ("TCS", "IT"), "INFY.NS": ("Infosys", "IT"), "HCLTECH.NS": ("HCL Tech", "IT"),
    "WIPRO.NS": ("Wipro", "IT"), "LTIM.NS": ("LTIMindtree", "IT"),
    "HDFCBANK.NS": ("HDFC Bank", "Banks"), "ICICIBANK.NS": ("ICICI Bank", "Banks"),
    "SBIN.NS": ("State Bank of India", "Banks"), "KOTAKBANK.NS": ("Kotak Bank", "Banks"),
    "AXISBANK.NS": ("Axis Bank", "Banks"),
    "BAJFINANCE.NS": ("Bajaj Finance", "Financial Services"), "HDFCLIFE.NS": ("HDFC Life", "Financial Services"),
    "SBILIFE.NS": ("SBI Life", "Financial Services"), "CHOLAFIN.NS": ("Chola Finance", "Financial Services"),
    "SUNPHARMA.NS": ("Sun Pharma", "Pharma"), "CIPLA.NS": ("Cipla", "Pharma"),
    "DRREDDY.NS": ("Dr Reddy's", "Pharma"), "DIVISLAB.NS": ("Divi's Labs", "Pharma"),
    "MARUTI.NS": ("Maruti Suzuki", "Auto"), "TATAMOTORS.NS": ("Tata Motors", "Auto"),
    "M&M.NS": ("Mahindra & Mahindra", "Auto"), "BAJAJ-AUTO.NS": ("Bajaj Auto", "Auto"),
    "EICHERMOT.NS": ("Eicher Motors", "Auto"),
    "HINDUNILVR.NS": ("Hindustan Unilever", "FMCG"), "ITC.NS": ("ITC", "FMCG"),
    "NESTLEIND.NS": ("Nestle India", "FMCG"), "BRITANNIA.NS": ("Britannia", "FMCG"),
    "TATASTEEL.NS": ("Tata Steel", "Metals"), "JSWSTEEL.NS": ("JSW Steel", "Metals"),
    "HINDALCO.NS": ("Hindalco", "Metals"), "VEDL.NS": ("Vedanta", "Metals"),
    "LT.NS": ("Larsen & Toubro", "Infra"), "ADANIPORTS.NS": ("Adani Ports", "Infra"),
    "ULTRACEMCO.NS": ("UltraTech Cement", "Infra"), "GRASIM.NS": ("Grasim", "Infra"),
    "DLF.NS": ("DLF", "Realty"), "GODREJPROP.NS": ("Godrej Properties", "Realty"),
    "OBEROIRLTY.NS": ("Oberoi Realty", "Realty"),
    "BHARTIARTL.NS": ("Bharti Airtel", "Telecom"), "IDEA.NS": ("Vodafone Idea", "Telecom"),
    "ZOMATO.NS": ("Zomato", "Consumer Tech"), "PAYTM.NS": ("Paytm", "Consumer Tech"),
    "NYKAA.NS": ("Nykaa", "Consumer Tech"), "TRENT.NS": ("Trent", "Consumer Tech"),
}
