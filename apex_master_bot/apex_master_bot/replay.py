"""Replays the tested pipeline over saved 5-minute bars and (optionally) checks it against the published
trade log. This is the bot's proof that it behaves the way the backtest did."""
import numpy as np
import pandas as pd
from .config import Config
from .data import vix_prior_close
from .exits import evaluate
from .selector import select_tested, rank_key
from .signals import add_indicators, scan_bar, session_cumvols


def generate_candidates(provider, cfg: Config, tickers=None):
    rows = []
    for t in (tickers or cfg.universe):
        df = provider.bars(t)
        cum = session_cumvols(df)
        for k, (d, g) in enumerate(df.groupby(df.index.date)):
            if k == 0 and cfg.skip_first_dataset_session:
                continue
            if len(g) < cfg.min_bars_per_session:
                continue
            g = add_indicators(g, cfg)
            O, H, L, C = (g[c].values for c in ("Open", "High", "Low", "Close"))
            fired = set()
            for i in range(cfg.first_scan_bar, len(g) - 2):
                for c in scan_bar(g, i, t, cum, fired, cfg):
                    ex = evaluate(O, H, L, C, i, c["direction"], c["stop_dist"], cfg)
                    rows.append({**c, "R": ex["R"], "exit": ex["reason"], "bars_held": ex["bars"], "entry": ex["entry"]})
    return pd.DataFrame(rows)


def run(provider, cfg: Config, selection="tested"):
    cands = generate_candidates(provider, cfg)
    vix = provider.vix_daily() if cfg.vix_prior_cap is not None else None
    trades, skipped = [], []
    for date, day in cands.groupby("date"):
        if vix is not None:
            v = vix_prior_close(vix, date)
            if v >= cfg.vix_prior_cap:
                skipped.append((date, f"vix_prior {v:.2f}"))
                continue
        recs = day.to_dict("records")
        if selection == "tested":
            pick = select_tested(recs, cfg)
        elif selection == "first_fire":                    # causal rule used by the live bot
            first_bar_ts = min(r["ts"] for r in recs if r["ticker"] in cfg.universe and r["module"] in cfg.module_priority)
            pick = select_tested([r for r in recs if r["ts"] == first_bar_ts], cfg)
        else:
            raise ValueError(selection)
        if pick:
            trades.append(pick)
    return pd.DataFrame(trades).sort_values("date").reset_index(drop=True), cands, skipped


def stats(t: pd.DataFrame) -> dict:
    r = t["R"]
    pf = r[r > 0].sum() / max(0.01, -r[r < 0].sum())
    eq = r.cumsum()
    return dict(n=int(len(t)), win=float((r > 0).mean()), meanR=float(r.mean()), PF=float(pf),
                sumR=float(r.sum()), maxDD_R=float((eq - eq.cummax()).min()))


def compare(trades: pd.DataFrame, published: pd.DataFrame) -> dict:
    """Row-by-row parity with results/MASTER_trades_tp1.2.csv (or RUNNER_trades_tp2.5.csv)."""
    p = published.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.strftime("%Y-%m-%d")
    m = trades.merge(p[["date", "ticker", "module", "direction", "minute", "R2", "rvol"]],
                     on="date", how="outer", suffixes=("", "_pub"), indicator=True)
    both = m[m["_merge"] == "both"]
    same_pick = (both.ticker == both.ticker_pub) & (both.module == both.module_pub) & \
                (both.direction == both.direction_pub) & (both.minute == both.minute_pub)
    same_R = np.isclose(both.R, both.R2, atol=1e-9)
    return dict(bot_trades=int(len(trades)), published_trades=int(len(p)), matched_days=int(len(both)),
                same_trade=int(same_pick.sum()), same_R=int(same_R.sum()),
                max_abs_R_diff=float(np.abs(both.R - both.R2).max()) if len(both) else None,
                max_abs_rvol_diff=float(np.abs(both.rvol - both.rvol_pub).max()) if len(both) else None,
                only_bot=m[m["_merge"] == "left_only"].date.tolist(),
                only_published=m[m["_merge"] == "right_only"].date.tolist())
