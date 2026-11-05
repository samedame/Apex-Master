"""L1/L2 tests exactly as pre-registered in PREREG.md (sha256 d06dd8b4...). Usage: python -I s02_longhist.py DATA_DIR OUT_DIR"""
import sys, json, os
import numpy as np, pandas as pd

DATA, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
TICK = ["SPY", "QQQ", "IWM"]
COST = 0.0002          # 2 bp round trip, as registered
SPLIT_L2 = pd.Timestamp("2025-06-30")
SPLIT_L1 = pd.Timestamp("2012-12-31")   # gap-fill clarification for L1 halves (set before results were seen)
rng = np.random.default_rng(20261104)

def rd(path):
    d = pd.read_csv(path, index_col=0)
    return d

# ---------- daily + VIX ----------
def load_daily(t):
    d = rd(f"{DATA}/{t}_1d.csv")
    d.index = pd.to_datetime(d.index, utc=True).tz_localize(None).normalize()
    d = d[~d.index.duplicated()].sort_index()
    for c in ["Open", "High", "Low", "Close"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["Open", "High", "Low", "Close"])
    d["ibs_prior"] = ((d.Close - d.Low) / (d.High - d.Low).replace(0, np.nan)).shift(1)
    return d

vix = rd(f"{DATA}/VIX_1d.csv"); vix.index = pd.to_datetime(vix.index, utc=True).tz_localize(None).normalize()
vix = vix[~vix.index.duplicated()].sort_index()["Close"].astype(float)
vix_prior = vix.shift(1)

DAILY = {t: load_daily(t) for t in TICK}

# ---------- hourly sessions ----------
def load_sessions(t):
    d = rd(f"{DATA}/{t}_1h.csv")
    d.index = pd.to_datetime(d.index, utc=True).tz_convert("America/New_York")
    d = d.sort_index()
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["date"] = d.index.normalize().tz_localize(None)
    rows = []
    for dt, g in d.groupby("date"):
        if len(g) != 7: continue
        if g.index[0].strftime("%H:%M") != "09:30" or g.index[-1].strftime("%H:%M") != "15:30": continue
        if g[["Open", "High", "Low", "Close"]].isna().any().any(): continue
        r = {"date": dt}
        for k in range(7):
            for c, nm in zip(["Open", "High", "Low", "Close", "Volume"], "OHLCV"):
                r[f"{nm}{k}"] = g[c].iloc[k]
        rows.append(r)
    s = pd.DataFrame(rows).set_index("date").sort_index()
    s["prevC"] = s["C6"].shift(1)
    # RVOL per slot: volume / mean of same slot over prior 20 sessions
    for k in range(7):
        s[f"RV{k}"] = s[f"V{k}"] / s[f"V{k}"].shift(1).rolling(20).mean()
    s["vix_prior"] = vix_prior.reindex(s.index, method="ffill")
    s["ibs_prior"] = DAILY[t]["ibs_prior"].reindex(s.index)
    s["oc"] = s["C6"] / s["O0"] - 1
    return s

SESS = {t: load_sessions(t) for t in TICK}
for t in TICK:
    print(t, "sessions", len(SESS[t]), SESS[t].index[0].date(), SESS[t].index[-1].date())

# ---------- bootstrap ----------
def date_agg(ev, all_dates):
    g = ev.groupby("date")["val"].agg(["sum", "count"]).reindex(all_dates).fillna(0.0)
    return g["sum"].values, g["count"].values

def boot_mean(S, N, B=10000):
    n = len(S); idx = rng.integers(0, n, size=(B, n))
    s = S[idx].sum(1); c = N[idx].sum(1)
    m = np.where(c > 0, s / np.maximum(c, 1), np.nan)
    return m

def summarize(ev, all_dates, claim=">0"):
    if len(ev) == 0: return dict(n=0)
    S, N = date_agg(ev, all_dates)
    m = boot_mean(S, N)
    mean = ev["val"].mean()
    lo, hi = np.nanpercentile(m, [2.5, 97.5])
    p = float(np.nanmean(m <= 0))
    return dict(n=int(len(ev)), mean_bp=mean * 1e4, lo_bp=lo * 1e4, hi_bp=hi * 1e4, p=p, hit=float((ev["val"] > 0).mean()))

def boot_diff(evA, evB, all_dates, B=10000):
    SA, NA = date_agg(evA, all_dates); SB, NB = date_agg(evB, all_dates)
    n = len(SA); idx = rng.integers(0, n, size=(B, n))
    mA = SA[idx].sum(1) / np.maximum(NA[idx].sum(1), 1); mB = SB[idx].sum(1) / np.maximum(NB[idx].sum(1), 1)
    d = mA - mB
    return dict(nA=len(evA), nB=len(evB), meanA_bp=evA.val.mean() * 1e4, meanB_bp=evB.val.mean() * 1e4,
                diff_bp=(evA.val.mean() - evB.val.mean()) * 1e4, lo_bp=np.percentile(d, 2.5) * 1e4,
                hi_bp=np.percentile(d, 97.5) * 1e4, p=float((d <= 0).mean()))

def halves(ev, split):
    return ev[ev.date <= split], ev[ev.date > split]

# ---------- L2 event builders ----------
def events_trap(t, follow=False):
    s = SESS[t]; rows = []
    ORH, ORL = s.H0.values, s.L0.values
    mu = {k: (s[f"C{k}"] / s[f"O{k}"] - 1).mean() for k in range(7)}
    sig = np.zeros((len(s), 5), int)
    for k in range(1, 5):
        O, H, L, C = (s[f"{x}{k}"].values for x in "OHLC")
        if not follow:
            short = (H > ORH) & (C < ORH) & (C < O); long = (L < ORL) & (C > ORL) & (C > O)
        else:
            long = (C > ORH) & (C > O); short = (C < ORL) & (C < O)
        sig[:, k] = np.where(short & ~long, -1, np.where(long & ~short, 1, 0))
    for i, dt in enumerate(s.index):
        for k in range(1, 5):
            if sig[i, k] != 0:
                d = sig[i, k]; kk = k + 1
                r = s[f"C{kk}"].iloc[i] / s[f"O{kk}"].iloc[i] - 1
                rows.append(dict(date=dt, ticker=t, k=k, dir=d, rv=s[f"RV{k}"].iloc[i], vix=s.vix_prior.iloc[i],
                                 gross=d * r, excess=d * (r - mu[kk])))
                break
    return pd.DataFrame(rows)

def events_late(t, mode):
    s = SESS[t]
    r6 = s.C6 / s.O6 - 1; mu6 = r6.mean()
    sgn = np.sign(s.O6 / s.prevC - 1) if mode == "a" else np.sign(s.O6 / s.O0 - 1)
    ev = pd.DataFrame({"date": s.index, "ticker": t, "dir": sgn.values, "gross": (sgn * r6).values,
                       "excess": (sgn * (r6 - mu6)).values, "vix": s.vix_prior.values})
    return ev[(ev.dir != 0) & ev.gross.notna()]

def events_ibs_l2(t, side):
    s = SESS[t]; mu = s.oc.mean()
    if side == "long": m = s.ibs_prior < 0.10; d = 1
    else: m = s.ibs_prior > 0.90; d = -1
    x = s[m]
    return pd.DataFrame({"date": x.index, "ticker": t, "dir": d, "gross": d * x.oc.values, "excess": d * (x.oc.values - mu), "vix": x.vix_prior.values})

def events_ibs_l1(t, side):
    dly = DAILY[t].dropna(subset=["ibs_prior"]).copy()
    dly["oc"] = dly.Close / dly.Open - 1; mu = dly.oc.mean()
    if side == "long": m = dly.ibs_prior < 0.10; d = 1
    else: m = dly.ibs_prior > 0.90; d = -1
    x = dly[m]
    return pd.DataFrame({"date": x.index, "ticker": t, "dir": d, "gross": d * x.oc.values, "excess": d * (x.oc.values - mu)})

def concat(f, *a):
    return pd.concat([f(t, *a) for t in TICK], ignore_index=True)

dates_l2 = SESS["SPY"].index.union(SESS["QQQ"].index).union(SESS["IWM"].index)
dates_l1 = DAILY["SPY"].index.union(DAILY["QQQ"].index).union(DAILY["IWM"].index)
dates_l1 = dates_l1[dates_l1 >= pd.Timestamp("1993-02-01")]

results = {}
def run(name, ev, all_dates, split, use="excess", cost=True, extra=None):
    e = ev.copy(); e["val"] = e[use] - (COST if cost else 0)
    full = summarize(e, all_dates)
    A, B = halves(e, split)
    full["A_mean_bp"] = A.val.mean() * 1e4 if len(A) else np.nan; full["A_n"] = len(A)
    full["B_mean_bp"] = B.val.mean() * 1e4 if len(B) else np.nan; full["B_n"] = len(B)
    full["gross_bp"] = ev[use].mean() * 1e4 if len(ev) else np.nan
    if "raw" in (extra or {}): pass
    results[name] = full
    return full

# H1, H2
ev1 = concat(events_trap, False); ev2 = concat(events_trap, True)
run("H1 trap fade (L2)", ev1, dates_l2, SPLIT_L2)
run("H2 breakout follow (L2)", ev2, dates_l2, SPLIT_L2)

# H3 RVOL normalcy inside H1
e = ev1.dropna(subset=["rv"]).copy(); e["val"] = e["excess"]
normal = e[(e.rv >= 0.75) & (e.rv <= 1.33)]; outside = e[(e.rv < 0.75) | (e.rv > 1.33)]
h3 = boot_diff(normal, outside, dates_l2)
h3["p_h3"] = h3["p"]
results["H3 RVOL-normal minus outside (L2, inside H1)"] = h3

# H4 late-day momentum
ev4a = concat(events_late, "a"); ev4b = concat(events_late, "b")
run("H4a late-day momentum (prevclose->15:30)", ev4a, dates_l2, SPLIT_L2, use="gross")
run("H4b late-day momentum (open->15:30)", ev4b, dates_l2, SPLIT_L2, use="gross")
ev4c = ev4a[ev4a.vix >= 20]
run("H4c = H4a, VIX>=20", ev4c, dates_l2, SPLIT_L2, use="gross")

# H5
ev5a = concat(events_ibs_l2, "long"); ev5b = concat(events_ibs_l2, "short")
run("H5a IBS<0.10 long (L2 o->c)", ev5a, dates_l2, SPLIT_L2)
run("H5b IBS>0.90 short (L2 o->c)", ev5b, dates_l2, SPLIT_L2)
ev5c = concat(events_ibs_l1, "long"); ev5d = concat(events_ibs_l1, "short")
run("H5c IBS<0.10 long (L1 daily o->c)", ev5c, dates_l1, SPLIT_L1)
run("H5d IBS>0.90 short (L1 daily o->c)", ev5d, dates_l1, SPLIT_L1)

# ---------- Holm over the 10 registered tests ----------
names = list(results.keys())
ps = []
for n in names:
    r = results[n]
    ps.append(r["p_h3"] if "p_h3" in r else r.get("p", np.nan))
order = np.argsort(ps); m = len(ps); adj = np.zeros(m); run_max = 0
for rank, idx in enumerate(order):
    run_max = max(run_max, (m - rank) * ps[idx]); adj[idx] = min(1.0, run_max)
for n, a in zip(names, adj): results[n]["p_holm"] = float(a)

print("\n=== REGISTERED TESTS (net of 2bp RT where applicable; one-sided p for claim > 0; Holm over 10) ===")
for n in names:
    r = results[n]
    if "diff_bp" in r:
        print(f"{n}\n   nNormal={r['nA']} nOutside={r['nB']}  mean normal {r['meanA_bp']:+.2f} bp vs outside {r['meanB_bp']:+.2f} bp ; diff {r['diff_bp']:+.2f} bp CI[{r['lo_bp']:+.2f},{r['hi_bp']:+.2f}] p={r['p']:.3f} holm={r['p_holm']:.3f}")
    else:
        print(f"{n}\n   n={r['n']} gross {r['gross_bp']:+.2f} bp  net {r['mean_bp']:+.2f} bp CI[{r['lo_bp']:+.2f},{r['hi_bp']:+.2f}] hit={r['hit']:.3f} p={r['p']:.3f} holm={r['p_holm']:.3f} | halfA n={r['A_n']} {r['A_mean_bp']:+.2f} halfB n={r['B_n']} {r['B_mean_bp']:+.2f}")

# ---------- descriptive extras (NOT part of the registered family) ----------
print("\n=== DESCRIPTIVE (unregistered, no p-values used for admission) ===")
for nm, ev, use in [("H1", ev1, "excess"), ("H2", ev2, "excess"), ("H4a", ev4a, "gross")]:
    print(f"-- {nm} by ticker (gross bp / n):", {t: (round(ev[ev.ticker == t][use].mean() * 1e4, 2), int((ev.ticker == t).sum())) for t in TICK})
    v = ev.dropna(subset=["vix"]) if "vix" in ev else ev
    for lab, mask in [("VIX<15", v.vix < 15), ("15-20", (v.vix >= 15) & (v.vix < 20)), ("VIX>=20", v.vix >= 20)]:
        x = v[mask]
        print(f"   {lab}: n={len(x)} mean {x[use].mean()*1e4:+.2f} bp" if len(x) else f"   {lab}: n=0")
# drift-adjusted H4a
print("H4a drift-adjusted (excess) net bp:", round((ev4a.excess.mean() - COST) * 1e4, 2), " raw net bp:", round((ev4a.gross.mean() - COST) * 1e4, 2))
print("H4a share of sessions with positive s*r6:", round((ev4a.gross > 0).mean(), 3))
print("mean |last-bar return| bp (SPY/QQQ/IWM):", {t: round((SESS[t].C6 / SESS[t].O6 - 1).abs().mean() * 1e4, 1) for t in TICK})
print("H1 events by k:", ev1.groupby("k").size().to_dict(), " H1 long/short:", ev1.groupby("dir").size().to_dict())
ev1.to_csv(f"{OUT}/h1_events.csv", index=False); ev2.to_csv(f"{OUT}/h2_events.csv", index=False)
ev4a.to_csv(f"{OUT}/h4a_events.csv", index=False)
json.dump(results, open(f"{OUT}/longhist_results.json", "w"), indent=1, default=float)
