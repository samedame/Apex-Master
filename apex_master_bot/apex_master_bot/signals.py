"""Candidate detection for the two modules the Master trades (P1C primary, P2 fallback).

This is a line-for-line port of backtest/engine.py `candidates_for`, restricted to P1C and P2. Every
indicator is causal (uses bars up to and including bar i), so the same function serves replay (whole
day available) and live (day growing bar by bar) and returns identical signals.
"""
import numpy as np
import pandas as pd
from .config import Config


def session_cumvols(df: pd.DataFrame) -> dict:
    """date-string -> cumulative volume array of that session (engine: _volmat)."""
    return {str(d): np.cumsum(g["Volume"].values) for d, g in df.groupby(df.index.date)}


def rvol_at(cumvols: dict, date: str, i: int, today_cum_i: float, lookback: int = 20) -> float:
    """engine RVOL_MAP: cum volume at slot i / mean of the same slot over the prior `lookback` sessions
    available in the dataset (sessions shorter than i+1 bars are skipped). Default 1.0 when no history."""
    dates = sorted(cumvols.keys())
    if date in cumvols:
        k = dates.index(date)
    else:                                   # live: today is not in the history yet
        k = len([d for d in dates if d < date])
    prior = [d for d in dates[max(0, k - lookback):k] if d < date]
    if not prior:
        return 1.0
    vals = [cumvols[p][i] for p in prior if len(cumvols[p]) > i]
    return float(today_cum_i / np.mean(vals)) if vals else 1.0


def add_indicators(g: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    g = g.copy()
    g["cumvol"] = g["Volume"].cumsum()
    g["vwap"] = (g["Close"] * g["Volume"]).cumsum() / g["cumvol"]
    g["ema9"] = g["Close"].ewm(span=9, adjust=False).mean()
    tr = pd.concat([g["High"] - g["Low"], (g["High"] - g["Close"].shift()).abs(),
                    (g["Low"] - g["Close"].shift()).abs()], axis=1).max(axis=1)
    g["atr"] = tr.rolling(cfg.atr_len, min_periods=cfg.atr_min_periods).mean()
    return g


def scan_bar(g: pd.DataFrame, i: int, ticker: str, cumvols: dict, fired: set, cfg: Config) -> list:
    """Candidates produced by the COMPLETED bar i of an indicator-enriched session frame `g`.
    `fired` holds modules already fired for this ticker today (each module fires at most once per ticker-day);
    it is updated in place."""
    if i < cfg.first_scan_bar or np.isnan(g["atr"].iloc[i]):
        return []
    row = g.iloc[i]
    m = i * cfg.bar_minutes                                   # engine: m=i*5
    stop_dist = max(g["atr"].iloc[i] * cfg.atr_mult, row["Close"] * cfg.min_stop_frac)
    or15 = g.iloc[:3]
    or15_high, or15_low = or15["High"].max(), or15["Low"].min()
    date = str(g.index[i].date())
    rvol = rvol_at(cumvols, date, i, float(row["cumvol"]), cfg.rvol_lookback_sessions)
    out = []

    def add(module, direction):
        if module in fired:
            return
        fired.add(module)
        out.append(dict(ticker=ticker, date=date, ts=g.index[i], bar=i, minute=m, module=module,
                        direction=direction, rvol=rvol, stop_dist=float(stop_dist),
                        signal_close=float(row["Close"])))

    # P1C ORB-15 trap reject
    if cfg.p1c_min_minute <= m <= cfg.p1c_max_minute:
        prev = g.iloc[i - 1]
        if (prev["High"] > or15_high and row["Close"] < or15_high and row["Close"] < row["ema9"]
                and row["Close"] < row["Open"] and row["Close"] >= row["vwap"] * cfg.p1c_vwap_floor):
            add("P1C", -1)
        if (prev["Low"] < or15_low and row["Close"] > or15_low and row["Close"] > row["ema9"]
                and row["Close"] > row["Open"]):
            add("P1C", 1)
    # P2 midday range-wall pin fade
    if cfg.p2_min_minute <= m <= cfg.p2_max_minute:
        r = g.iloc[:cfg.p2_range_bars]
        hi, lo = r["High"].max(), r["Low"].min()
        if row["High"] >= hi and row["Close"] < row["Open"] and row["Close"] < hi:
            add("P2", -1)
        if row["Low"] <= lo and row["Close"] > row["Open"] and row["Close"] > lo:
            add("P2", 1)
    return out
