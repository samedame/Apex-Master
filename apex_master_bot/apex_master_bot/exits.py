"""Exit logic: port of backtest/exit_opt.py `sim_simple` (variant simple_tp1.2_mb20).

Entry = OPEN of the bar after the signal bar. Per bar: target if the bar HIGH (low for shorts) reaches
+target_R; else stop if the bar CLOSE is at or beyond -1R (never an intrabar stop); else after
max_hold_bars exit at that bar's close. 0.15R cost is deducted from every outcome.

`evaluate` serves both replay (all bars complete) and live (last bar may still be forming: only the
target can trigger on a forming bar, exactly as the target is intrabar in the backtest).
"""
import numpy as np
from .config import Config


def evaluate(O, H, L, C, idx, direction, stop_dist, cfg: Config, last_complete=None, session_over=True,
             entry=None):
    """Returns dict(status='open'|'closed', R, reason, bars). `last_complete` = index of the last completed
    bar (defaults to the last bar). Bars after it are treated as forming (target check only)."""
    n = len(C)
    if last_complete is None:
        last_complete = n - 1
    if idx + 1 >= n:
        return dict(status="open", R=None, reason=None, bars=0, entry=entry)
    entry = float(O[idx + 1]) if entry is None else entry
    for j in range(idx + 1, min(n, idx + 1 + cfg.max_hold_bars)):
        if direction == 1:
            highR = (H[j] - entry) / stop_dist; closeR = (C[j] - entry) / stop_dist
        else:
            highR = (entry - L[j]) / stop_dist; closeR = (entry - C[j]) / stop_dist
        if highR >= cfg.target_R:
            return dict(status="closed", R=cfg.target_R - cfg.cost_R, reason="tp", bars=j - idx, entry=entry)
        if j > last_complete:                       # forming bar: nothing else can fire yet
            return dict(status="open", R=None, reason=None, bars=j - idx, entry=entry)
        if closeR <= -cfg.stop_R:
            return dict(status="closed", R=closeR - cfg.cost_R, reason="stop", bars=j - idx, entry=entry)
    t = min(n - 1, idx + cfg.max_hold_bars)
    time_due = (idx + cfg.max_hold_bars <= last_complete) or (session_over and last_complete >= n - 1)
    if not time_due:
        return dict(status="open", R=None, reason=None, bars=last_complete - idx, entry=entry)
    final = (C[t] - entry) / stop_dist if direction == 1 else (entry - C[t]) / stop_dist
    return dict(status="closed", R=float(final) - cfg.cost_R, reason="time", bars=cfg.max_hold_bars, entry=entry)
