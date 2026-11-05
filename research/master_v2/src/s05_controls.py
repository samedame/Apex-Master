"""Controls for the admitted IBS x VIX>=20 component (post-hoc validity checks, labelled as such). Usage: python -I s05_controls.py DATA_DIR OUT_DIR"""
import sys, json, os
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from common import *

DATA, OUT = sys.argv[1], sys.argv[2]
D = Data(DATA)
BL1 = Boot(len(D.dates_l1), B=5000, seed=31)
ORDER = ["SPY", "QQQ", "IWM"]; res = {}

# ---------- ticker-day panel ----------
rows = []
for t in TICK:
    d = D.daily[t].copy(); d["ticker"] = t; d["date"] = d.index
    d["vix"] = D.vix_prior.reindex(d.index, method="ffill")
    rows.append(d[["date", "ticker", "ibs_prior", "vix", "oc", "gap"]])
P = pd.concat(rows, ignore_index=True)
P = P[(P.date >= pd.Timestamp("1993-02-01"))].dropna(subset=["ibs_prior", "vix", "oc"])
P["val"] = P.oc - COST
hiV = P.vix >= 20; loIBS = P.ibs_prior < 0.10

# ---------- C1: IBS deciles-ish within each VIX regime ----------
bins = [0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0001]
labs = ["<.1", ".1-.2", ".2-.4", ".4-.6", ".6-.8", ".8-.9", ">=.9"]
P["ibsb"] = pd.cut(P.ibs_prior, bins=bins, labels=labs, right=False)
print("C1 mean open->close (bp, net of 2bp) by prior-day IBS bucket, pooled SPY/QQQ/IWM ticker-days:")
tab = {}
for lab, mk in [("VIX>=20", hiV), ("VIX<20", ~hiV)]:
    g = P[mk].groupby("ibsb", observed=True).val.agg(["count", "mean"]); g["mean_bp"] = g["mean"] * 1e4
    tab[lab] = g
    print(f"  {lab}: " + "  ".join(f"{i}: {r['mean_bp']:+.1f} (n={int(r['count'])})" for i, r in g.iterrows()))
allhi = P[hiV]; alllo = P[~hiV]
print(f"  all VIX>=20 ticker-days: {allhi.val.mean()*1e4:+.2f} bp (n={len(allhi)});  all VIX<20: {alllo.val.mean()*1e4:+.2f} bp (n={len(alllo)})")

# ---------- C2: within-VIX>=20 IBS effect; interaction ----------
G1 = P[hiV & loIBS]; G2 = P[hiV & ~loIBS]; G3 = P[~hiV & loIBS]; G4 = P[~hiV & ~loIBS]
m = [BL1.mean_dist(g, D.dates_l1, "val") for g in (G1, G2, G3, G4)]
within = m[0] - m[1]; did = (m[0] - m[1]) - (m[2] - m[3])
def ci(a): return f"[{np.nanpercentile(a,2.5)*1e4:+.1f},{np.nanpercentile(a,97.5)*1e4:+.1f}]"
print(f"\nC2 within VIX>=20: IBS<.1 {G1.val.mean()*1e4:+.1f} bp (n={len(G1)}) vs IBS>=.1 {G2.val.mean()*1e4:+.1f} bp (n={len(G2)}): diff {(G1.val.mean()-G2.val.mean())*1e4:+.1f} bp CI{ci(within)} p1={np.nanmean(within<=0):.4f}")
print(f"   within VIX<20:  IBS<.1 {G3.val.mean()*1e4:+.1f} bp (n={len(G3)}) vs IBS>=.1 {G4.val.mean()*1e4:+.1f} bp (n={len(G4)}): diff {(G3.val.mean()-G4.val.mean())*1e4:+.1f} bp")
print(f"   difference-in-differences {((G1.val.mean()-G2.val.mean())-(G3.val.mean()-G4.val.mean()))*1e4:+.1f} bp CI{ci(did)} p1={np.nanmean(did<=0):.4f}")
res["C2"] = dict(within_diff_bp=float((G1.val.mean()-G2.val.mean())*1e4), within_p1=float(np.nanmean(within <= 0)),
                 did_bp=float(((G1.val.mean()-G2.val.mean())-(G3.val.mean()-G4.val.mean()))*1e4), did_p1=float(np.nanmean(did <= 0)),
                 hi_all_bp=float(allhi.val.mean()*1e4), lo_all_bp=float(alllo.val.mean()*1e4))

# ---------- pick frame ----------
def pick_frame():
    rows = []
    for dt in D.dates_l1:
        for t in ORDER:
            d = D.daily[t]
            if dt in d.index and not np.isnan(d.at[dt, "ibs_prior"]) and d.at[dt, "ibs_prior"] < 0.10:
                r = d.loc[dt]; v = D.vix_prior.reindex([dt], method="ffill").iloc[0]
                rows.append(dict(date=dt, ticker=t, ibs=d.at[dt, "ibs_prior"], oc=r.oc, vix=v, mae=r.mae, mfe=r.mfe)); break
    return pd.DataFrame(rows)
pf = pick_frame(); pf["val"] = pf.oc - COST
hi = pf[pf.vix >= 20].copy(); hi["sigma"] = hi.vix / 100 / np.sqrt(252); hi["z"] = hi.oc / hi.sigma

# ---------- C3: IBS threshold & ticker within VIX>=20 ----------
print("\nC3 threshold sensitivity within VIX>=20 (liquidity-order pick):")
for thr in [0.05, 0.10, 0.15, 0.20, 0.30]:
    rows = []
    for dt in D.dates_l1:
        for t in ORDER:
            d = D.daily[t]
            if dt in d.index and not np.isnan(d.at[dt, "ibs_prior"]) and d.at[dt, "ibs_prior"] < thr:
                v = D.vix_prior.reindex([dt], method="ffill").iloc[0]
                if v >= 20: rows.append(d.at[dt, "oc"] - COST)
                break
    x = np.array(rows); print(f"  IBS<{thr:.2f}: n={len(x):4d} net {x.mean()*1e4:+.2f} bp hit {(x>0).mean():.3f}")
print("by ticker within VIX>=20 picks:", {t: (int((hi.ticker == t).sum()), round(hi[hi.ticker == t].val.mean() * 1e4, 1)) for t in ORDER})

# ---------- C4: reliability profile (empirical) ----------
print("\nC4 empirical reliability: P(close stays above open - d*sigma), sigma = VIX_prior/100/sqrt(252)")
allhi_sig = allhi.copy(); allhi_sig["z"] = allhi_sig.oc / (allhi_sig.vix / 100 / np.sqrt(252))
from math import erf, sqrt
def Phi(x): return 0.5 * (1 + erf(x / sqrt(2)))
print("   d      picks(IBS<.1,VIX>=20)   all VIX>=20 days   normal(0,1) benchmark")
for dd in [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]:
    print(f"  {dd:4.2f}   {(hi.z > -dd).mean():.3f} (n={len(hi)})          {(allhi_sig.z > -dd).mean():.3f}              {Phi(dd):.3f}")
print(f"  picks: mean z {hi.z.mean():+.3f}, median z {hi.z.median():+.3f}, p5 {hi.z.quantile(.05):+.2f}, p1 {hi.z.quantile(.01):+.2f}, worst {hi.z.min():+.2f}")
print(f"  all VIX>=20 days: mean z {allhi_sig.z.mean():+.3f}, p5 {allhi_sig.z.quantile(.05):+.2f}")

# ---------- C5: streaks and drawdown (VIX>=20 picks, one trade per day, bp and z-units) ----------
h = hi.sort_values("date"); v = (h.oc - COST).values * 1e4; eq = np.cumsum(v); dd = eq - np.maximum.accumulate(eq)
zz = (h.z - COST / h.sigma).values; zeq = np.cumsum(zz); zdd = zeq - np.maximum.accumulate(zeq)
def longest_loss(a):
    best = cur = 0
    for x in a:
        cur = cur + 1 if x < 0 else 0; best = max(best, cur)
    return best
print(f"\nC5 VIX>=20 picks: n={len(h)} sum {eq[-1]:.0f} bp; max drawdown {dd.min():.0f} bp ({zdd.min():.1f} z-units); longest losing streak {longest_loss(v)}; worst trade {v.min():.0f} bp ({zz.min():.2f} z); worst 10-trade window {pd.Series(v).rolling(10).sum().min():.0f} bp")
by_month = h.assign(ym=h.date.dt.to_period("M")).groupby("ym").apply(lambda x: ((x.oc - COST) * 1e4).sum())
print(f"   worst calendar month sum {by_month.min():.0f} bp ({by_month.idxmin()}); share of months positive {(by_month>0).mean():.2f} of {len(by_month)}")
res["C5"] = dict(n=len(h), max_dd_bp=float(dd.min()), max_dd_z=float(zdd.min()), loss_streak=int(longest_loss(v)), worst_bp=float(v.min()))

# ---------- C6: L2 entry-delay and per-slot profile on VIX>=20 pick days ----------
print("\nC6 L2 (2023-12..2026-11) VIX>=20 pick days: entry-delay sensitivity (bp, gross, hourly bars)")
rows = []
for r in pf[(pf.date >= D.dates_l2[0]) & (pf.vix >= 20)].itertuples():
    s = D.sess[r.ticker]
    if r.date in s.index:
        x = s.loc[r.date]; rows.append([x["C6"] / x[f"O{k}"] - 1 for k in range(0, 5)] + [x["C6"] / x["O0"] - 1])
dl = pd.DataFrame(rows, columns=["enter_0930", "enter_1030", "enter_1130", "enter_1230", "enter_1330", "oc"])
print("  n =", len(dl), " mean bp:", {c: round(dl[c].mean() * 1e4, 1) for c in dl.columns[:5]}, " hit(open entry):", round((dl.enter_0930 > 0).mean(), 3))

# ---------- C7: today ----------
print("\nC7 next-session state:")
print("  VIX last close", round(float(D.vix.iloc[-1]), 2), D.vix.index[-1].date())
for t in TICK:
    s = D.sess[t]; x = s.iloc[-1]
    H = max(x[f"H{k}"] for k in range(7)); L = min(x[f"L{k}"] for k in range(7)); C = x["C6"]
    print(f"  {t} session {s.index[-1].date()}: O {x['O0']:.2f} H {H:.2f} L {L:.2f} C {C:.2f}  IBS {(C-L)/(H-L):.3f}")
json.dump(res, open(f"{OUT}/controls_results.json", "w"), indent=1, default=float)
