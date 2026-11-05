"""Shared loaders and helpers (hourly sessions, daily context, bootstraps)."""
import numpy as np, pandas as pd
from math import erf, sqrt

TICK = ["SPY", "QQQ", "IWM"]
COST = 0.0002
SPLIT_L2 = pd.Timestamp("2025-06-30")
SPLIT_L1 = pd.Timestamp("2012-12-31")

def _rd(path):
    return pd.read_csv(path, index_col=0)

def norm_p2(z):
    return 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))

class Data:
    def __init__(self, data_dir):
        self.dir = data_dir
        v = _rd(f"{data_dir}/VIX_1d.csv"); v.index = pd.to_datetime(v.index, utc=True).tz_localize(None).normalize()
        v = v[~v.index.duplicated()].sort_index()["Close"].astype(float)
        self.vix = v; self.vix_prior = v.shift(1)
        self.daily = {t: self._daily(t) for t in TICK}
        spy = self.daily["SPY"]
        sma = spy.Close.rolling(200).mean()
        self.above200_prior = (spy.Close > sma).shift(1)
        self.sess = {t: self._sessions(t) for t in TICK}
        self.dates_l2 = self.sess["SPY"].index.union(self.sess["QQQ"].index).union(self.sess["IWM"].index)
        dl1 = self.daily["SPY"].index.union(self.daily["QQQ"].index).union(self.daily["IWM"].index)
        self.dates_l1 = dl1[dl1 >= pd.Timestamp("1993-02-01")]

    def _daily(self, t):
        d = _rd(f"{self.dir}/{t}_1d.csv")
        d.index = pd.to_datetime(d.index, utc=True).tz_localize(None).normalize()
        d = d[~d.index.duplicated()].sort_index()
        for c in ["Open", "High", "Low", "Close"]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["Open", "High", "Low", "Close"])
        rng = (d.High - d.Low).replace(0, np.nan)
        d["ibs"] = (d.Close - d.Low) / rng
        d["ibs_prior"] = d["ibs"].shift(1)
        d["oc"] = d.Close / d.Open - 1
        d["gap"] = d.Open / d.Close.shift(1) - 1
        d["mae"] = -(d.Low / d.Open - 1)     # adverse excursion for a long from the open
        d["mfe"] = d.High / d.Open - 1
        return d

    def _sessions(self, t):
        d = _rd(f"{self.dir}/{t}_1h.csv")
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
        for k in range(7):
            s[f"RV{k}"] = s[f"V{k}"] / s[f"V{k}"].shift(1).rolling(20).mean()
        s["vix_prior"] = self.vix_prior.reindex(s.index, method="ffill")
        s["ibs_prior"] = self.daily[t]["ibs_prior"].reindex(s.index)
        s["oc"] = s["C6"] / s["O0"] - 1
        return s

class Boot:
    def __init__(self, n_dates, B=4000, seed=7):
        self.rng = np.random.default_rng(seed)
        self.idx = self.rng.integers(0, n_dates, size=(B, n_dates))

    def agg(self, ev, all_dates, col="val"):
        g = ev.groupby("date")[col].agg(["sum", "count"]).reindex(all_dates).fillna(0.0)
        return g["sum"].values, g["count"].values

    def mean_dist(self, ev, all_dates, col="val"):
        S, N = self.agg(ev, all_dates, col)
        s = S[self.idx].sum(1); c = N[self.idx].sum(1)
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)

    def test(self, ev, all_dates, col="val"):
        """two-sided normal-approx p from bootstrap SE, plus percentile CI"""
        if len(ev) < 5: return dict(n=len(ev), mean=np.nan, se=np.nan, z=np.nan, p2=np.nan, lo=np.nan, hi=np.nan)
        m = self.mean_dist(ev, all_dates, col)
        mean = ev[col].mean(); se = np.nanstd(m)
        z = mean / se if se > 0 else np.nan
        return dict(n=len(ev), mean=mean, se=se, z=z, p2=norm_p2(z) if se > 0 else np.nan,
                    p1=float(np.nanmean(m <= 0)), lo=np.nanpercentile(m, 2.5), hi=np.nanpercentile(m, 97.5))

    def diff(self, evA, evB, all_dates, col="val"):
        SA, NA = self.agg(evA, all_dates, col); SB, NB = self.agg(evB, all_dates, col)
        mA = SA[self.idx].sum(1) / np.maximum(NA[self.idx].sum(1), 1)
        mB = SB[self.idx].sum(1) / np.maximum(NB[self.idx].sum(1), 1)
        d = mA - mB
        return dict(nA=len(evA), nB=len(evB), mA=evA[col].mean(), mB=evB[col].mean(), diff=evA[col].mean() - evB[col].mean(),
                    lo=np.percentile(d, 2.5), hi=np.percentile(d, 97.5), p1=float((d <= 0).mean()))

def holm(ps):
    ps = np.asarray(ps, float); m = len(ps); order = np.argsort(ps); adj = np.zeros(m); run = 0
    for rank, idx in enumerate(order):
        run = max(run, (m - rank) * ps[idx]); adj[idx] = min(1.0, run)
    return adj

def trap_events(sess, t, follow=False, vix_min=None):
    s = sess[t]; rows = []
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
