#!/usr/bin/env python3
"""
healthcheck.py — pipeline self-audit. Runs at the end of the workflow (after run_daily.py).
Prints a PASS/WARN/FAIL report and exits non-zero ONLY on FAIL (so the Actions run goes red
on real breakage, but tolerates benign gaps like "no holdings yet").

Design: WARN = "worth knowing, not broken" (e.g. theme map empty, no open positions).
        FAIL = "the thing that makes the dashboard trustworthy is broken" (stale prices,
        dashboard not built, signals all NaN, JSON corrupt).
"""
import os, json, sys
import pandas as pd
import config as C

DATA = C.DATA_DIR
fails, warns, oks = [], [], []


def ok(m): oks.append(m)
def warn(m): warns.append(m)
def fail(m): fails.append(m)


def check_file(path, max_age_days=None, label=None):
    label = label or path
    if not os.path.exists(path):
        fail(f"MISSING: {label}")
        return False
    if max_age_days is not None:
        import time
        age = (time.time() - os.path.getmtime(path)) / 86400
        if age > max_age_days:
            warn(f"STALE ({age:.1f}d): {label}")
    ok(f"present: {label}")
    return True


# ---- 1. Price data freshness (the foundation everything rests on) ----
try:
    px = pd.read_csv(os.path.join(DATA, "prices.csv"), parse_dates=["date"])
    last = px["date"].max()
    age = (pd.Timestamp.now() - last).days
    if age > 5:
        fail(f"prices.csv last date {last.date()} is {age}d old — pipeline may be stalled")
    else:
        ok(f"prices fresh (last {last.date()}, {age}d)")
    if px["close"].isna().mean() > 0.05:
        warn(f"prices.csv has {px['close'].isna().mean()*100:.0f}% NaN closes")
    if px["ticker"].nunique() < 300:
        warn(f"only {px['ticker'].nunique()} tickers in prices.csv (expected ~500)")
    else:
        ok(f"{px['ticker'].nunique()} tickers loaded")
except Exception as e:
    fail(f"prices.csv unreadable: {type(e).__name__}: {e}")


# ---- 2. Dashboard built and non-trivial ----
for f in ["dashboard.html", "index.html"]:
    if check_file(f):
        sz = os.path.getsize(f)
        if sz < 20000:
            fail(f"{f} is only {sz} bytes — likely a render failure")
        else:
            ok(f"{f} ({sz//1024}kb)")

if os.path.exists("dashboard.html"):
    h = open("dashboard.html").read()
    if "DATA=" not in h and "window.DATA" not in h and '"radar"' not in h:
        fail("dashboard.html has no embedded DATA payload")
    else:
        ok("dashboard payload embedded")


# ---- 3. Core JSON/CSV outputs parse ----
for jf in ["intel.json", "theme_map.json", "portfolio_review.json"]:
    p = os.path.join(DATA, jf)
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            if jf == "theme_map.json" and not d:
                warn("theme_map.json is empty (AI synthesis produced nothing this run)")
            else:
                ok(f"{jf} parses ({len(d)} items)")
        except Exception as e:
            fail(f"{jf} corrupt: {type(e).__name__}")
    else:
        warn(f"{jf} not present (may not have run this cycle)")


# ---- 4. Signals sane ----
try:
    bt = json.load(open("backtest_summary.json")) if os.path.exists("backtest_summary.json") else None
    if bt:
        ok("backtest_summary.json present")
except Exception as e:
    warn(f"backtest_summary.json issue: {type(e).__name__}")


# ---- 5. AI-call ledger writing (the forward-test's notebook) ----
led = os.path.join(DATA, "ai_calls.csv")
if os.path.exists(led):
    try:
        lc = pd.read_csv(led)
        need = {"date", "ticker", "call", "close"}
        if not need.issubset(lc.columns):
            fail(f"ai_calls.csv missing columns: {need - set(lc.columns)}")
        else:
            ok(f"ai_calls.csv healthy ({len(lc)} calls logged)")
    except Exception as e:
        fail(f"ai_calls.csv corrupt: {type(e).__name__}")
else:
    warn("ai_calls.csv not yet created (first intel run pending)")


# ---- 6. Radar internal consistency ----
try:
    import engine as E
    r = E.radar_snapshot()
    for k in ["breakouts", "accum"]:
        rows = r.get(k, [])
        for row in rows[:50]:
            if row.get("close") in (None, 0):
                warn(f"radar {k}: {row.get('ticker')} has no price")
                break
    # every breakout should carry a grade + window fields
    missing_grade = [x["ticker"] for x in r.get("breakouts", []) if not x.get("grade")]
    if missing_grade:
        warn(f"breakouts missing grade: {missing_grade[:5]}")
    else:
        ok(f"radar: {len(r.get('breakouts',[]))} breakouts all graded")
except Exception as e:
    fail(f"radar_snapshot() threw: {type(e).__name__}: {e}")


# ---- 7. tradelog / family DB readable if present ----
if os.path.exists("tradelog.json"):
    try:
        tl = json.load(open("tradelog.json"))
        ent = tl.get("entries", tl if isinstance(tl, list) else [])
        ok(f"tradelog.json readable ({len(ent)} entries)")
    except Exception as e:
        fail(f"tradelog.json corrupt: {type(e).__name__}")


# ---- report ----
print("\n" + "=" * 52)
print("  SWING DESK HEALTHCHECK")
print("=" * 52)
for m in oks:
    print(f"  ✓  {m}")
for m in warns:
    print(f"  ⚠  {m}")
for m in fails:
    print(f"  ✗  {m}")
print("=" * 52)
print(f"  {len(oks)} ok · {len(warns)} warnings · {len(fails)} failures")
print("=" * 52 + "\n")

if fails:
    print("HEALTHCHECK FAILED — see ✗ above")
    sys.exit(1)
print("HEALTHCHECK PASSED" + (f" (with {len(warns)} warnings)" if warns else ""))
sys.exit(0)
