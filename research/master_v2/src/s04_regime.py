"""Addendum 2 tests B1-B9. Usage: python -I s04_regime.py DATA_DIR OUT_DIR"""
import sys, json, os
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from common import *

DATA, OUT = sys.argv[1], sys.argv[2]
D = Data(DATA)
BL1 = Boot(len(D.dates_l1), B=5000, seed=21)
ORDER = ["SPY", "QQQ", "IWM"]
mu_oc = {t: D.daily[t].oc.mean() for t in TICK}

def pick_frame(dates, thr=0.10):
    rows = []
    for dt in dates:
        for t in ORDER:
            d = D.daily[t]
            if dt in d.index and not np.isnan(d.at[dt, "ibs_prior"]) and d.at[dt, "ibs_prior"] < thr:
                r = d.loc[dt]
                rows.append(dict(date=dt, ticker=t, ibs=d.at[dt, "ibs_prior"], oc=r.oc, excess=r.oc - mu_oc[t], gap=r.gap,
                                 vix=D.vix_prior.reindex([dt], method="ffill").iloc[0])); break
    return pd.DataFrame(rows)

pf = pick_frame(D.dates_l1)
pf["val"] = pf.oc - COST
pf["year"] = pf.date.dt.year
print(f"pick frame (liquidity order): {len(pf)} trades over {len(D.dates_l1)} sessions; raw net {pf.val.mean()*1e4:+.2f} bp")
res = {}

# ---------------- B1 ----------------
hi = pf[pf.vix >= 20]; lo = pf[pf.vix < 20]
t1 = BL1.test(hi, D.dates_l1, "val")
hA = hi[hi.date <= SPLIT_L1]; hB = hi[hi.date > SPLIT_L1]
print(f"\nB1 VIX>=20: n={t1['n']} net {t1['mean']*1e4:+.2f} bp CI[{t1['lo']*1e4:+.2f},{t1['hi']*1e4:+.2f}] p1={t1['p1']:.4f} hit {(hi.val>0).mean():.3f} | <=2012 n={len(hA)} {hA.val.mean()*1e4:+.2f}  >=2013 n={len(hB)} {hB.val.mean()*1e4:+.2f}")
print(f"   VIX<20: n={len(lo)} net {lo.val.mean()*1e4:+.2f} bp hit {(lo.val>0).mean():.3f}")
res["B1"] = dict(n=t1["n"], net_bp=t1["mean"]*1e4, lo=t1["lo"]*1e4, hi=t1["hi"]*1e4, p1=t1["p1"], hit=float((hi.val > 0).mean()),
                 A_n=len(hA), A_bp=hA.val.mean()*1e4, B_n=len(hB), B_bp=hB.val.mean()*1e4, lo20_bp=lo.val.mean()*1e4, lo20_n=len(lo))

# ---------------- B2 ----------------
pf = pf.sort_values("date").reset_index(drop=True)
THR = [15, 18, 20, 22, 25]
def stat(vix, val):
    best = -np.inf; arg = None
    for th in THR:
        a = val[vix >= th]; b = val[vix < th]
        if len(a) >= 50 and len(b) >= 50:
            s = a.mean() - b.mean()
            if s > best: best, arg = s, th
    return best, arg
obs, obs_thr = stat(pf.vix.values, pf.val.values)
d20 = hi.val.mean() - lo.val.mean()
rng = np.random.default_rng(99)
n = len(pf); null = []
for _ in range(5000):
    off = int(rng.integers(50, n - 50))
    null.append(stat(np.roll(pf.vix.values, off), pf.val.values)[0])
null = np.array(null)
p_b2 = float((null >= obs).mean())
print(f"\nB2 heterogeneity: diff at 20 = {d20*1e4:+.2f} bp; best-threshold stat {obs*1e4:+.2f} bp at VIX>={obs_thr}; max-over-thresholds circular-shift p = {p_b2:.4f}")
res["B2"] = dict(diff20_bp=d20*1e4, best_bp=obs*1e4, best_thr=obs_thr, p=p_b2)

# Holm over B1 (p1) and B2
ph = holm([t1["p1"], p_b2]); print(f"Holm-adjusted: B1 {ph[0]:.4f}  B2 {ph[1]:.4f}")
res["holm"] = dict(B1=float(ph[0]), B2=float(ph[1]))

# ---------------- B3 vol-normalised ----------------
pf["z"] = pf.oc / (pf.vix / 100 / np.sqrt(252))
print("\nB3 vol-normalised open->close (in units of VIX-implied daily sd) by band:")
for lab, lo_, hi_ in [("<15", 0, 15), ("15-20", 15, 20), ("20-25", 20, 25), (">=25", 25, 100)]:
    x = pf[(pf.vix >= lo_) & (pf.vix < hi_)]
    print(f"  {lab:>6}: n={len(x):4d} mean z {x.z.mean():+.3f}  mean bp {x.oc.mean()*1e4:+.1f}  sd(bp) {x.oc.std()*1e4:.0f}")

# ---------------- B4 L2 ----------------
print("\nB4 L2 replication (2023-12..2026-11):")
p2 = pick_frame(D.dates_l2)
for lab, x in [("VIX>=20", p2[p2.vix >= 20]), ("VIX<20", p2[p2.vix < 20])]:
    print(f"  {lab}: n={len(x)} mean oc {x.oc.mean()*1e4 if len(x) else float('nan'):+.1f} bp  hit {(x.oc>0).mean() if len(x) else float('nan'):.3f}")
print("  L2 sessions with VIX>=20 prior:", int((D.vix_prior.reindex(D.dates_l2, method='ffill') >= 20).sum()), "of", len(D.dates_l2))

# ---------------- B5 walk-forward ----------------
years = sorted(pf.year.unique()); wf = []; chosen = {}
for Y in years:
    if Y < 2000: continue
    tr = pf[pf.year < Y]; best = None
    for th in [0, 15, 18, 20, 22, 25]:
        x = tr[tr.vix >= th]
        if len(x) >= 40 and (best is None or x.val.mean() > best[1]): best = (th, x.val.mean())
    chosen[Y] = best[0] if best else None
    if best is None: continue
    x = pf[(pf.year == Y) & (pf.vix >= best[0])]
    wf.append(x)
wfd = pd.concat(wf)
fixed = pf[(pf.year >= 2000) & (pf.vix >= 20)]; alw = pf[pf.year >= 2000]
for lab, x in [("walk-forward threshold", wfd), ("fixed VIX>=20", fixed), ("always (no regime rule)", alw)]:
    tt = BL1.test(x, D.dates_l1, "val")
    print(f"B5 {lab:26s}: n={len(x):4d} net {x.val.mean()*1e4:+6.2f} bp CI[{tt['lo']*1e4:+.2f},{tt['hi']*1e4:+.2f}] hit {(x.val>0).mean():.3f}")
print("  thresholds chosen by year:", {k: v for k, v in list(chosen.items())[-10:]})
res["B5"] = dict(wf_n=len(wfd), wf_bp=wfd.val.mean()*1e4, fixed_bp=fixed.val.mean()*1e4, always_bp=alw.val.mean()*1e4)

# ---------------- B6 costs ----------------
print("\nB6 cost scenarios on VIX>=20 picks (net mean bp):")
for c in [2, 5, 10, 20]:
    print(f"  cost {c:2d} bp RT: {(hi.oc.mean() - c/1e4)*1e4:+.2f} bp")
print(f"  breakeven round-trip cost ~ {hi.oc.mean()*1e4:.1f} bp")

# ---------------- B7 crisis dependence ----------------
by = hi.groupby("year").val.agg(["count", "sum", "mean"]); by["sum_bp"] = by["sum"] * 1e4; by["mean_bp"] = by["mean"] * 1e4
print("\nB7 VIX>=20 picks by year (n, sum bp, mean bp):")
print(by[["count", "sum_bp", "mean_bp"]].round(1).T.to_string())
best2 = by["sum"].sort_values(ascending=False).index[:2].tolist()
ex1 = hi[~hi.year.isin(best2)]; ex2 = hi[~hi.year.isin([2008, 2020, 2022])]
# year-block bootstrap
yrs = by.index.values; rb = np.random.default_rng(5); bm = []
sumy = hi.groupby("year").val.sum().reindex(yrs).values; cnty = hi.groupby("year").val.count().reindex(yrs).values
for _ in range(5000):
    ii = rb.integers(0, len(yrs), len(yrs)); bm.append(sumy[ii].sum() / max(1, cnty[ii].sum()))
print(f"  excluding best two years {best2}: n={len(ex1)} net {ex1.val.mean()*1e4:+.2f} bp")
print(f"  excluding 2008, 2020, 2022: n={len(ex2)} net {ex2.val.mean()*1e4:+.2f} bp")
print(f"  year-block bootstrap 95% CI of mean: [{np.percentile(bm,2.5)*1e4:+.2f}, {np.percentile(bm,97.5)*1e4:+.2f}] bp; share of positive years: {(by['sum']>0).mean():.2f} ({int((by['sum']>0).sum())} of {len(by)})")
res["B7"] = dict(ex_best2_bp=ex1.val.mean()*1e4, ex_crisis_bp=ex2.val.mean()*1e4, yr_ci=[float(np.percentile(bm, 2.5)*1e4), float(np.percentile(bm, 97.5)*1e4)],
                 pos_years=int((by['sum'] > 0).sum()), n_years=len(by))

# ---------------- B8 L3 window count ----------------
w0, w1 = pd.Timestamp("2026-08-12"), pd.Timestamp("2026-11-04")
win = pick_frame(pd.DatetimeIndex([d for d in D.dates_l1 if w0 <= d <= w1]))
print(f"\nB8 Master window (2026-08-12..11-04): IBS<0.10 pick days = {len(win)}; with VIX>=20: {int((win.vix>=20).sum())}")
print("  prior-close VIX range in window:", round(D.vix_prior.loc[w0:w1].min(), 1), "-", round(D.vix_prior.loc[w0:w1].max(), 1))

# ---------------- B9 today ----------------
print("\nB9 latest state (data through", D.daily['SPY'].index[-1].date(), "):")
print("  VIX last close:", round(float(D.vix.iloc[-1]), 2), "on", D.vix.index[-1].date())
for t in TICK:
    d = D.daily[t]; print(f"  {t}: last-session IBS {d.ibs.iloc[-1]:.3f}  (C {d.Close.iloc[-1]:.2f}, H {d.High.iloc[-1]:.2f}, L {d.Low.iloc[-1]:.2f}, {d.index[-1].date()})")
pf.to_csv(f"{OUT}/ibs_pick_order_l1.csv", index=False)
json.dump(res, open(f"{OUT}/regime_results.json", "w"), indent=1, default=float)
