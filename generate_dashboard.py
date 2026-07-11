"""Builds dashboard.html: latest snapshot + params + backtest summary injected into template.html."""
import json, os, os
from datetime import datetime
import config as C
import engine as E


def build(out="dashboard.html"):
    prices, meta = E.load_data()
    snap = E.snapshot(prices, meta)
    backtest = None
    if os.path.exists("backtest_summary.json"):
        with open("backtest_summary.json") as f:
            backtest = json.load(f)
    payload = {
        **snap,
        "indices": E.index_snapshot(),
        "microcaps": E.microcap_snapshot(),
        "radar": E.radar_snapshot(),
        "themes": (open(os.path.join(C.DATA_DIR, "themes.md")).read()
                   if os.path.exists(os.path.join(C.DATA_DIR, "themes.md")) else ""),
        "intel": (open(os.path.join(C.DATA_DIR, "intel.md")).read()
                  if os.path.exists(os.path.join(C.DATA_DIR, "intel.md")) else ""),
        "intel_rows": _intel_rows(snap),
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
        "sample": os.path.exists(os.path.join(C.DATA_DIR, "SAMPLE_FLAG")),
        "tuned": os.path.exists(C.TUNED_FILE),
        "params": {k: getattr(C, k) for k in
                   ["BUY_SCORE", "STRONG_BUY_SCORE", "WATCHLIST_SCORE", "EXIT_SCORE", "REDUCE_SCORE",
                    "STOP_ATR_MULT", "TRAIL_ATR_MULT", "TIME_STOP_BARS", "RISK_PER_TRADE",
                    "MAX_POSITIONS", "MAX_PER_SECTOR", "TOP_SECTORS", "MIN_TURNOVER_CR",
                    "EARNINGS_WARN_DAYS", "TARGET_R"]},
        "backtest": backtest,
    }
    with open("template.html") as f:
        html = f.read()

    def _py(o):  # numpy -> plain python for JSON
        import numpy as np
        if isinstance(o, np.integer): return int(o)
        if isinstance(o, np.floating): return float(o)
        if isinstance(o, np.bool_): return bool(o)
        return str(o)

    js = json.dumps(payload, default=_py).replace("</", "<\\/")  # keep </script> out of the payload
    with open(out, "w") as f:
        f.write(html.replace("__PAYLOAD__", js))
    print(f"Dashboard written: {out} ({len(snap['rows'])} stocks, regime {snap['regime']['light']})")
    snap["indices"] = payload["indices"]
    return snap


if __name__ == "__main__":
    build()


def _intel_rows(snap):
    """Join AI research with the system's own signals + technicals for the Intelligence tab."""
    path = os.path.join(C.DATA_DIR, "intel.json")
    if not os.path.exists(path):
        return []
    try:
        raw = json.load(open(path))
    except Exception:
        return []
    sig = {r["ticker"]: r for r in snap.get("rows", [])}
    mic = {m["ticker"] + ".NS": m for m in (snap.get("microcaps") or [])}
    out = []
    for c in raw:
        t = c["ticker"]; sym = t.replace(".NS", "")
        s_row = sig.get(sym) or sig.get(t)
        m_row = mic.get(t)
        if s_row:
            signal, close, trend = s_row.get("signal", "—"), s_row.get("price"), s_row.get("trend", "")
        elif m_row:
            signal, close, trend = "Watch-only", m_row.get("close"), m_row.get("trend", "")
        else:
            signal, close, trend = "Watch-only", None, ""
        out.append({"ticker": sym, "name": c.get("name", "")[:32], "sector": c.get("sector", ""),
                    "signal": signal, "close": close, "trend": trend,
                    "rs3": c.get("rs3"), "breakout": bool(c.get("breakout")),
                    "vol": c.get("vol_surge"), "ai": c.get("ai", "")})
    return out
