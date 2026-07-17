"""Market intelligence layer: Claude + web search reads news/themes for the day's
quant-flagged movers (funnel design — not all 1000 stocks). Needs ANTHROPIC_API_KEY.
Output: data/intel.md, injected into the daily brief by run_daily.py.
This is RESEARCH ASSISTANCE, not a validated signal — long-term buys still need human judgment."""
import os, sys, json, time
import pandas as pd, numpy as np
import requests as rq
import config as C

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("INTEL_MODEL", "claude-haiku-4-5-20251001")
MAX_STOCKS = int(os.environ.get("INTEL_MAX_STOCKS", "15"))

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
            hi100s = g.high.rolling(100).max().shift(1)
            hi100 = float(hi100s.iloc[-1])
            v20s = g.volume.rolling(20).mean()
            sigs = (c > hi100s) & (g.volume >= 1.5 * v20s) & (c.pct_change(63) > 0)
            fires = sigs[sigs].index
            camp_days = 999
            if len(fires):
                first = fires[0]
                for _k in range(1, len(fires)):
                    if (fires[_k] - fires[_k-1]).days > 45: first = fires[_k]
                camp_days = int((g.index[-1] - first).days) if hasattr(g,'index') else 999
            brk = bool(c.iloc[-1] > hi100)
            manual = str(meta.loc[t, "cap"]) == "Manual" if t in meta.index else False
            score = rs3 + (25 if brk else 0) + (15 if vr >= 2 else 0) + (40 if manual else 0) + (45 if (brk and camp_days <= 5) else 0)
            name = str(meta.loc[t, "name"]) if t in meta.index else t
            sector = str(meta.loc[t, "sector"]) if t in meta.index else "?"
            # light grade proxy for the cost filter (mirrors engine's A/B/C rule)
            _g = "C"
            if rs3 > 120: _g = "C"
            elif 25 <= rs3 <= 120 and vr >= 2.5: _g = "A"
            elif (25 <= rs3 <= 120) or vr >= 2.5: _g = "B"
            out[t] = {"ticker": t, "name": name, "sector": sector, "rs3": round(rs3, 0), "grade": _g,
                      "breakout": brk, "vol_surge": round(vr, 1), "score": score,
                      "close": round(float(c.iloc[-1]), 2),
                      "camp_days": camp_days if camp_days < 900 else None}
    ranked = sorted(out.values(), key=lambda r: -r["score"])
    # COST FILTER: only pay for AI on likely BUY candidates —
    # fresh/active breakouts graded A or B. Skip weak C-grades and extended non-breakout leaders.
    def _worth_research(r):
        if not r.get("breakout"):
            return False  # skip pure momentum leaders (extended, rarely fresh buys)
        g = r.get("grade")
        return g in ("A", "B")
    buy_candidates = [r for r in ranked if _worth_research(r)]
    picks = buy_candidates[:MAX_STOCKS]
    # guarantee: every FRESH breakout (<=5 days into its move) gets a seat regardless of rank
    have = {p["ticker"] for p in picks}
    for r in ranked[MAX_STOCKS + 15:]:
        if r.get("breakout") and (r.get("camp_days") is not None) and r["camp_days"] <= 5 and r["ticker"] not in have:
            picks.append(r); have.add(r["ticker"])
    # USER WATCHLIST: force-research these regardless of budget/rank; tag so UI shows a dedicated section
    wl_path = os.path.join(C.DATA_DIR, "user_watchlist.txt")
    if os.path.exists(wl_path):
        wl = [l.strip().upper() for l in open(wl_path) if l.strip() and not l.startswith("#")]
        for sym in wl:
            t = sym if sym.endswith(".NS") else sym + ".NS"
            if t in have:
                # already in funnel — just flag it as watchlist too
                for p in picks:
                    if p["ticker"] == t: p["user_watch"] = True
                continue
            if t in out:
                row = dict(out[t]); row["user_watch"] = True; picks.append(row); have.add(t)
            else:
                # not in scanned universe (e.g. off-index) — build a minimal row so it still gets researched
                picks.append({"ticker": t, "name": sym, "sector": "", "rs3": 0, "breakout": False,
                              "vol_surge": 0, "score": 0, "close": None, "user_watch": True})
                have.add(t)
    # guarantee: every displayed breakout gets researched, regardless of score rank
    try:
        import engine as _E
        have = {p["ticker"] for p in picks}
        for b in _E.radar_snapshot().get("breakouts", []):
            tk = b["ticker"] + ".NS"
            if tk not in have:
                picks.append({"ticker": tk, "name": b.get("name", ""), "sector": b.get("sector", ""),
                              "rs3": b.get("rs_3m", 0), "breakout": True,
                              "vol_surge": b.get("vol_x", 0), "score": 0,
                              "close": b.get("close"), "camp_days": b.get("camp_days")})
                have.add(tk)
    except Exception as e:
        print(f"breakout force-include skipped ({type(e).__name__})")
    # Fridays: also research the quiet accumulators (stories are cheapest before the breakout)
    if pd.Timestamp.now().weekday() == 4 or os.environ.get("INTEL_ACCUM") == "1":
        try:
            import engine as E
            accum = E.radar_snapshot().get("accum", [])[:8]
            have = {p["ticker"].replace(".NS", "") for p in picks}
            for a in accum:
                if a["ticker"] not in have:
                    picks.append({"ticker": a["ticker"] + ".NS", "name": a["name"], "sector": a["sector"],
                                  "rs3": a["rs_3m"], "breakout": False, "vol_surge": a.get("vol_trend", 0),
                                  "score": 0, "accum": True})
            print(f"Friday: +{len(picks)-len(ranked[:MAX_STOCKS])} accumulators added to research")
        except Exception as e:
            print(f"accum add skipped ({type(e).__name__})")
    # RESEARCH PRIORITY: main() spends the budget in list order, so put the picks we
    # actually promise to research at the front (otherwise high-score leaders can starve
    # them). 1) user-watchlist (forced regardless of budget/rank), 2) fresh A/B breakouts
    # (<=5 days into the move — the guarantee), 3) everyone else by score. Budget cap unchanged.
    def _prio(r):
        if r.get("user_watch"):
            return 0
        if (r.get("breakout") and r.get("grade") in ("A", "B")
                and r.get("camp_days") is not None and r["camp_days"] <= 5):
            return 1
        return 2
    picks.sort(key=lambda r: (_prio(r), -(r.get("score") or 0)))
    return picks

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
    # cache: reuse research done in the last 2 days if price hasn't moved >5%
    prev = {}
    try:
        for r0 in json.load(open(os.path.join(C.DATA_DIR, "intel.json"))):
            prev[r0.get("ticker")] = r0
    except Exception:
        pass
    today = pd.Timestamp.now()
    budget = MAX_STOCKS
    print(f"intel: {len(cands)} candidates, research budget {budget} via {MODEL}")
    sections = []
    for c in cands:
        p = prev.get(c["ticker"])
        fresh_cache = False
        if p and p.get("ai") and p.get("asof") and p.get("close"):
            try:
                age = (today - pd.Timestamp(p["asof"])).days
                drift = abs(c.get("close", 0) / float(p["close"]) - 1)
                fresh_cache = age <= 2 and drift < 0.05
            except Exception:
                fresh_cache = False
        if fresh_cache:
            c["ai"] = p["ai"]; c["asof"] = p["asof"]
            sym = c["ticker"].replace(".NS", "")
            sections.append(f"### {sym} — {c['name']} ({c['sector']}) · RS {c['rs3']:+.0f}% (cached {p['asof']})\n{c['ai']}\n")
            continue
        if budget <= 0:
            continue
        budget -= 1
        c["asof"] = today.strftime("%Y-%m-%d")
        sym = c["ticker"].replace(".NS", "")
        if c.get("accum"):
            q = (f"NSE-listed Indian stock {c['name']} (symbol {sym}, sector {c['sector']}) has been "
                 f"quiet/sideways for months but trading volume is quietly rising ({c['vol_surge']}x normal) — "
                 "possible accumulation before a move. First check screener.in/company/" + sym + "/ for fundamentals, "
                 "then search recent news + any upcoming catalysts (orders, results dates, capacity, policy). "
                 "Reply in EXACTLY this 5-line format, simple everyday English, each line under 18 words, "
                 "no markdown, no preamble:\n"
                 "CATALYST: <any brewing story/upcoming event with date, or 'nothing found — may be noise'>\n"
                 "THEME: <sector story if any, or 'stock-specific'>\n"
                 "FUNDAMENTALS: <one line with 1 number>\n"
                 "VERDICT: <Hard news | Mixed | Speculative>\n"
                 "CALL calibration: you are judging a STARTER-SIZE long-term buy (1/3 position, adding later), not all-in at a perfect price. "
                 "BUY-NOW = RARE highest-conviction (use sparingly, only when everything aligns): strong accelerating earnings, hard catalyst, sane valuation, and entry not overextended. "
                 "BUY-WORTHY = real earnings/order-backed story AND valuation acceptable for the growth (a big recent run does NOT disqualify if growth justifies it). "
                 "WAIT = good story but risk/reward genuinely poor right now (parabolic, results imminent, valuation far ahead of growth). "
                 "AVOID = no catalyst, weak/deteriorating fundamentals, or operator-pattern move. "
                 "Roughly a quarter of quality earnings-backed movers should merit BUY-WORTHY; BUY-NOW at most 1-2 per day across ALL stocks.\n"
                 "CALL: <BUY-NOW | BUY-WORTHY | WAIT | AVOID> — <under 10 words for a long-term buyer>\n"
                 "WHY_CALL: <2-3 short plain sentences: the case for this call, the main risk, and what would change your mind>")
        else:
            q = (f"NSE-listed Indian stock {c['name']} (symbol {sym}, sector {c['sector']}) is up strongly "
                 f"({c['rs3']:+.0f}% vs Nifty over 3 months"
             + (", fresh 100-day-high breakout" if c["breakout"] else "")
             + (f", volume {c['vol_surge']}x average" if c["vol_surge"] >= 2 else "") + "). "
             "First check screener.in/company/" + sym + "/ for fundamentals (sales & profit growth "
             "trend, ROE, debt, promoter holding change), then search recent news (last 3-4 weeks). "
             "Reply in EXACTLY this 5-line format and nothing else — no preamble, no headers, "
             "no ---, no markdown, no bold. Use simple everyday English a non-finance person understands. "
             "Each line under 18 words. Max 80 words total:\n"
             "CATALYST: <one sentence with the specific trigger and date>\n"
             "THEME: <one sentence: broader sector story + 1-2 peer tickers, or 'stock-specific'>\n"
             "FUNDAMENTALS: <one sentence: backed by earnings/orders (give 1 key number) or purely price action>\n"
             "VERDICT: <Hard news | Mixed | Speculative> — <under 8 words why>\n"
             "CALL calibration: you are judging a STARTER-SIZE long-term buy (1/3 position, adding later), not all-in at a perfect price. "
                 "BUY-NOW = RARE highest-conviction (use sparingly, only when everything aligns): strong accelerating earnings, hard catalyst, sane valuation, and entry not overextended. "
                 "BUY-WORTHY = real earnings/order-backed story AND valuation acceptable for the growth (a big recent run does NOT disqualify if growth justifies it). "
                 "WAIT = good story but risk/reward genuinely poor right now (parabolic, results imminent, valuation far ahead of growth). "
                 "AVOID = no catalyst, weak/deteriorating fundamentals, or operator-pattern move. "
                 "Roughly a quarter of quality earnings-backed movers should merit BUY-WORTHY; BUY-NOW at most 1-2 per day across ALL stocks.\n"
             "CALL: <BUY-NOW | BUY-WORTHY | WAIT | AVOID> — <under 10 words for a long-term buyer>\n"
             "WHY_CALL: <2-3 short plain sentences: the case for this call, the main risk, and what would change your mind>\n"
             "If nothing concrete found, CATALYST line says 'no clear public catalyst found' and CALL is AVOID or WAIT.")
        try:
            ans = ask_claude([{"role": "user", "content": q}], 520)
            sections.append(f"### {sym} — {c['name']} ({c['sector']}) · RS {c['rs3']:+.0f}%"
                            + (" · 🔶 breakout" if c["breakout"] else "") + f"\n{ans}\n")
            c["ai"] = ans
            print(f"  ✓ {sym}")
        except Exception as e:
            print(f"  ✗ {sym}: {type(e).__name__}")
        time.sleep(1)
    # structured THEME MAP: theme -> moved members + not-yet-moved peers (early entries)
    try:
        researched = [c for c in cands if c.get("ai")]
        listing = "; ".join(f"{c['ticker'].replace('.NS','')} ({c['sector']}, {'+' if c['rs3']>0 else ''}{c['rs3']:.0f}%)" for c in researched)
        tq = ("Today's strongest NSE movers: " + listing + ". "
              "Identify the 2-4 clearest investable THEMES linking several of them (e.g. rooftop solar capex, "
              "defence orders, infra capex). For each theme, also name 2-4 NSE-listed peers with direct exposure "
              "that have NOT moved much yet (the early entries). Reply ONLY a JSON array, no markdown: "
              '[{"theme":"...","why":"one plain sentence why money is flowing here now",'
              '"moved":["TICK1","TICK2"],"early":[{"ticker":"TICK","why":"under 8 words"}]}]')
        def _parse_themes(txt):
            txt = txt.strip().replace("```json", "").replace("```", "").strip()
            a, b = txt.find("["), txt.rfind("]")
            if a < 0 or b < 0:
                raise ValueError("no array")
            frag = txt[a:b+1]
            try:
                return json.loads(frag)
            except Exception:
                import re as _r
                frag2 = _r.sub(r",\s*([}\]])", r"\1", frag)   # trailing commas
                frag2 = frag2.replace("\n", " ")
                return json.loads(frag2)
        tm = None
        for _attempt in range(2):
            try:
                raw = ask_claude([{"role": "user",
                    "content": tq + ("" if _attempt == 0 else
                    " CRITICAL: output ONLY the raw JSON array starting with [ and ending with ]. "
                    "No prose, no markdown, no code fences, nothing else.")}], 900)
                tm = _parse_themes(raw)
                if isinstance(tm, list) and tm:
                    break
            except Exception as _e:
                last_err = _e; tm = None
        if isinstance(tm, list) and tm:
            # keep only well-formed entries
            clean = [t for t in tm if isinstance(t, dict) and t.get("theme")]
            json.dump(clean, open(os.path.join(C.DATA_DIR, "theme_map.json"), "w"))
            print(f"theme map: {len(clean)} themes")
        else:
            print(f"theme map failed after retry: {type(last_err).__name__ if 'last_err' in dir() else 'empty'}")
    except Exception as e:
        print(f"theme map failed: {type(e).__name__}")
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
    json.dump([{k: c.get(k) for k in ("ticker","name","sector","rs3","breakout","vol_surge","ai","close","asof","camp_days","user_watch")}
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


def portfolio():
    """Weekly AI review of holdings from tradelog.json (requires Cloud sync). Per holding:
    news, analyst view, fundamentals, technicals + CALL: HOLD/ADD/REDUCE/SELL."""
    if not API_KEY: print("portfolio: no key"); return
    lp = "tradelog.json"
    if not os.path.exists(lp):
        print("portfolio: tradelog.json not found (enable Cloud sync) — skipping"); return
    try:
        log = json.load(open(lp))
        entries = log.get("entries", log if isinstance(log, list) else [])
    except Exception as e:
        print(f"portfolio: log parse failed {type(e).__name__}"); return
    pos = {}
    for e in sorted(entries, key=lambda x: x.get("date", "")):
        t = str(e.get("ticker", "")).upper()
        if not t: continue
        q, px = float(e.get("qty", 0) or 0), float(e.get("price", 0) or 0)
        p = pos.setdefault(t, {"qty": 0.0, "cost": 0.0, "first": e.get("date", ""), "note": ""})
        if str(e.get("side")) == "Buy":
            if p["qty"] <= 0: p["first"] = e.get("date", "")
            p["cost"] += q * px; p["qty"] += q
            p["note"] = (e.get("note") or p["note"])[:60]
        else:
            avg = p["cost"] / p["qty"] if p["qty"] > 0 else px
            p["cost"] -= q * avg; p["qty"] -= q
    holdings = {t: p for t, p in pos.items() if p["qty"] > 0.5}
    if not holdings:
        print("portfolio: no open holdings"); return
    # price/technical context
    frames = {}
    for f in [C.PRICES_FILE, os.path.join(C.DATA_DIR, "mc_prices.csv")]:
        if os.path.exists(f):
            px = pd.read_csv(f, parse_dates=["date"])
            for t, g in px.groupby("ticker"):
                frames[t.replace(".NS", "")] = g.sort_values("date").set_index("date")
    prev = {}
    try:
        for r0 in json.load(open(os.path.join(C.DATA_DIR, "portfolio_review.json"))).get("rows", []):
            prev[r0.get("ticker")] = r0
    except Exception:
        pass
    prev_asof = None
    try:
        prev_asof = pd.Timestamp(json.load(open(os.path.join(C.DATA_DIR, "portfolio_review.json"))).get("asof"))
    except Exception:
        pass
    is_friday = pd.Timestamp.now().weekday() == 4
    out = []
    for t, p in holdings.items():
        avg = p["cost"] / p["qty"]
        g = frames.get(t)
        tech = ""
        last = None
        if g is not None and len(g) > 70:
            c = g.close; last = float(c.iloc[-1])
            ma50 = float(c.rolling(50).mean().iloc[-1])
            r3 = float(c.iloc[-1] / c.iloc[-64] - 1) * 100 if len(c) > 64 else 0
            tech = (f"price {last:.1f} vs your avg {avg:.1f} ({(last/avg-1)*100:+.1f}%), "
                    f"{'above' if last>ma50 else 'below'} its 50-day average, 3-month move {r3:+.0f}%")
        pr = prev.get(t)
        if pr and prev_asof is not None and not is_friday:
            try:
                age = (pd.Timestamp.now() - prev_asof).days
                drift = abs((last or 0) / float(pr.get("last") or last or 1) - 1) if last else 0
                if age <= 5 and drift < 0.07 and pr.get("ai"):
                    pr2 = dict(pr); pr2["qty"] = p["qty"]; pr2["avg"] = round(avg, 2); pr2["last"] = last
                    out.append(pr2); print(f"  ↻ {t} (cached review)"); continue
            except Exception:
                pass
        q = (f"I hold NSE stock {t} (bought around Rs {avg:.0f}, since {p['first']}"
             + (f", note: {p['note']}" if p['note'] else "") + f"). Current technicals: {tech or 'n/a'}. "
             "Search recent news (last 4-6 weeks) and what analysts/brokerages currently say. "
             "Reply in EXACTLY this 5-line format, simple everyday English, each line under 18 words, "
             "no markdown, no preamble:\n"
             "NEWS: <most important recent development with date>\n"
             "ANALYSTS: <what brokerages/analysts say now: targets/upgrades/downgrades, or 'no recent coverage found'>\n"
             "FUNDAMENTALS: <one line: growth/valuation health with 1 number>\n"
             "TECHNICALS: <one line restating the technical picture simply>\n"
             "CALL: <HOLD | ADD | REDUCE | SELL> — <under 10 words why, for a long-term holder>")
        try:
            ans = ask_claude([{"role": "user", "content": q}], 520)
            m = None
            import re as _re
            mm = _re.search(r"CALL:\s*(HOLD|ADD|REDUCE|SELL)\s*[—-]?\s*(.*)", ans, _re.I)
            call, why = (mm.group(1).upper(), mm.group(2).strip()[:80]) if mm else (None, "")
            body = _re.sub(r"\n?CALL:.*", "", ans).strip()
            out.append({"ticker": t, "qty": p["qty"], "avg": round(avg, 2), "since": p["first"],
                        "last": last, "call": call, "why": why, "ai": body})
            print(f"  ✓ {t} -> {call}")
        except Exception as e:
            print(f"  ✗ {t}: {type(e).__name__}")
        time.sleep(1)
    json.dump({"asof": pd.Timestamp.now().strftime("%Y-%m-%d"), "rows": out},
              open(os.path.join(C.DATA_DIR, "portfolio_review.json"), "w"))
    md = [f"# Weekly portfolio review — {pd.Timestamp.now().strftime('%Y-%m-%d')}\n"]
    for r in out:
        md.append(f"### {r['ticker']} — {r['call'] or '?'} ({r['why']})\n{r['ai']}\n")
    open(os.path.join(C.DATA_DIR, "portfolio_review.md"), "w").write("\n".join(md))
    print(f"portfolio review written ({len(out)} holdings)")

if __name__ == "__main__":
    if "--themes" in sys.argv: themes()
    elif "--portfolio" in sys.argv: portfolio()
    else: main()
