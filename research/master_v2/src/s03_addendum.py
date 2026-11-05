"""Addendum 1 tests A5-A8 and descriptive robustness D1-D9. Usage: python -I s03_addendum.py DATA_DIR REPO_DIR OUT_DIR"""
import sys, json, os
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from common import *

DATA, REPO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
D = Data(DATA)
BL1 = Boot(len(D.dates_l1), B=4000, seed=11)
BL2 = Boot(len(D.dates_l2), B=4000, seed=13)
res = {}

# ================= L1 panel: lowest-IBS pick =================
def pick_frame(thr=0.10):
    rows = []
    P = {t: D.daily[t] for t in TICK}
    for dt in D.dates_l1:
        cands = []
        for t in TICK:
            d = P[t]
            if dt in d.index and not np.isnan(d.at[dt, "ibs_prior"]) and d.at[dt, "ibs_prior"] < thr:
                cands.append((d.at[dt, "ibs_prior"], t))
        if not cands: continue
        cands.sort()
        rows.append(dict(date=dt, n_trig=len(cands), ticker=cands[0][1], ibs=cands[0][0],
                         others=[c[1] for c in cands[1:]]))
    return pd.DataFrame(rows)

mu_oc = {t: D.daily[t].oc.mean() for t in TICK}
def enrich(pf):
    out = []
    for r in pf.itertuples():
        d = D.daily[r.ticker]
        row = d.loc[r.date]
        oth = [D.daily[o].at[r.date, "oc"] - mu_oc[o] for o in r.others if r.date in D.daily[o].index]
        out.append(dict(date=r.date, ticker=r.ticker, n_trig=r.n_trig, ibs=r.ibs, oc=row.oc, excess=row.oc - mu_oc[r.ticker],
                        gap=row.gap, mae=row.mae, mfe=row.mfe,
                        vix=D.vix_prior.reindex([r.date], method="ffill").iloc[0],
                        above200=D.above200_prior.reindex([r.date], method="ffill").iloc[0],
                        others_excess=np.mean(oth) if oth else np.nan))
    return pd.DataFrame(out)

pf = enrich(pick_frame(0.10))
pf["val"] = pf.oc - COST
pf["val_ex"] = pf.excess - COST
print("=== Lowest-IBS pick (IBS<0.10), one ETF per day, L1 1993-2026 ===")
t_raw = BL1.test(pf, D.dates_l1, "val"); t_ex = BL1.test(pf, D.dates_l1, "val_ex")
print(f"days traded {len(pf)} of {len(D.dates_l1)} sessions ({len(pf)/len(D.dates_l1):.1%}); per year {len(pf)/ (len(D.dates_l1)/252):.1f}")
print(f"raw net {t_raw['mean']*1e4:+.2f} bp CI[{t_raw['lo']*1e4:+.2f},{t_raw['hi']*1e4:+.2f}] z={t_raw['z']:.2f}; excess-of-drift net {t_ex['mean']*1e4:+.2f} bp CI[{t_ex['lo']*1e4:+.2f},{t_ex['hi']*1e4:+.2f}]; hit {(pf.val>0).mean():.3f}")
res["pick_overall"] = dict(n=len(pf), raw_bp=t_raw["mean"]*1e4, ex_bp=t_ex["mean"]*1e4, hit=float((pf.val > 0).mean()))

# ---- A5 selection: lowest-IBS vs the other triggered ETFs
m = pf.dropna(subset=["others_excess"]).copy()
a5 = dict(n_days=len(m), pick_bp=m.excess.mean()*1e4, others_bp=m.others_excess.mean()*1e4)
m["val"] = m.excess - m.others_excess
t5 = BL1.test(m, D.dates_l1, "val")
a5.update(diff_bp=t5["mean"]*1e4, lo_bp=t5["lo"]*1e4, hi_bp=t5["hi"]*1e4, p1=t5["p1"])
print(f"\nA5 lowest-IBS vs other triggered ETFs: n={a5['n_days']} pick {a5['pick_bp']:+.2f} others {a5['others_bp']:+.2f} diff {a5['diff_bp']:+.2f} bp CI[{a5['lo_bp']:+.2f},{a5['hi_bp']:+.2f}] p1={a5['p1']:.3f}")
res["A5"] = a5

# ---- D1 threshold sweep
print("\nD1 threshold sweep (lowest-IBS pick; net bp raw / excess; n):")
for thr in [0.05, 0.10, 0.15, 0.20, 0.25]:
    x = enrich(pick_frame(thr)); x["val"] = x.oc - COST; x["val_ex"] = x.excess - COST
    print(f"  IBS<{thr:.2f}: n={len(x):5d}  raw {x.val.mean()*1e4:+6.2f}  excess {x.val_ex.mean()*1e4:+6.2f}  hit {(x.val>0).mean():.3f}")

# ---- D2 VIX bands, D3 trend, D4 gap, D5 decade, D6 ticker
def band(df, col, bins, labels):
    c = pd.cut(df[col], bins=bins, labels=labels, right=False)
    for lab in labels:
        x = df[c == lab]
        if len(x): print(f"  {lab:>10}: n={len(x):5d} raw {x.val.mean()*1e4:+7.2f} bp excess {x.val_ex.mean()*1e4:+7.2f} hit {(x.val>0).mean():.3f}")
print("\nD2 VIX prior-close bands:"); band(pf, "vix", [0, 15, 20, 25, 100], ["<15", "15-20", "20-25", ">=25"])
print("\nD3 trend (SPY prior close vs 200d):")
for lab, mk in [("above200", pf.above200 == True), ("below200", pf.above200 == False)]:
    x = pf[mk]; print(f"  {lab:>10}: n={len(x):5d} raw {x.val.mean()*1e4:+7.2f} excess {x.val_ex.mean()*1e4:+7.2f} hit {(x.val>0).mean():.3f}")
print("\nD4 gap vs prior close:")
for lab, mk in [("gap down<-0.15%", pf.gap < -0.0015), ("flat", pf.gap.abs() <= 0.0015), ("gap up>0.15%", pf.gap > 0.0015)]:
    x = pf[mk]; print(f"  {lab:>16}: n={len(x):5d} raw {x.val.mean()*1e4:+7.2f} excess {x.val_ex.mean()*1e4:+7.2f} hit {(x.val>0).mean():.3f}")
print("\nD5 by decade:")
pf["dec"] = (pf.date.dt.year // 5) * 5
for k, x in pf.groupby("dec"): print(f"  {k}-{k+4}: n={len(x):4d} raw {x.val.mean()*1e4:+7.2f} excess {x.val_ex.mean()*1e4:+7.2f} hit {(x.val>0).mean():.3f}")
print("\nD6 by ticker picked:")
for k, x in pf.groupby("ticker"): print(f"  {k}: n={len(x):4d} raw {x.val.mean()*1e4:+7.2f} excess {x.val_ex.mean()*1e4:+7.2f} hit {(x.val>0).mean():.3f}")
print("\nD7 excursions from the open on picked days (percent):")
for nm in ["mae", "mfe"]:
    q = np.percentile(pf[nm] * 100, [50, 75, 90, 95, 99]); print(f"  {nm}: p50 {q[0]:.2f} p75 {q[1]:.2f} p90 {q[2]:.2f} p95 {q[3]:.2f} p99 {q[4]:.2f}")
for lvl in [0.25, 0.5, 0.75, 1.0]:
    print(f"  share of days adverse excursion > {lvl}%: {(pf.mae*100 > lvl).mean():.3f}   favourable > {lvl}%: {(pf.mfe*100 > lvl).mean():.3f}")
print("\nD8 trades per calendar year (last 8 yrs):", pf.groupby(pf.date.dt.year).size().tail(8).to_dict())
pf.to_csv(f"{OUT}/ibs_pick_l1.csv", index=False)

# ================= A6 post-hoc: H2 follow, VIX>=20 =================
ev2 = pd.concat([trap_events(D.sess, t, follow=True) for t in TICK], ignore_index=True)
e = ev2[ev2.vix >= 20].copy(); e["val"] = e.excess - COST
t6 = BL2.test(e, D.dates_l2, "val")
A = e[e.date <= SPLIT_L2]; B = e[e.date > SPLIT_L2]
print(f"\nA6 (post-hoc) breakout-follow, VIX>=20: n={t6['n']} net {t6['mean']*1e4:+.2f} bp CI[{t6['lo']*1e4:+.2f},{t6['hi']*1e4:+.2f}] p1={t6['p1']:.3f} | halfA n={len(A)} {A.val.mean()*1e4:+.2f}  halfB n={len(B)} {B.val.mean()*1e4:+.2f}")
res["A6"] = dict(n=t6["n"], net_bp=t6["mean"]*1e4, lo=t6["lo"]*1e4, hi=t6["hi"]*1e4, p1=t6["p1"], A_bp=A.val.mean()*1e4, B_bp=B.val.mean()*1e4, nA=len(A), nB=len(B))

# ================= A7 scan =================
def slot_features(t, k):
    s = D.sess[t]
    minL = np.min([s[f"L{j}"].values for j in range(k + 1)], axis=0); maxH = np.max([s[f"H{j}"].values for j in range(k + 1)], axis=0)
    Ck = s[f"C{k}"].values
    ibs_d = (Ck - minL) / np.where(maxH - minL > 0, maxH - minL, np.nan)
    rk = s[f"C{k}"].values / s[f"O{k}"].values - 1
    dayret = Ck / s.prevC.values - 1
    gap = s.O0.values / s.prevC.values - 1
    fwd = s.C6.values / Ck - 1
    fwd = fwd - np.nanmean(fwd)
    f = pd.DataFrame({"date": s.index, "ticker": t, "fwd": fwd, "ret_up": rk > 0, "ret_dn": rk < 0,
                      "day_up": dayret > 0, "day_dn": dayret < 0,
                      "ibsd_lo": ibs_d < 0.15, "ibsd_mid": (ibs_d >= 0.15) & (ibs_d <= 0.85), "ibsd_hi": ibs_d > 0.85,
                      "rv_lo": s[f"RV{k}"].values < 0.75, "rv_mid": (s[f"RV{k}"].values >= 0.75) & (s[f"RV{k}"].values <= 1.33), "rv_hi": s[f"RV{k}"].values > 1.33,
                      "gap_up": gap > 0.0015, "gap_dn": gap < -0.0015, "gap_flat": np.abs(gap) <= 0.0015,
                      "vix_lo": s.vix_prior.values < 15, "vix_mid": (s.vix_prior.values >= 15) & (s.vix_prior.values < 20), "vix_hi": s.vix_prior.values >= 20,
                      "pibs_lo": s.ibs_prior.values < 0.10, "pibs_hi": s.ibs_prior.values > 0.90})
    return f
GROUPS = ["ret_up", "ret_dn", "day_up", "day_dn", "ibsd_lo", "ibsd_mid", "ibsd_hi", "rv_lo", "rv_mid", "rv_hi", "gap_up", "gap_dn", "gap_flat", "vix_lo", "vix_mid", "vix_hi", "pibs_lo", "pibs_hi"]
scan = []
for k in range(0, 6):
    fr = pd.concat([slot_features(t, k) for t in TICK], ignore_index=True).dropna(subset=["fwd"])
    for g in GROUPS:
        x = fr[fr[g]].copy(); x["val"] = x["fwd"]
        if len(x) < 30: continue
        r = BL2.test(x, D.dates_l2, "val")
        hA = x[x.date <= SPLIT_L2].val.mean(); hB = x[x.date > SPLIT_L2].val.mean()
        scan.append(dict(slot=k, group=g, n=r["n"], eff_bp=r["mean"] * 1e4, z=r["z"], p2=r["p2"], hA_bp=hA * 1e4, hB_bp=hB * 1e4))
sc = pd.DataFrame(scan)
sc["p_holm"] = holm(sc.p2.values)
print(f"\nA7 scan: {len(sc)} group tests; survivors at Holm<0.10: {(sc.p_holm < 0.10).sum()}; at raw p<0.05: {(sc.p2 < 0.05).sum()} (expected by chance ~{0.05*len(sc):.1f})")
print(sc.reindex(sc.z.abs().sort_values(ascending=False).index).head(12).round(3).to_string(index=False))
sc.to_csv(f"{OUT}/a7_scan.csv", index=False)
res["A7"] = dict(n_tests=len(sc), holm_survivors=int((sc.p_holm < 0.10).sum()), raw_p05=int((sc.p2 < 0.05).sum()))

# ================= A8 cross-instrument RVOL-normalcy (L3) =================
ev = pd.read_csv(f"{REPO}/results/exit_variants.csv")
print("\nA8 RVOL-normalcy across instruments (candidate R vs |RVOL-1|; Spearman, n, p two-sided):")
for variant in ["simple_tp1.2_mb20", "simple_tp2.5_mb20"]:
    for lab, mk in [("9 single names", ~ev.ticker.isin(TICK)), ("index trio", ev.ticker.isin(TICK))]:
        x = ev[(ev.exit_variant == variant) & ev.module.isin(["P1C", "P2"]) & mk].dropna(subset=["rvol", "R2"])
        rho, p = spearmanr(x.R2, (x.rvol - 1).abs())
        print(f"  {variant:18s} {lab:15s} n={len(x):4d} rho={rho:+.3f} p={p:.3f}")
        res[f"A8 {variant} {lab}"] = dict(n=len(x), rho=float(rho), p=float(p))

# ================= D9 L2 timing profile on IBS<0.10 days =================
print("\nD9 L2 timing on IBS<0.10 days (lowest-IBS pick among three ETFs), mean bp per hourly slot and cumulative from open:")
rows = []
for dt in D.dates_l2:
    c = []
    for t in TICK:
        s = D.sess[t]
        if dt in s.index and not np.isnan(s.at[dt, "ibs_prior"]) and s.at[dt, "ibs_prior"] < 0.10: c.append((s.at[dt, "ibs_prior"], t))
    if c:
        c.sort(); t = c[0][1]; s = D.sess[t].loc[dt]
        rows.append([s[f"C{k}"] / s[f"O{k}"] - 1 for k in range(7)] + [s["C6"] / s["O0"] - 1])
d9 = pd.DataFrame(rows, columns=[f"bar{k}" for k in range(7)] + ["oc"])
print(f"  n days = {len(d9)}  (of {len(D.dates_l2)} sessions)")
print("  per-slot mean bp:", {c: round(d9[c].mean() * 1e4, 1) for c in d9.columns})
print("  open->close mean bp:", round(d9.oc.mean() * 1e4, 1), " hit:", round((d9.oc > 0).mean(), 3))
json.dump(res, open(f"{OUT}/addendum_results.json", "w"), indent=1, default=float)
