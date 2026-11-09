"""Fixed ETF research comparisons on archived bars. Run with the bot on PYTHONPATH."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from apex_master_bot.market_regime import daily_features
from apex_master_bot.v2 import V2, load_daily_csv, replay

ROOT = Path(__file__).resolve().parents[2]
SPLITS = {"development": ("1996", "2015"), "validation": ("2016", "2020"),
          "historical_test": ("2021", "2026")}
COSTS = (2, 5, 10)


def panel(data):
    daily = {t: load_daily_csv(data / f"{t}_1d.csv") for t in V2.order}
    calendar = daily["SPY"].index
    baseline = replay(str(data)).set_index("date")
    baseline.index = pd.to_datetime(baseline.index)
    p = baseline.reindex(calendar)
    vix = load_daily_csv(data / "VIX_1d.csv").Close.reindex(calendar)
    p["vix"] = vix.shift()
    p["vix_change"] = vix.diff().shift()
    features = {t: daily_features(bars.reindex(calendar)) for t, bars in daily.items()}
    p["trend"] = features["SPY"].trend20.shift()
    p["rv20"] = features["SPY"].rv20.shift()
    prior_returns = pd.concat({t: x["return"].shift() for t, x in features.items()}, axis=1)
    p["participation"] = (prior_returns > 0).sum(axis=1).where(prior_returns.notna().all(axis=1))
    p["alt"] = p.oc
    for t in V2.order:
        ibs = features[t].ibs.shift()
        r = features[t].intraday
        p["alt"] = p.alt.mask((p.ticker.notna()) & (ibs < V2.ibs_max) & (ibs < p.ibs_prior), r)
        # Advance the minimum even if the eventual close is missing. No fallback based on outcomes.
        p["ibs_prior"] = p.ibs_prior.mask((p.ticker.notna()) & (ibs < p.ibs_prior), ibs)
    p["late"] = np.nan
    p["gap"] = np.nan
    for ticker in V2.order:
        hourly = pd.read_csv(data / f"{ticker}_1h.csv", index_col=0)
        hourly.index = pd.to_datetime(hourly.index, utc=True).tz_convert("America/New_York")
        if hourly.index.has_duplicates:
            raise ValueError(f"duplicate hourly bars for {ticker}")
        opening = hourly.at_time("09:30").Open
        later = hourly.at_time("10:30").Open
        opening.index = opening.index.tz_localize(None).normalize()
        later.index = later.index.tz_localize(None).normalize()
        selected = p.ticker == ticker
        prior = daily[ticker].Close.reindex(calendar).shift()
        p.loc[selected, "gap"] = (opening.reindex(calendar) / prior - 1)[selected]
        p.loc[selected, "late"] = (daily[ticker].Close.reindex(calendar) / later.reindex(calendar) - 1)[selected]
    return p


def variants(p):
    base = p.oc
    return {
        "baseline": base,
        "vix_up_1": base.where(p.vix_change >= 1),
        "spy_above_sma20": base.where(p.trend > 0),
        "etf_participation_2": base.where(p.participation >= 2),
        "prior_rv20_at_least_20pct": base.where(p.rv20 >= .20),
        "lowest_ibs": p.alt,
        "bearish_on_same_signal": -base,
    }


def drawdown(returns):
    curve = np.cumprod(np.concatenate((np.ones(returns.shape[:-1] + (1,)), 1 + returns), axis=-1), axis=-1)
    return (curve / np.maximum.accumulate(curve, axis=-1) - 1).min(axis=-1)


def stats(series, cost, *, bootstrap=True):
    traded = series.dropna()
    if traded.empty:
        return {"n": 0, "status": "INCONCLUSIVE"}
    x = traded.to_numpy() - cost / 10000
    daily = (series - cost / 10000).fillna(0).to_numpy()
    neg = x[x < 0]
    streak = longest = 0
    for r in x:
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
    vol = daily.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(daily, 0) ** 2))
    out = {"n": len(x), "annual_frequency": len(x) * 252 / len(daily),
           "net_bp": x.mean() * 1e4, "median_bp": np.median(x) * 1e4,
           "win_rate": (x > 0).mean(), "profit_factor": x[x > 0].sum() / -neg.sum() if len(neg) else None,
           "drawdown": float(drawdown(daily)), "p05_bp": np.quantile(x, .05) * 1e4,
           "daily_sharpe": daily.mean() / vol * np.sqrt(252) if len(x) >= 30 and vol > 0 else None,
           "daily_sortino": daily.mean() / downside * np.sqrt(252) if len(x) >= 30 and downside > 0 else None,
           "cost_bp_sum": len(x) * cost, "round_trips": len(x), "exposure": len(x) / len(daily),
           "compounded": np.prod(1 + daily) - 1, "longest_losing_streak": longest}
    if bootstrap and len(x) >= 30 and len(daily) >= 100:
        matrix = blocks(len(daily))
        net = daily[matrix]
        hits = (daily > 0)[matrix].sum(axis=1)
        trades = series.notna().to_numpy()[matrix].sum(axis=1)
        valid = trades > 0
        out.update(mean_ci_bp=np.quantile(net[valid].sum(axis=1) / trades[valid] * 1e4, [.025, .975]).tolist(),
                   win_ci=np.quantile(hits[valid] / trades[valid], [.025, .975]).tolist(),
                   drawdown_p05=float(np.quantile(drawdown(net), .05)))
    return out


def blocks(n, length=20):
    rng = np.random.default_rng(4715)
    start = rng.integers(0, n, size=(1500, (n + length - 1) // length, 1))
    return ((start + np.arange(length)) % n).reshape(1500, -1)[:, :n]


def compare(series, base, cost, matrix):
    if series.notna().sum() < 30 or base.notna().sum() < 30:
        return {"status": "INCONCLUSIVE"}
    delta = (series - cost / 10000).fillna(0) - (base - cost / 10000).fillna(0)
    observed = delta.mean()
    sampled = delta.to_numpy()[matrix].mean(axis=1)
    p = (1 + (abs(sampled - observed) >= abs(observed)).sum()) / (len(sampled) + 1)
    return {"delta_bp_per_session": observed * 1e4, "ci_bp": np.quantile(sampled * 1e4, [.025, .975]).tolist(),
            "p_block": p}


def holm(results, family_size):
    valid = sorted((r for r in results.values() if "p_block" in r), key=lambda r: r["p_block"])
    prior = 0.
    for i, row in enumerate(valid):
        prior = max(prior, min(1., row["p_block"] * (family_size - i)))
        row["p_holm"] = prior


def evaluate(p):
    report = {}
    for name, (start, end) in SPLITS.items():
        sub = p.loc[start:end]
        rules = variants(sub)
        matrix = blocks(len(sub))
        comparisons = {key: compare(series, rules["baseline"], 2, matrix)
                       for key, series in rules.items() if key != "baseline"}
        holm(comparisons, len(comparisons))
        report[name] = {"etf": {key: {cost: stats(series, cost, bootstrap=cost == 2) for cost in COSTS}
                                for key, series in rules.items()},
                        "paired_daily_comparisons": comparisons,
                        "baseline_by_vix": {name: stats(sub.oc.where(mask), 2, bootstrap=False)
                                            for name, mask in {"20_to_25": sub.vix.between(20, 25, inclusive="left"),
                                                               "25_plus": sub.vix >= 25}.items()}}
    late = p.loc["2023-12-07":].copy()
    late.loc[late.gap.isna(), "late"] = np.nan
    late_rules = {"delay_unfiltered": late.late, "negative_gap_long": late.late.where(late.gap < 0),
                  "negative_gap_at_least_50bp_long": late.late.where(late.gap <= -.005),
                  "negative_gap_short": -late.late.where(late.gap < 0)}
    report["hourly_exploratory"] = {"label": "10:30 ET hourly open to daily close, descriptive",
                                     "etf": {k: stats(v, 5) for k, v in late_rules.items()}}
    report["inconclusive"] = ["event exclusion: timestamped calendar archive missing",
                              "intraday exits: stop/target sequencing and executable marks missing",
                              "options: historical bid/ask archive missing",
                              "calibrated probabilities: prospective validation missing"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "research/master_v2/data")
    args = parser.parse_args()
    print(json.dumps(evaluate(panel(args.data)), indent=2, allow_nan=False))
