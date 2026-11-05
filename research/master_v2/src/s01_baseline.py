"""Reproduce the existing Apex Master numbers from its own result files and pin down its selection rules."""
import sys
import numpy as np, pandas as pd

REPO = sys.argv[1]
ev = pd.read_csv(f"{REPO}/results/exit_variants.csv")
print("cols:", list(ev.columns))
print("variants:", sorted(ev.exit_variant.unique()))
ev["ts"] = pd.to_datetime(ev["ts"], utc=True)

def stats(r):
    r = np.asarray(r, float)
    pf = r[r > 0].sum() / max(1e-9, -r[r < 0].sum())
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(eq)).min()
    return dict(n=len(r), win=round((r > 0).mean(), 3), mean=round(r.mean(), 3), pf=round(pf, 2), dd=round(dd, 1))

for variant in ["simple_tp1.2_mb20", "simple_tp2.5_mb20"]:
    d = ev[(ev.exit_variant == variant) & ev.module.isin(["P1C", "P2"]) & ev.ticker.isin(["SPY", "QQQ", "IWM"])].copy()
    d["rvol_dist"] = (d.rvol - 1).abs()
    d["prio"] = d.module.map({"P1C": 0, "P2": 1})
    print(f"\n== {variant}: candidates {len(d)} over {d.date.nunique()} sessions")
    hind = d.sort_values(["date", "prio", "rvol_dist"]).groupby("date").head(1)
    print("hindsight pick :", stats(hind.R2))
    ff = d.sort_values(["date", "ts", "prio"]).groupby("date").head(1)
    print("first_fire     :", stats(ff.R2))
    print("all candidates :", stats(d.R2))
    # random pick, one per day
    rng = np.random.default_rng(0)
    groups = [g.R2.values for _, g in d.groupby("date")]
    sims = np.array([np.mean([rng.choice(g) for g in groups]) for _ in range(5000)])
    print("random pick mean R: mean %.3f  p5 %.3f  p95 %.3f ; hindsight beats %.1f%% ; first_fire beats %.1f%%" % (
        sims.mean(), np.percentile(sims, 5), np.percentile(sims, 95),
        (sims < hind.R2.mean()).mean() * 100, (sims < ff.R2.mean()).mean() * 100))
    print("days with >1 candidate:", sum(len(g) > 1 for g in groups), "of", len(groups))
    print("first_fire by module:", ff.groupby("module").R2.agg(["count", "mean"]).round(3).to_dict())
