"""Pulls the real data: Nifty 500 constituent list (official NSE CSV) + 2 years of daily
OHLCV from Yahoo Finance for every stock and the Nifty index. Writes the same
prices.csv / meta.csv format the sample generator uses, so the rest of the system
doesn't care which source it's running on.

Needs internet access to: query1/query2.finance.yahoo.com, fc.yahoo.com
(and optionally nsearchives.nseindia.com for the constituent list).

Run:  python fetch_data.py
"""
import io, os, sys, time
import pandas as pd
import config as C

NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
MIDCAP150_URL = "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
SMALLCAP250_URL = "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"



INDICES = {  # Yahoo symbol -> display name (verified working Jul 2026)
    "^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "NIFTY_FIN_SERVICE.NS": "FIN NIFTY",
    "^CNXIT": "NIFTY IT", "^NSEMDCP50": "NIFTY MIDCAP 50", "NIFTY_MIDCAP_100.NS": "NIFTY MIDCAP 100",
    "^CNXAUTO": "NIFTY AUTO", "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG",
    "^CNXMETAL": "NIFTY METAL", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY",
    "^CNXPSUBANK": "NIFTY PSU BANK", "^CNXINFRA": "NIFTY INFRA", "^CNXMEDIA": "NIFTY MEDIA",
}  # Nifty Smallcap 100 has no usable Yahoo history — tracked via our own Smallcap-250 tags instead


def fetch_indices(years=C.YEARS_OF_DATA):
    """Major NSE indices -> data/indices.csv (separate from the stock universe)."""
    import yfinance as yf
    rows = []
    for sym, name in INDICES.items():
        try:
            df = yf.download(sym, period=f"{years}y", interval="1d", auto_adjust=True,
                             progress=False, group_by="column")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns=str.lower).dropna(subset=["close"]).reset_index().rename(columns={"Date": "date"})
            df["ticker"], df["name"] = sym, name
            rows.append(df[["date", "ticker", "name", "open", "high", "low", "close", "volume"]])
            time.sleep(0.3)
        except Exception as e:
            print(f"index {sym} skipped ({type(e).__name__})")
    if rows:
        out = pd.concat(rows, ignore_index=True)
        out = _drop_live_bar(out)
        out.to_csv(os.path.join(C.DATA_DIR, "indices.csv"), index=False)
        print(f"Indices saved: {out['ticker'].nunique()} indices, {out['date'].nunique()} days")



def _drop_live_bar(df):
    """If we're fetching mid-session (IST market hours), drop today's in-progress bar:
    an EOD system must only ever see completed daily bars."""
    from datetime import datetime, timedelta, timezone
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if ist.weekday() < 5 and (9, 0) <= (ist.hour, ist.minute) <= (15, 40):
        today = pd.Timestamp(ist.date())
        before = len(df)
        df = df[pd.to_datetime(df["date"]).dt.normalize() < today]
        if len(df) < before:
            print(f"Market open — dropped today's partial bar ({before-len(df)} rows); using last completed close")
    return df


def get_universe():
    """Official Nifty 500 list -> (ticker, name, sector, cap). Falls back to embedded subset.
    Nifty 500 = Nifty 100 (Large) + Midcap 150 (Mid) + Smallcap 250 (Small); we tag each stock."""
    try:
        import requests

        def symbols(url):
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            d = pd.read_csv(io.StringIO(r.text))
            return d

        df = symbols(NIFTY500_URL)
        df = df.rename(columns={"Symbol": "symbol", "Company Name": "name", "Industry": "sector"})
        cap_map = {}
        for url, seg in [(MIDCAP150_URL, "Mid"), (SMALLCAP250_URL, "Small")]:
            try:
                for s in symbols(url)["Symbol"].astype(str).str.strip():
                    cap_map[s] = seg
            except Exception:
                pass  # segment tags are a bonus — universe works without them
        syms = df["symbol"].astype(str).str.strip()
        out = pd.DataFrame({
            "ticker": syms + ".NS",
            "name": df["name"].astype(str).str.strip(),
            "sector": df["sector"].astype(str).str.strip(),
            "cap": [cap_map.get(s, "Large" if cap_map else "") for s in syms],
        })
        tagged = (out["cap"] != "").sum()
        print(f"Fetched official Nifty 500 list: {len(out)} names ({tagged} tagged Large/Mid/Small)")
        return out
    except Exception as e:
        print(f"Could not fetch official list ({e}); using embedded fallback universe "
              f"({len(C.EMBEDDED_UNIVERSE)} names)")
        return pd.DataFrame([{"ticker": t, "name": n, "sector": s, "cap": ""}
                             for t, (n, s) in C.EMBEDDED_UNIVERSE.items()])


def fetch_prices(tickers, years=C.YEARS_OF_DATA):
    import yfinance as yf
    period = f"{years}y"
    all_rows = []
    BATCH = 50
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i + BATCH]
        print(f"Downloading {i + 1}-{i + len(batch)} of {len(tickers)} ...")
        data = yf.download(batch, period=period, interval="1d", auto_adjust=True,
                           group_by="ticker", threads=True, progress=False)
        for t in batch:
            try:
                df = data[t].dropna(subset=["Close"]) if len(batch) > 1 else data.dropna(subset=["Close"])
                if df.empty:
                    continue
                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
                df = df.reset_index().rename(columns={"Date": "date"})
                df["ticker"] = t
                all_rows.append(df)
            except Exception:
                continue
        time.sleep(1)  # be polite to Yahoo
    prices = pd.concat(all_rows, ignore_index=True)
    prices = _drop_live_bar(prices)
    return prices[["date", "ticker", "open", "high", "low", "close", "volume"]]


def fetch_earnings_dates(tickers):
    """Next earnings date per ticker (holdings + watchlist only — slow per-ticker call)."""
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            cal = yf.Ticker(t).calendar
            d = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if d:
                out[t] = str(d[0] if isinstance(d, (list, tuple)) else d)
        except Exception:
            pass
        time.sleep(0.3)
    return out


def _nse_session():
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                      "Accept": "application/json", "Referer": "https://www.nseindia.com/"})
    s.get("https://www.nseindia.com", timeout=10)  # sets cookies
    return s


def fetch_flows():
    """FII/DII net buy/sell (₹ cr) from NSE -> appends data/flows.csv. Needs www.nseindia.com allowed."""
    try:
        s = _nse_session()
        js = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10).json()
        rec = {}
        for x in js:
            cat = str(x.get("category", "")).upper()
            key = "fii_net_cr" if "FII" in cat or "FPI" in cat else "dii_net_cr" if "DII" in cat else None
            if key:
                rec.setdefault(x.get("date"), {})[key] = float(x.get("netValue", 0))
        rows = [{"date": pd.to_datetime(d, dayfirst=True).date(), **v} for d, v in rec.items()]
        if not rows:
            raise ValueError("empty response")
        new = pd.DataFrame(rows)
        if os.path.exists(C.FLOWS_FILE):
            old = pd.read_csv(C.FLOWS_FILE, parse_dates=["date"])
            old["date"] = old["date"].dt.date
            new = pd.concat([old, new]).drop_duplicates("date", keep="last")
        new.sort_values("date").to_csv(C.FLOWS_FILE, index=False)
        print(f"FII/DII flows updated ({len(new)} days on file)")
    except Exception as e:
        print(f"FII/DII flows skipped ({type(e).__name__}) — allow www.nseindia.com, or drop data/flows.csv manually")


def fetch_surveillance():
    """ASM + GSM surveillance lists from NSE -> data/asm_gsm.csv (these stocks never get a Buy state)."""
    try:
        s = _nse_session()
        rows = []
        for url, name in [("https://www.nseindia.com/api/reportASM", "ASM"),
                          ("https://www.nseindia.com/api/reportGSM", "GSM")]:
            js = s.get(url, timeout=10).json()
            for section in (js.get("longterm", {}), js.get("shortterm", {}), js):
                for item in (section.get("data") or []):
                    sym = item.get("symbol")
                    if sym:
                        stage = item.get("asmSurvIndicator") or item.get("gsmSurvIndicator") or ""
                        rows.append({"ticker": f"{sym}.NS", "list": f"{name} {stage}".strip()})
        if not rows:
            raise ValueError("empty response")
        pd.DataFrame(rows).drop_duplicates("ticker").to_csv(C.SURVEILLANCE_FILE, index=False)
        print(f"Surveillance list updated ({len(rows)} tickers on ASM/GSM)")
    except Exception as e:
        print(f"ASM/GSM skipped ({type(e).__name__}) — allow www.nseindia.com, or drop data/asm_gsm.csv manually")


def save_earnings(meta, prices):
    """Next earnings date for liquid tickers -> data/earnings.csv (slow: ~0.3s per ticker, run weekly)."""
    turn = (prices.assign(turn=prices["close"] * prices["volume"] / 1e7)
            .groupby("ticker")["turn"].mean())
    liquid = [t for t in meta["ticker"] if turn.get(t, 0) >= C.MIN_TURNOVER_CR]
    print(f"Fetching earnings dates for {len(liquid)} liquid tickers (this takes a few minutes)…")
    out = fetch_earnings_dates(liquid)
    pd.DataFrame([{"ticker": k, "next_earnings": v} for k, v in out.items()]).to_csv(C.EARNINGS_FILE, index=False)
    print(f"Earnings dates saved for {len(out)} tickers")


def fetch_benchmark(years=C.YEARS_OF_DATA):
    """Fetch the benchmark index separately — batch downloads have silently dropped
    special-character tickers like ^NSEI before, and the whole engine depends on it."""
    import yfinance as yf
    df = yf.download(C.BENCHMARK, period=f"{years}y", interval="1d", auto_adjust=True,
                     progress=False, group_by="column")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower).dropna(subset=["close"]).reset_index().rename(columns={"Date": "date"})
    df["ticker"] = C.BENCHMARK
    return df[["date", "ticker", "open", "high", "low", "close", "volume"]]


def quality_gate(prices, min_tickers=450, max_stale_days=7):
    """Refuse to publish signals from broken/partial data. Live money runs on this."""
    got = prices["ticker"].nunique()
    if got < min_tickers:
        raise SystemExit(f"DATA QUALITY FAIL: only {got} tickers fetched (need >= {min_tickers}). "
                         "Not overwriting good data — investigate before trading.")
    if C.BENCHMARK not in set(prices["ticker"]):
        raise SystemExit("DATA QUALITY FAIL: benchmark missing — regime light cannot be computed.")
    age = (pd.Timestamp.now().normalize() - pd.to_datetime(prices["date"]).max()).days
    if age > max_stale_days:
        raise SystemExit(f"DATA QUALITY FAIL: newest bar is {age} days old — feed looks stale.")
    print(f"Quality gate passed: {got} tickers, newest bar {pd.to_datetime(prices['date']).max().date()}")


if __name__ == "__main__":
    meta = get_universe()
    prices = fetch_prices(meta["ticker"].tolist())
    bench = _drop_live_bar(fetch_benchmark())
    prices = pd.concat([prices[prices["ticker"] != C.BENCHMARK], bench], ignore_index=True)
    quality_gate(prices)
    print(f"Got data for {prices['ticker'].nunique()} tickers, {prices['date'].nunique()} trading days")
    os.makedirs(C.DATA_DIR, exist_ok=True)
    prices.to_csv(C.PRICES_FILE, index=False)
    meta[meta["ticker"].isin(prices["ticker"].unique())].to_csv(C.META_FILE, index=False)
    flag = os.path.join(C.DATA_DIR, "SAMPLE_FLAG")
    if os.path.exists(flag):
        os.remove(flag)  # real data now — clear the sample banner
    fetch_indices()        # NIFTY / BANK NIFTY / sector indices for the Indices tab
    fetch_flows()          # best-effort extras: skip quietly if NSE is unreachable
    fetch_surveillance()
    if "--earnings" in sys.argv:
        save_earnings(meta, prices)
    print("Saved prices.csv and meta.csv — run `python run_daily.py` next")
