"""Final Master v2 backtest, options break-even mapping, v1 unit-matched comparison, integrity checks.
Usage: python -I s06_final.py DATA_DIR REPO_DIR OUT_DIR"""
import sys, json, os, csv, datetime as dt
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from common import *

DATA, REPO, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
D = Data(DATA)
BL1 = Boot(len(D.dates_l1), B=5000, seed=41)
ORDER = ["SPY", "QQQ", "IWM"]; res = {}

def pick_frame(dates, thr=0.10):
    rows = []
    for d0 in dates:
        for t in ORDER:
            d = D.daily[t]
            if d0 in d.index and not np.isnan(d.at[d0, "ibs_prior"]) and d.at[d0, "ibs_prior"] < thr:
                r = d.loc[d0]; v = D.vix_prior.reindex([d0], method="ffill").iloc[0]
                rows.append(dict(date=d0, ticker=t, ibs_prior=d.at[d0, "ibs_prior"], vix_prior=v, open=r.Open, high=r.High, low=r.Low, close=r.Close,
                                 oc=r.oc, gap=r.gap)); break
    return pd.DataFrame(rows)

pf = pick_frame(D.dates_l1)
pf["sigma"] = pf.vix_prior / 100 / np.sqrt(252)
pf["z"] = pf.oc / pf.sigma
v2 = pf[pf.vix_prior >= 20].copy().reset_index(drop=True)
v2["net_bp"] = (v2.oc - COST) * 1e4
v2["net_z"] = v2.net_bp / 1e4 / v2.sigma
v2["year"] = v2.date.dt.year
v2.to_csv(f"{OUT}/master_v2_trades.csv", index=False)

def stats(x, col="net_bp"):
    a = x[col].values
    pf_ = a[a > 0].sum() / max(1e-9, -a[a < 0].sum())
    eq = np.cumsum(a); dd = (eq - np.maximum.accumulate(eq)).min()
    return dict(n=len(a), mean=float(a.mean()), sd=float(a.std(ddof=1)), hit=float((a > 0).mean()), pf=float(pf_), dd=float(dd), median=float(np.median(a)))

# ---------- 1. headline ----------
t = BL1.test(v2.assign(val=v2.net_bp / 1e4), D.dates_l1, "val")
S = stats(v2); Sz = stats(v2, "net_z")
yrs = (v2.date.max() - v2.date.min()).days / 365.25
print(f"MASTER v2 (VIX_prior>=20, prior IBS<0.10 first of SPY/QQQ/IWM, long open->close, 2bp RT): n={S['n']} over {yrs:.1f} yrs ({S['n']/yrs:.1f}/yr)")
print(f"  net {S['mean']:+.2f} bp/trade CI[{t['lo']*1e4:+.2f},{t['hi']*1e4:+.2f}]  median {S['median']:+.1f}  hit {S['hit']:.3f}  PF {S['pf']:.2f}  sd {S['sd']:.0f} bp  maxDD {S['dd']:.0f} bp")
print(f"  z-units (VIX-implied daily sd): mean {Sz['mean']:+.3f}  sd {Sz['sd']:.2f}  maxDD {Sz['dd']:.1f}")
res["v2"] = dict(S=S, Sz=Sz, ci=[t["lo"]*1e4, t["hi"]*1e4], per_year=S["n"]/yrs)
print("  sub-periods (n, mean bp, hit):")
for lab, a, b in [("1996-2007", 1996, 2007), ("2008-2014", 2008, 2014), ("2015-2026", 2015, 2026), ("2022-2026", 2022, 2026)]:
    x = v2[(v2.year >= a) & (v2.year <= b)]
    print(f"    {lab}: n={len(x):4d} mean {x.net_bp.mean():+6.1f} bp hit {(x.net_bp>0).mean():.3f}")
print("  by VIX band (share of total bp):")
tot = v2.net_bp.sum()
for lab, lo_, hi_ in [("20-25", 20, 25), (">=25", 25, 999)]:
    x = v2[(v2.vix_prior >= lo_) & (v2.vix_prior < hi_)]
    print(f"    VIX {lab}: n={len(x)} mean {x.net_bp.mean():+.1f} bp, share of total net bp {x.net_bp.sum()/tot:.1%}")
res["share_vix25"] = float(v2[v2.vix_prior >= 25].net_bp.sum() / tot)

# ---------- 2. placebo: random same-size draws of VIX>=20 sessions (SPY, open->close) ----------
spy = D.daily["SPY"]; spy = spy[(spy.index >= "1993-02-01")]
vp = D.vix_prior.reindex(spy.index, method="ffill")
pool = spy[vp >= 20].oc.values - COST
rng = np.random.default_rng(3); sims = np.array([rng.choice(pool, S["n"]).mean() for _ in range(10000)]) * 1e4
print(f"\nPlacebo: mean of {S['n']} random SPY VIX>=20 sessions: {sims.mean():+.2f} bp (p95 {np.percentile(sims,95):+.2f}); v2 pick mean {S['mean']:+.2f} beats {(sims < S['mean']).mean():.4f} of draws")
res["placebo_beat"] = float((sims < S["mean"]).mean())

# ---------- 3. model-free options mapping (empirical break-even) ----------
allhi = []
for tkr in ORDER:
    d = D.daily[tkr]; d = d[d.index >= "1993-02-01"].copy()
    d["vix"] = D.vix_prior.reindex(d.index, method="ffill"); d = d[d.vix >= 20].dropna(subset=["ibs_prior"])
    d["sigma"] = d.vix / 100 / np.sqrt(252); allhi.append(d)
allhi = pd.concat(allhi)
def put_spread(x, dd, w):
    """short put at open*(1-dd*sigma), long at width w*sigma lower. returns win prob, fair credit as fraction of width"""
    ks = x.Open * (1 - dd * x.sigma); kl = x.Open * (1 - (dd + w) * x.sigma)
    loss = ((ks - x.Close) / (ks - kl)).clip(0, 1)
    return float((x.Close >= ks).mean()), float(loss.mean())
def call_spread(x, a, w):
    kl = x.Open * (1 + a * x.sigma); ku = x.Open * (1 + (a + w) * x.sigma)
    pay = ((x.Close - kl) / (ku - kl)).clip(0, 1)
    return float((x.Close > kl).mean()), float(pay.mean())
pick_x = v2.rename(columns={"open": "Open", "close": "Close"})
print("\nOptions mapping, model-free (same-day expiry, strikes in units of VIX-implied daily sd from the OPEN).")
print("Bull put credit spread: P(win), fair credit as % of width [picks | all VIX>=20 ticker-days]")
tab = {}
for dd_ in [0.5, 0.75, 1.0]:
    for w in [0.25, 0.5]:
        a = put_spread(pick_x, dd_, w); b = put_spread(allhi, dd_, w)
        tab[f"put d={dd_} w={w}"] = dict(win_pick=a[0], fair_pick=a[1], win_all=b[0], fair_all=b[1])
        print(f"  short -{dd_:.2f}sd, width {w:.2f}sd : win {a[0]:.3f} fair credit {a[1]*100:5.1f}% of width | all: win {b[0]:.3f} fair {b[1]*100:5.1f}%")
print("Bull call debit spread: P(finish above long strike), fair debit as % of width [picks | all]")
for a_ in [0.0, 0.25]:
    for w in [0.5, 1.0]:
        a = call_spread(pick_x, a_, w); b = call_spread(allhi, a_, w)
        tab[f"call a={a_} w={w}"] = dict(p_pick=a[0], fair_pick=a[1], p_all=b[0], fair_all=b[1])
        print(f"  long +{a_:.2f}sd, width {w:.2f}sd : P(above) {a[0]:.3f} fair debit {a[1]*100:5.1f}% of width | all: {b[0]:.3f} fair {b[1]*100:5.1f}%")
res["options_tab"] = tab

# ---------- 4. v1 unit-matched comparison ----------
ev = pd.read_csv(f"{REPO}/results/exit_variants.csv")
ev["tsu"] = pd.to_datetime(ev["ts"], utc=True)
def stop_dist_for(row, cache={}):
    key = row.ticker
    if key not in cache:
        d = pd.read_csv(f"{REPO}/data/{key}_5m.csv", index_col=0)
        d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York"); d = d.between_time("09:30", "15:55")
        d["date"] = d.index.date; cache[key] = d
    d = cache[key]; ts = row.tsu.tz_convert("America/New_York")
    g = d[d["date"] == ts.date()]
    tr = pd.concat([g.High - g.Low, (g.High - g.Close.shift()).abs(), (g.Low - g.Close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=5).mean()
    i = g.index.get_loc(ts)
    return max(atr.iloc[i] * 0.9, g.Close.iloc[i] * 0.0008), g.Close.iloc[i]
def v1_units(variant, rule):
    d = ev[(ev.exit_variant == variant) & ev.module.isin(["P1C", "P2"]) & ev.ticker.isin(ORDER)].copy()
    d["rvol_dist"] = (d.rvol - 1).abs(); d["prio"] = d.module.map({"P1C": 0, "P2": 1})
    pick = d.sort_values(["date", "prio", "rvol_dist"] if rule == "hindsight" else ["date", "tsu", "rvol_dist"]).groupby("date").head(1)
    sd = pick.apply(lambda r: stop_dist_for(r), axis=1)
    pick["stop_bp"] = [x[0] / x[1] * 1e4 for x in sd]
    pick["net_bp"] = pick.R2 * pick.stop_bp
    pick["sigma"] = pick.vix_prior / 100 / np.sqrt(252)
    pick["net_z"] = pick.net_bp / 1e4 / pick.sigma
    return pick
print("\nUNIT-MATCHED COMPARISON (net of each strategy's own cost model; bp of underlying and VIX-implied-sd units)")
rows = []
per_year_v1 = 252 * 57 / 57  # one trade per session
for variant, vl in [("simple_tp1.2_mb20", "reliability"), ("simple_tp2.5_mb20", "runner")]:
    for rule in ["hindsight", "first_fire"]:
        p = v1_units(variant, rule)
        m, s_ = p.net_bp.mean(), p.net_bp.std(ddof=1)
        rows.append(dict(name=f"v1 {vl} {rule}", n=len(p), R_mean=p.R2.mean(), bp_mean=m, bp_sd=s_, z_mean=p.net_z.mean(), hit=(p.R2 > 0).mean(), stop_bp=p.stop_bp.mean(),
                         ir_ann=(m / s_) * np.sqrt(252)))
for r in rows:
    print(f"  {r['name']:30s} n={r['n']} meanR {r['R_mean']:+.3f} | {r['bp_mean']:+.2f} bp/trade (sd {r['bp_sd']:.1f}) z {r['z_mean']:+.3f} hit {r['hit']:.3f} avg 1R={r['stop_bp']:.1f}bp | annualised IR if 1 trade/session {r['ir_ann']:+.2f}")
a = v2.net_bp.values
v2_ir = (a.mean() / a.std(ddof=1)) * np.sqrt(S["n"] / yrs)
print(f"  {'v2 VIX>=20 IBS dip':30s} n={S['n']} | {S['mean']:+.2f} bp/trade (sd {S['sd']:.1f}) z {Sz['mean']:+.3f} hit {S['hit']:.3f} | annualised IR at {S['n']/yrs:.1f} trades/yr {v2_ir:+.2f}")
res["v1_rows"] = rows; res["v2_ir"] = float(v2_ir)
print(f"  expected underlying bp per year: v1 hindsight (reliability) {rows[0]['bp_mean']*252:+.0f}; v1 live rule {rows[1]['bp_mean']*252:+.0f}; v2 {S['mean']*S['n']/yrs:+.0f} (avg), last-5y avg {v2[v2.year>=2022].net_bp.sum()/5:+.0f}")

# ---------- 5. integrity: lookahead truncation test + independent csv recomputation ----------
print("\nINTEGRITY")
# (a) truncation: rebuild signal for a date with data truncated to the prior session; compare IBS and VIX used
rng = np.random.default_rng(1); bad = 0; chk = 0
for d0 in rng.choice(v2.date.values, 25, replace=False):
    d0 = pd.Timestamp(d0); r = v2[v2.date == d0].iloc[0]; t = r.ticker
    raw = pd.read_csv(f"{DATA}/{t}_1d.csv", index_col=0); raw.index = pd.to_datetime(raw.index, utc=True).tz_localize(None).normalize()
    raw = raw[raw.index < d0]                       # only data strictly before the trade date
    last = raw.iloc[-1]; ibs = (last.Close - last.Low) / (last.High - last.Low)
    vr = pd.read_csv(f"{DATA}/VIX_1d.csv", index_col=0); vr.index = pd.to_datetime(vr.index, utc=True).tz_localize(None).normalize()
    vlast = vr[vr.index < d0].Close.iloc[-1]
    chk += 1
    if abs(ibs - r.ibs_prior) > 1e-9 or abs(vlast - r.vix_prior) > 1e-9 or not (ibs < 0.10 and vlast >= 20): bad += 1
print(f"  truncation test (signal rebuilt from data strictly before the trade date): {chk-bad}/{chk} identical")
# (b) independent plain-python recomputation of headline stats
def readcsv(path):
    with open(path) as f:
        rd = csv.reader(f); hdr = next(rd); out = []
        for r in rd:
            if len(r) < 6: continue
            out.append(r)
    return hdr, out
def col(hdr, name): return hdr.index(name)
data = {}
for tkr in ORDER:
    hdr, rows_ = readcsv(f"{DATA}/{tkr}_1d.csv"); io = col(hdr, "Open"); ih = col(hdr, "High"); il = col(hdr, "Low"); ic = col(hdr, "Close")
    seq = []
    for r in rows_:
        try: seq.append((r[0][:10], float(r[io]), float(r[ih]), float(r[il]), float(r[ic])))
        except: pass
    data[tkr] = {x[0]: (i, x) for i, x in enumerate(seq)}; data[tkr]["_seq"] = seq
hdr, vrows = readcsv(f"{DATA}/VIX_1d.csv"); iv = col(hdr, "Close"); vseq = [(r[0][:10], float(r[iv])) for r in vrows if r[iv] not in ("", "nan")]
vdate = [x[0] for x in vseq]; vclose = [x[1] for x in vseq]
import bisect
trades = []
all_dates = sorted(set(d for t in ORDER for d in data[t] if d != "_seq" and d >= "1993-02-01"))
for d0 in all_dates:
    k = bisect.bisect_left(vdate, d0) - 1
    if k < 0 or vclose[k] < 20: continue
    for tkr in ORDER:
        if d0 not in data[tkr]: continue
        i, x = data[tkr][d0]
        if i == 0: continue
        p = data[tkr]["_seq"][i - 1]
        rngp = p[2] - p[3]
        if rngp <= 0: continue
        if (p[4] - p[3]) / rngp < 0.10:
            trades.append(x[4] / x[1] - 1 - 0.0002); break
tr = np.array(trades)
print(f"  independent csv-module recomputation: n={len(tr)} mean {tr.mean()*1e4:+.2f} bp hit {(tr>0).mean():.3f}  | pandas pipeline: n={S['n']} mean {S['mean']:+.2f} bp hit {S['hit']:.3f}")
res["independent"] = dict(n=len(tr), mean_bp=float(tr.mean()*1e4))
# (c) sign-flip placebo: same trade dates, random sign
rs = np.random.default_rng(8); flip = np.array([(v2.oc.values * rs.choice([-1, 1], len(v2))).mean() for _ in range(5000)]) * 1e4
print(f"  random-sign placebo on the same dates: mean {flip.mean():+.2f} bp, p95 {np.percentile(flip,95):+.2f} bp (v2 gross {v2.oc.mean()*1e4:+.2f})")

# ---------- 6. post-hoc hypotheses for forward registration (descriptive only) ----------
print("\nFORWARD-HYPOTHESIS CANDIDATES (post-hoc, NOT admitted)")
sh = allhi[allhi.ibs_prior > 0.90].copy(); sh["oc"] = sh.Close / sh.Open - 1
print(f"  short IBS>0.90 within VIX>=20 (ticker-days): n={len(sh)} mean oc {sh.oc.mean()*1e4:+.1f} bp -> short net {(-sh.oc.mean()-COST)*1e4:+.1f} bp; halves <=2012 {(-sh[sh.index<='2012-12-31'].oc.mean()-COST)*1e4:+.1f} / >=2013 {(-sh[sh.index>'2012-12-31'].oc.mean()-COST)*1e4:+.1f}")
iw = v2[v2.ticker == "IWM"]; ot = v2[v2.ticker != "IWM"]
print(f"  IWM-triggered trades: n={len(iw)} {iw.net_bp.mean():+.1f} bp; SPY/QQQ-triggered: n={len(ot)} {ot.net_bp.mean():+.1f} bp")
json.dump(res, open(f"{OUT}/final_results.json", "w"), indent=1, default=float)
