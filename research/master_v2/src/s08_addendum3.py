"""Addendum 3: A1 time out-of-sample, A2 asset out-of-sample, A3 second tier, A4 sizing.
Usage: python -I s08_addendum3.py DATA_DIR EXTRA_DATA_DIR OUT_DIR   (EXTRA_DATA_DIR holds DIA_1d.csv etc.)"""
import sys, json, os
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from common import *

DATA, EXTRA, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
D = Data(DATA)
ORDER = ["SPY", "QQQ", "IWM"]; res = {}
YEAR_B = 5000

def load(path):
    d = pd.read_csv(path, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_localize(None).normalize()
    d = d[~d.index.duplicated()].sort_index()
    for c in ["Open", "High", "Low", "Close"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    rng = (d.High - d.Low).replace(0, np.nan)
    d["ibs"] = (d.Close - d.Low) / rng
    d["ibs_prior"] = d["ibs"].shift(1)
    d["oc"] = d.Close / d.Open - 1
    return d

def vix_prior_on(idx):
    return D.vix_prior.reindex(idx, method="ffill")

def ci(m): return f"[{np.nanpercentile(m,2.5)*1e4:+.1f},{np.nanpercentile(m,97.5)*1e4:+.1f}]"

# ================= A1: time out-of-sample, S&P 500 index close-to-close =================
g = load(f"{DATA}/GSPC_1d.csv")
lr = np.log(g.Close).diff()
g["rv21"] = lr.rolling(21).std() * np.sqrt(252) * 100
g["rv21_p"] = g["rv21"]                          # RV21 ending the signal day (known at that close)
g["c2c_next"] = g.Close.shift(-1) / g.Close - 1  # buy at this close, sell at the next close
g["vix_sig"] = D.vix.reindex(g.index)            # VIX close ON the signal day (known at that close)
cal = g.loc["1990-01-01":"2026-11-03"].dropna(subset=["rv21", "vix_sig"])
share = (cal.vix_sig >= 20).mean()
q = float(np.quantile(cal.rv21, 1 - share))
agree = float(((cal.rv21 >= q) == (cal.vix_sig >= 20)).mean())
print(f"A1 proxy: share of 1990-2026 days with VIX>=20 = {share:.3f}; RV21 threshold q = {q:.2f}; classification agreement = {agree:.3f}")
res["A1_proxy"] = dict(share=float(share), q=q, agreement=agree)
g["val"] = g.c2c_next - COST
d70 = g.loc["1970-01-02":"1992-12-31"].dropna(subset=["ibs", "rv21", "val"]).copy(); d70["date"] = d70.index
sig = d70[(d70.ibs < 0.10) & (d70.rv21 >= q)]; calm = d70[(d70.ibs < 0.10) & (d70.rv21 < q)]
dates70 = d70.index
B70 = Boot(len(dates70), B=YEAR_B, seed=81)
t_a1a = B70.test(sig, dates70, "val"); t_a1b = B70.test(calm, dates70, "val")
base70 = d70.val.mean()
print(f"A1a 1970-92 IBS<.10 & RV21>=q: n={t_a1a['n']} net {t_a1a['mean']*1e4:+.2f} bp CI[{t_a1a['lo']*1e4:+.1f},{t_a1a['hi']*1e4:+.1f}] p1={t_a1a['p1']:.4f} hit {(sig.val>0).mean():.3f} (all days {base70*1e4:+.2f} bp)")
print(f"A1b 1970-92 IBS<.10 & RV21<q: n={t_a1b['n']} net {t_a1b['mean']*1e4:+.2f} bp CI[{t_a1b['lo']*1e4:+.1f},{t_a1b['hi']*1e4:+.1f}]")
hA = sig[sig.index <= "1981-12-31"]; hB = sig[sig.index > "1981-12-31"]
print(f"   halves: 1970-81 n={len(hA)} {hA.val.mean()*1e4:+.1f} bp | 1982-92 n={len(hB)} {hB.val.mean()*1e4:+.1f} bp")
# A1c reference: same variant on SPY 1993-2026 with VIX>=20 (VIX close on the signal day)
spy = D.daily["SPY"].copy(); spy["c2c_next"] = spy.Close.shift(-1) / spy.Close - 1
spy["vix_sig"] = D.vix.reindex(spy.index)
r = spy.dropna(subset=["ibs", "c2c_next", "vix_sig"]); r = r[r.index >= "1993-02-01"]
ref = r[(r.ibs < 0.10) & (r.vix_sig >= 20)]; refc = r[(r.ibs < 0.10) & (r.vix_sig < 20)]
print(f"A1c reference SPY 1993-2026 close-to-close: VIX>=20 n={len(ref)} {(ref.c2c_next.mean()-COST)*1e4:+.2f} bp | VIX<20 n={len(refc)} {(refc.c2c_next.mean()-COST)*1e4:+.2f} bp | all days {(r.c2c_next.mean()-COST)*1e4:+.2f}")
res["A1"] = dict(a=dict(n=t_a1a["n"], mean_bp=t_a1a["mean"]*1e4, lo=t_a1a["lo"]*1e4, hi=t_a1a["hi"]*1e4, p1=t_a1a["p1"], hit=float((sig.val > 0).mean()),
                        h1_bp=float(hA.val.mean()*1e4), h1_n=len(hA), h2_bp=float(hB.val.mean()*1e4), h2_n=len(hB)),
                 b=dict(n=t_a1b["n"], mean_bp=t_a1b["mean"]*1e4), ref_hi_bp=float((ref.c2c_next.mean()-COST)*1e4), ref_hi_n=len(ref),
                 ref_lo_bp=float((refc.c2c_next.mean()-COST)*1e4), ref_all_bp=float((r.c2c_next.mean()-COST)*1e4))

# ================= A2: asset out-of-sample =================
ETFS = ["DIA", "MDY", "XLF", "XLK", "XLE", "XLV", "XLP", "XLU", "XLI", "XLB", "XLY", "EWJ", "EWG", "EWU", "EWZ", "EEM", "EFA", "EWC", "EWA", "EWH"]
US = {"DIA", "MDY", "XLF", "XLK", "XLE", "XLV", "XLP", "XLU", "XLI", "XLB", "XLY"}
rows = []
for t in ETFS:
    d = load(f"{EXTRA}/{t}_1d.csv"); d = d[d.index >= "1995-01-01"].copy()
    d["vix"] = vix_prior_on(d.index); d["ticker"] = t; d["date"] = d.index
    rows.append(d[["date", "ticker", "ibs_prior", "vix", "oc"]])
P = pd.concat(rows, ignore_index=True).dropna(subset=["ibs_prior", "vix", "oc"]); P["val"] = P.oc - COST
P["grp"] = np.where(P.ticker.isin(US), "US", "intl")
alld = pd.DatetimeIndex(sorted(P.date.unique()))
B2 = Boot(len(alld), B=YEAR_B, seed=82)
hiV = P.vix >= 20; lo = P.ibs_prior < 0.10
a2a = P[hiV & lo]; t_a2a = B2.test(a2a, alld, "val")
print(f"\nA2a other ETFs, VIX>=20 & IBS<.10: n={t_a2a['n']} net {t_a2a['mean']*1e4:+.2f} bp CI[{t_a2a['lo']*1e4:+.1f},{t_a2a['hi']*1e4:+.1f}] p1={t_a2a['p1']:.4f} hit {(a2a.val>0).mean():.3f}")
d_b = B2.diff(P[hiV & lo], P[hiV & ~lo], alld, "val")
print(f"A2b within VIX>=20: IBS<.10 {d_b['mA']*1e4:+.1f} (n={d_b['nA']}) vs rest {d_b['mB']*1e4:+.1f} (n={d_b['nB']}): diff {d_b['diff']*1e4:+.1f} CI[{d_b['lo']*1e4:+.1f},{d_b['hi']*1e4:+.1f}] p1={d_b['p1']:.4f}")
a2c = P[~hiV & lo]; print(f"A2c VIX<20 & IBS<.10: n={len(a2c)} net {a2c.val.mean()*1e4:+.2f} bp   (all VIX>=20 ticker-days {P[hiV].val.mean()*1e4:+.2f} bp, n={int(hiV.sum())})")
sub = {}
for lab, m in [("US", a2a.grp == "US"), ("intl", a2a.grp == "intl"), ("<=2012", a2a.date <= SPLIT_L1), (">2012", a2a.date > SPLIT_L1)]:
    x = a2a[m]; sub[lab] = (len(x), float(x.val.mean() * 1e4));
print("A2d subgroups (n, bp):", {k: (v[0], round(v[1], 1)) for k, v in sub.items()})
bt = {t: (int(len(a2a[a2a.ticker == t])), round(float(a2a[a2a.ticker == t].val.mean() * 1e4), 1)) for t in ETFS if (a2a.ticker == t).sum() > 0}
print("   by ticker (n, bp):", bt)
res["A2"] = dict(a=dict(n=t_a2a["n"], mean_bp=t_a2a["mean"]*1e4, lo=t_a2a["lo"]*1e4, hi=t_a2a["hi"]*1e4, p1=t_a2a["p1"], hit=float((a2a.val > 0).mean())),
                 b=dict(diff_bp=d_b["diff"]*1e4, lo=d_b["lo"]*1e4, hi=d_b["hi"]*1e4, p1=d_b["p1"], hi_ibs_bp=d_b["mA"]*1e4, rest_bp=d_b["mB"]*1e4),
                 c=dict(n=len(a2c), mean_bp=float(a2c.val.mean()*1e4)), allhi_bp=float(P[hiV].val.mean()*1e4), subgroups=sub, by_ticker=bt)

# ================= A3: tier 2 =================
def pick_tiers(dates):
    rows = []
    for d0 in dates:
        t1 = None
        for t in ORDER:
            dd = D.daily[t]
            if d0 in dd.index and not np.isnan(dd.at[d0, "ibs_prior"]) and dd.at[d0, "ibs_prior"] < 0.10:
                t1 = t; break
        tier = 1 if t1 else 0; tk = t1
        if t1 is None:
            for t in ORDER:
                dd = D.daily[t]
                if d0 in dd.index and not np.isnan(dd.at[d0, "ibs_prior"]) and 0.10 <= dd.at[d0, "ibs_prior"] < 0.20:
                    tier, tk = 2, t; break
        if tk:
            dd = D.daily[tk]; v = D.vix_prior.reindex([d0], method="ffill").iloc[0]
            rows.append(dict(date=d0, ticker=tk, tier=tier, ibs=dd.at[d0, "ibs_prior"], vix=v, oc=dd.at[d0, "oc"]))
    return pd.DataFrame(rows)
tf = pick_tiers(D.dates_l1); tf["val"] = tf.oc - COST; tf["year"] = tf.date.dt.year
t1 = tf[(tf.tier == 1) & (tf.vix >= 20)]; t2 = tf[(tf.tier == 2) & (tf.vix >= 20)]
BL1 = Boot(len(D.dates_l1), B=YEAR_B, seed=83)
tt = BL1.test(t2, D.dates_l1, "val"); yrs = (D.dates_l1[-1] - D.dates_l1[0]).days / 365.25
hA2 = t2[t2.date <= SPLIT_L1]; hB2 = t2[t2.date > SPLIT_L1]
print(f"\nA3a tier 2 (IBS .10-.20, no tier-1 that day, VIX>=20): n={tt['n']} ({tt['n']/yrs:.1f}/yr) net {tt['mean']*1e4:+.2f} bp CI[{tt['lo']*1e4:+.1f},{tt['hi']*1e4:+.1f}] p1={tt['p1']:.4f} hit {(t2.val>0).mean():.3f}")
print(f"   halves: <=2012 n={len(hA2)} {hA2.val.mean()*1e4:+.1f} bp | >2012 n={len(hB2)} {hB2.val.mean()*1e4:+.1f} bp;  tier-1 n={len(t1)} {t1.val.mean()*1e4:+.2f} bp")
def port(df1, df2, w2):
    a = pd.concat([df1.assign(w=1.0), df2.assign(w=w2)]).sort_values("date")
    x = (a.val * a.w * 1e4).values; n = len(x); tpy = n / yrs
    ir = x.mean() / x.std() * np.sqrt(tpy); eq = np.cumsum(x); dd = (eq - np.maximum.accumulate(eq)).min()
    return dict(n=n, per_year=tpy, mean_bp_per_trade=float(x.mean()), total_bp=float(x.sum()), ir=float(ir), maxdd=float(dd))
p1_ = port(t1, t2.iloc[0:0], 0.5); pc = port(t1, t2, 0.5)
print(f"   tier 1 alone: n={p1_['n']} {p1_['per_year']:.1f}/yr, sum {p1_['total_bp']:.0f} bp, IR {p1_['ir']:.2f}, maxDD {p1_['maxdd']:.0f} bp")
print(f"   tier 1 + 0.5 x tier 2: n={pc['n']} {pc['per_year']:.1f}/yr, sum {pc['total_bp']:.0f} bp, IR {pc['ir']:.2f}, maxDD {pc['maxdd']:.0f} bp")
res["A3"] = dict(n=tt["n"], per_year=tt["n"]/yrs, mean_bp=tt["mean"]*1e4, lo=tt["lo"]*1e4, hi=tt["hi"]*1e4, p1=tt["p1"], hit=float((t2.val > 0).mean()),
                 h1_bp=float(hA2.val.mean()*1e4), h1_n=len(hA2), h2_bp=float(hB2.val.mean()*1e4), h2_n=len(hB2), tier1=p1_, combined=pc)

# ================= Holm over A1a, A2a, A3a =================
ps = [t_a1a["p1"], t_a2a["p1"], tt["p1"]]; hh = holm(ps)
print(f"\nHolm-adjusted p (A1a, A2a, A3a): {hh[0]:.4f}, {hh[1]:.4f}, {hh[2]:.4f}   (raw {ps[0]:.4f}, {ps[1]:.4f}, {ps[2]:.4f})")
res["holm"] = dict(A1a=float(hh[0]), A2a=float(hh[1]), A3a=float(hh[2]))
adm3 = (hh[2] < 0.10) and (tt["mean"] * 1e4 >= 8) and (hA2.val.mean() > 0 and hB2.val.mean() > 0) and (pc["ir"] >= p1_["ir"])
sup = ((hh[0] < 0.10 and t_a1a["mean"] > 0) or (hh[1] < 0.10 and t_a2a["mean"] > 0))
weak = (t_a1a["mean"] <= 0 and t_a2a["mean"] <= 0)
print("A3 admission (add tier 2 to the bot):", "YES" if adm3 else "NO")
print("A1/A2 out-of-sample label:", "SUPPORTED" if sup else ("WEAKENED" if weak else "INCONCLUSIVE"))
res["decisions"] = dict(add_tier2=bool(adm3), oos_label="SUPPORTED" if sup else ("WEAKENED" if weak else "INCONCLUSIVE"))

# ================= A4: sizing on the tier-1 trades =================
x = t1.copy().sort_values("date").reset_index(drop=True); x["r"] = x.val * 1e4
wts = {"constant": np.ones(len(x)), "w_up (prop. to VIX)": x.vix.values, "w_dn (prop. to 1/VIX)": 1 / x.vix.values}
tpy1 = len(x) / yrs; out4 = {}
yrsv = x.date.dt.year.values; uy = np.unique(yrsv); rng = np.random.default_rng(84)
def ir_of(r, w):
    w = w / w.mean(); y = r * w; return y.mean() / y.std()
boot = {k: [] for k in wts}; boot_d = {k: [] for k in wts if k != "constant"}
byy = {y: np.where(yrsv == y)[0] for y in uy}
for _ in range(YEAR_B):
    pick = rng.choice(uy, len(uy)); ii = np.concatenate([byy[y] for y in pick]); r = x.r.values[ii]
    base = ir_of(r, np.ones(len(r)))
    for k in boot_d: boot_d[k].append(ir_of(r, wts[k][ii]) - base)
print("\nA4 sizing on the tier-1 trades (weights normalised to mean 1):")
for k, w in wts.items():
    wn = w / w.mean(); y = x.r.values * wn; eq = np.cumsum(y); dd = (eq - np.maximum.accumulate(eq)).min()
    s = dict(mean_bp=float(y.mean()), sd=float(y.std()), ir_trade=float(y.mean() / y.std()), ir_ann=float(y.mean() / y.std() * np.sqrt(tpy1)), maxdd=float(dd), total=float(y.sum()))
    if k != "constant":
        d = np.array(boot_d[k]); a = x.date <= SPLIT_L1
        h1 = ir_of(x.r.values[a.values], w[a.values]) - ir_of(x.r.values[a.values], np.ones(a.sum()))
        h2 = ir_of(x.r.values[~a.values], w[~a.values]) - ir_of(x.r.values[~a.values], np.ones((~a).sum()))
        s.update(d_ir_lo=float(np.percentile(d, 2.5)), d_ir_hi=float(np.percentile(d, 97.5)), d_ir=float(ir_of(x.r.values, w) - ir_of(x.r.values, np.ones(len(x)))), half1=float(h1), half2=float(h2))
        s["adopt"] = bool(s["d_ir_lo"] > 0 and h1 > 0 and h2 > 0)
        print(f"  {k:24s}: mean {s['mean_bp']:+.1f} bp, IR/trade {s['ir_trade']:.3f} (diff {s['d_ir']:+.3f}, CI[{s['d_ir_lo']:+.3f},{s['d_ir_hi']:+.3f}]), maxDD {s['maxdd']:.0f} bp, halves {h1:+.3f}/{h2:+.3f}, ADOPT={s['adopt']}")
    else:
        print(f"  {k:24s}: mean {s['mean_bp']:+.1f} bp, IR/trade {s['ir_trade']:.3f}, maxDD {s['maxdd']:.0f} bp")
    out4[k] = s
res["A4"] = out4
json.dump(res, open(f"{OUT}/addendum3_results.json", "w"), indent=1, default=float)
