"""Builds dashboard.html: latest snapshot + params + backtest summary injected into template.html."""
import json, os
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
