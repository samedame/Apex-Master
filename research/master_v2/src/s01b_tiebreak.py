import sys
import numpy as np, pandas as pd
REPO = sys.argv[1]
ev = pd.read_csv(f"{REPO}/results/exit_variants.csv")
ev["ts"] = pd.to_datetime(ev["ts"], utc=True)
def stats(r):
    r = np.asarray(r, float); pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum())
    eq = np.cumsum(r); dd = (eq - np.maximum.accumulate(eq)).min()
    return f"n={len(r)} win={(r>0).mean():.3f} mean={r.mean():+.3f} pf={pf:.2f} dd={dd:.1f}"
for variant in ["simple_tp1.2_mb20", "simple_tp2.5_mb20"]:
    d = ev[(ev.exit_variant == variant) & ev.module.isin(["P1C", "P2"]) & ev.ticker.isin(["SPY", "QQQ", "IWM"])].copy()
    d["rvol_dist"] = (d.rvol - 1).abs(); d["prio"] = d.module.map({"P1C": 0, "P2": 1})
    print("==", variant)
    for name, keys in {
        "ts,prio": ["date", "ts", "prio"],
        "ts,rvol_dist": ["date", "ts", "rvol_dist"],
        "ts,prio,rvol_dist": ["date", "ts", "prio", "rvol_dist"],
        "prio,ts": ["date", "prio", "ts"],
        "prio,ts,rvol_dist": ["date", "prio", "ts", "rvol_dist"],
        "ts,ticker": ["date", "ts", "ticker"],
    }.items():
        pick = d.sort_values(keys).groupby("date").head(1)
        print(f"{name:20s}", stats(pick.R2))
    # how many days have a tie at the earliest ts
    first = d.sort_values(["date", "ts"]).groupby("date")
    ties = sum((g.ts == g.ts.min()).sum() > 1 for _, g in first)
    print("days with a same-bar tie at the earliest timestamp:", ties)
