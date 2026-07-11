"""Market intelligence layer: Claude + web search reads news/themes for the day's
quant-flagged movers (funnel design — not all 1000 stocks). Needs ANTHROPIC_API_KEY.
Output: data/intel.md, injected into the daily brief by run_daily.py.
This is RESEARCH ASSISTANCE, not a validated signal — long-term buys still need human judgment."""
import os, sys, json, time
import pandas as pd, numpy as np
import requests as rq
import config as C

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("INTEL_MODEL", "claude-sonnet-4-6")
MAX_STOCKS = int(os.environ.get("INTEL_MAX_STOCKS", "20"))

def candidates():
    """Funnel: top RS + fresh 100d-high breakouts + volume surges across Nifty500+Microcap, plus watchlist."""
    out = {}
    for pf, mf in [(C.PRICES_FILE, C.META_FILE),
                   (os.path.join(C.DATA_DIR, "mc_prices.csv"), os.path.join(C.DATA_DIR, "mc_meta.csv"))]:
        if not os.path.exists(pf): continue
        px = pd.read_csv(pf, parse_dates=["date"])
        meta = pd.read_csv(mf).set_index("ticker")
        bench = pd.read_csv(C.PRICES_FILE, parse_dates=["date"])
        bench = bench[bench.ticker == C.BENCHMARK].set_index("date")["close"]
        for t, g in px.groupby("ticker"):
            if t == C.BENCHMARK or len(g) < 110: continue
            g = g.sort_values("date").set_index("date")
            c = g.close; b = bench.reindex(g.index).ffill()
            turn = float((c * g.volume / 1e7).tail(20).mean())
            if turn < C.MIN_TURNOVER_CR: continue
            rs3 = float((c.pct_change(63).iloc[-1] - b.pct_change(63).iloc[-1]) * 100)
            vr = float((g.volume.iloc[-1] / g.volume.rolling(20).mean().iloc[-1]) or 0)
            hi100 = float(g.high.rolling(100).max().shift(1).iloc[-1])
            brk = bool(c.iloc[-1] > hi100)
            manual = str(meta.loc[t, "cap"]) == "Manual" if t in meta.index else False
            score = rs3 + (25 if brk else 0) + (15 if vr >= 2 else 0) + (40 if manual else 0)
            name = str(meta.loc[t, "name"]) if t in meta.index else t
            sector = str(meta.loc[t, "sector"]) if t in meta.index else "?"
            out[t] = {"ticker": t, "name": name, "sector": sector, "rs3": round(rs3, 0),
                      "breakout": brk, "vol_surge": round(vr, 1), "score": score}
    ranked = sorted(out.values(), key=lambda r: -r["score"])
    return ranked[:MAX_STOCKS]

def ask_claude(messages, max_tokens=700):
    r = rq.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "messages": messages,
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]},
        timeout=180)
    r.raise_for_status()
    return " ".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()

def main():
    if not API_KEY:
        print("intel: no ANTHROPIC_API_KEY — skipping"); return
    cands = candidates()
    if not cands:
        print("intel: no candidates"); return
    print(f"intel: researching {len(cands)} quant-flagged movers via {MODEL}")
    sections = []
    for c in cands:
        sym = c["ticker"].replace(".NS", "")
        q = (f"NSE-listed Indian stock {c['name']} (symbol {sym}, sector {c['sector']}) is up strongly "
             f"({c['rs3']:+.0f}% vs Nifty over 3 months"
             + (", fresh 100-day-high breakout" if c["breakout"] else "")
             + (f", volume {c['vol_surge']}x average" if c["vol_surge"] >= 2 else "") + "). "
             "First check screener.in/company/" + sym + "/ for fundamentals (sales & profit growth "
             "trend, ROE, debt, promoter holding change), then search recent news (last 3-4 weeks). "
             "In max 4 short bullets: "
             "(1) the specific catalyst (order wins, results, policy, sector theme) with dates if found, "
             "(2) whether it's part of a broader sector/theme move and which peers, "
             "(3) fundamentals check: is the price move backed by earnings/order growth or purely price action? "
             "(4) credibility: hard news vs speculation/operator chatter. "
             "If you find nothing concrete, say 'no clear public catalyst found' — do not invent reasons.")
        try:
            ans = ask_claude([{"role": "user", "content": q}])
            sections.append(f"### {sym} — {c['name']} ({c['sector']}) · RS {c['rs3']:+.0f}%"
                            + (" · 🔶 breakout" if c["breakout"] else "") + f"\n{ans}\n")
            c["ai"] = ans
            print(f"  ✓ {sym}")
        except Exception as e:
            print(f"  ✗ {sym}: {type(e).__name__}")
        time.sleep(1)
    # theme synthesis
    try:
        names = ", ".join(f"{c['ticker'].replace('.NS','')} ({c['sector']})" for c in cands)
        theme = ask_claude([{"role": "user", "content":
            f"These NSE stocks are today's strongest quant-flagged movers: {names}. "
            "In 3-4 sentences: identify any common sector themes or macro narratives linking several of them "
            "(e.g. optical fiber capex, defence orders, power capex). Name the theme and its members. "
            "Base it on the sector mix and current Indian market news; be specific, no fluff."}], 400)
        sections.insert(0, f"## Theme read\n{theme}\n")
    except Exception as e:
        print(f"theme synthesis failed: {type(e).__name__}")
    hdr = (f"# Market intelligence — {pd.Timestamp.now().strftime('%Y-%m-%d')}\n"
           f"_Claude web-research on the day's {len(cands)} quant-flagged movers. Research assistance, "
           f"NOT validated signals — verify before any long-term buy._\n\n")
    open(os.path.join(C.DATA_DIR, "intel.md"), "w").write(hdr + "\n".join(sections))
    json.dump([{k: c.get(k) for k in ("ticker","name","sector","rs3","breakout","vol_surge","ai")}
               for c in cands if c.get("ai")],
              open(os.path.join(C.DATA_DIR, "intel.json"), "w"))
    print(f"intel.md + intel.json written ({len(sections)} sections)")

def themes():
    """Friday forward scan: upcoming catalysts (1-2 quarters) -> exposed listed names. Theme-first."""
    if not API_KEY: print("themes: no key"); return
    q = ("You are researching FORWARD catalysts for Indian equities. Search for major upcoming "
         "catalysts over the next 1-2 quarters: government capex programs and tender pipelines "
         "(e.g. BharatNet, railways, defence procurement, power/transmission, water), PLI scheme "
         "disbursements, regulatory changes, and sector capex cycles turning up. For the 4-6 most "
         "concrete ones, give: the catalyst with expected timing, and 2-4 NSE-listed stocks (prefer "
         "small/midcaps) with DIRECT revenue exposure. Mark speculation clearly. Max 350 words, "
         "plain text, no markdown headers.")
    try:
        out = ask_claude([{"role": "user", "content": q}], 900)
        open(os.path.join(C.DATA_DIR, "themes.md"), "w").write(
            f"FORWARD THEMES (weekly scan, {pd.Timestamp.now().strftime('%Y-%m-%d')}) — research, not signals\n\n" + out)
        print("themes.md written")
    except Exception as e:
        print(f"themes failed: {type(e).__name__}")

if __name__ == "__main__":
    if "--themes" in sys.argv: themes()
    else: main()
