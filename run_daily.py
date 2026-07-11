"""One command = fresh dashboard + daily brief.

Usage:
  python run_daily.py            # use data already on disk
  python run_daily.py --fetch    # pull latest 2 years from Yahoo Finance first (needs internet)

If no data exists at all, generates clearly-labelled SAMPLE data so the
dashboard still works end-to-end.
"""
import argparse
import os
import subprocess
import sys

import config as C

LAMP = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def ensure_data(fetch: bool):
    if fetch:
        subprocess.run([sys.executable, "fetch_data.py"], check=True)
    if not os.path.exists(C.PRICES_FILE):
        raise SystemExit("No price data found. This system runs on REAL data only — "
                         "run `python run_daily.py --fetch` (or `python fetch_data.py`) first.")


def write_brief(snap: dict, sample: bool, path: str = "brief.md"):
    rg = snap["regime"]
    lines = [f"# Daily swing brief — {snap['asof']}", ""]
    if sample:
        lines += ["> ⚠️ **SAMPLE DATA** — demo prices, not real market data.", ""]

    lines += [
        f"**Market regime:** {LAMP[rg['light']]} **{rg['light'].upper()}** — {rg['advice']}",
        f"Nifty {rg['nifty']} · 50DMA {rg['ma50']} · 200DMA {rg['ma200']} · 1M {rg['chg_1m']:+.1f}%",
    ]
    br = snap.get("breadth")
    if br:
        lines.append(f"**Breadth:** {br['pct_above_50dma']}% of universe above 50-DMA ({br['label']})"
                     f" · A/D {br['advancers']}/{br['decliners']}")
        if rg["light"] == "green" and br["pct_above_50dma"] < 40:
            lines.append("> ⚠ Narrow rally — index is green but few stocks participate. Be selective.")
    fl = snap.get("flows")
    if fl:
        warn = " — **selling streak, tighten up**" if fl["fii_selling"] and fl["fii_streak"] >= 3 else ""
        lines.append(f"**Flows:** FII ₹{fl['fii_net_cr']:+,} cr today ({fl['fii_5d_cr']:+,} cr 5-day{warn})"
                     f" · DII ₹{fl['dii_net_cr']:+,} cr")
    lines.append("")

    idx = snap.get("indices") or []
    if idx:
        key = {r["name"]: r for r in idx}
        head = [key.get("NIFTY 50"), key.get("BANK NIFTY")]
        rest = sorted([r for r in idx if r["name"] not in ("NIFTY 50", "BANK NIFTY")],
                      key=lambda r: -(r["chg_1m"] or -999))
        strip = [r for r in head if r] + rest[:2] + rest[-2:]
        lines.append("**Indices:** " + " · ".join(
            f"{r['name']} {r['close']:,} ({r['chg_1d']:+.1f}%)" for r in strip))
        lines.append("")

    # forward-test tracker: record every microcap 🔶 setup (no hindsight, analyzed at review)
    try:
        mcs = [m for m in (snap.get("microcaps") or []) if m.get("setup_hi100")]
        if mcs:
            import csv
            path = os.path.join(C.DATA_DIR, "mc_paper.csv")
            seen = set()
            if os.path.exists(path):
                with open(path) as f:
                    seen = {(r["date"], r["ticker"]) for r in csv.DictReader(f)}
            new = [m for m in mcs if (snap["asof"], m["ticker"]) not in seen]
            if new:
                write_header = not os.path.exists(path)
                with open(path, "a", newline="") as f:
                    w = csv.writer(f)
                    if write_header:
                        w.writerow(["date", "ticker", "close", "rs_3m", "turnover_cr", "sector"])
                    for m in new:
                        w.writerow([snap["asof"], m["ticker"], m["close"], m["rs_3m"], m["turnover_cr"], m["sector"]])
                print(f"Forward-test: logged {len(new)} microcap setup(s)")
    except Exception as e:
        print(f"paper tracker skipped ({type(e).__name__})")

    fno = [x for x in (snap.get("indices") or []) if x.get("fno_dip")]
    if fno:
        lines.append("**Index F&O (dip-buy):** " + " · ".join(
            f"{x['name']} RSI2={x.get('rsi2',0):.0f} → {x['fno_dip']}" for x in fno))
        lines.append("")

    top = [s for s in snap["sectors"] if s["top"]]
    lines += ["**Leading sectors:** " + " · ".join(f"{s['sector']} ({s['blend']:+.1f}%)" for s in top), ""]

    def rows_in(state):
        return [r for r in snap["rows"] if r["state"] == state]

    for state, emoji in [("Strong Buy", "✅"), ("Buy", "🟢")]:
        rs = rows_in(state)
        lines.append(f"## {emoji} {state} ({len(rs)})")
        if rs:
            for r in rs[:15]:
                earn = f" · 📅 results {r['earnings']} — inside holding window" if r.get("earnings_soon") else ""
                seg = f" · {r['cap']} cap" if r.get("cap") else ""
                lines.append(
                    f"- **{r['ticker']}** ({r['sector']}{seg}) — score {r['score']:.0f}, {r['trigger_label']}."
                    f" Entry ₹{r['entry']} · Stop ₹{r['stop']} · Target ₹{r['target']} · Risk/sh ₹{r['risk_per_share']}{earn}"
                )
        else:
            lines.append("- none today")
        lines.append("")

    due = [r for r in snap["rows"] if r.get("earnings_soon")
           and r["state"] in ("Strong Buy", "Buy", "Watchlist")]
    if due:
        lines.append("## 📅 Results due soon (earnings gaps jump past stops — size down or wait)")
        lines += [f"- **{r['ticker']}** — {r['earnings']}" for r in due[:15]]
        lines.append("")

    wl = rows_in("Watchlist")
    lines.append(f"## 👀 Watchlist ({len(wl)})")
    lines.append(" · ".join(r["ticker"] for r in wl[:25]) + (" …" if len(wl) > 25 else "") if wl else "- none")
    lines += [
        "",
        "## 📌 Position reminders (check Trade log tab)",
        f"- **Exit** any holding whose score has dropped below {C.EXIT_SCORE}; **Reduce** below {C.REDUCE_SCORE}.",
        f"- Hard stop {C.STOP_ATR_MULT}×ATR below entry · breakeven at +1R · time-stop after {C.TIME_STOP_BARS} bars (~6 weeks).",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Brief written: {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="pull fresh data from Yahoo Finance first")
    args = ap.parse_args()

    ensure_data(args.fetch)

    import generate_dashboard
    snap = generate_dashboard.build()
    sample = os.path.exists(os.path.join(C.DATA_DIR, "SAMPLE_FLAG"))
    write_brief(snap, sample)

    n = {s: len([r for r in snap["rows"] if r["state"] == s]) for s in C.STATE_ORDER}
    print(f"Signals -> Strong Buy: {n['Strong Buy']} | Buy: {n['Buy']} | Watchlist: {n['Watchlist']}"
          f" | Regime: {snap['regime']['light']}")


if __name__ == "__main__":
    main()
