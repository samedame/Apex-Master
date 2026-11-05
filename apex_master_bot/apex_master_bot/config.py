"""Every constant here is copied from the tested pipeline (backtest/engine.py, exit_opt.py, make_final.py).

Source of each value is noted so it can be audited against the backtest code.
"""
from dataclasses import dataclass, field, replace
from typing import Optional, Tuple

TZ = "America/New_York"


@dataclass(frozen=True)
class Config:
    # --- universe / modules (make_final.build: module in P1C,P2 and ticker in SPY,QQQ,IWM) ---
    universe: Tuple[str, ...] = ("SPY", "QQQ", "IWM")
    module_priority: dict = field(default_factory=lambda: {"P1C": 0, "P2": 1})

    # --- bars (engine.load: 5-minute bars, 09:30..15:55 ET) ---
    bar_minutes: int = 5
    session_open: str = "09:30"
    session_last_bar: str = "15:55"
    min_bars_per_session: int = 60          # engine: `if len(g)<60: continue` (skips half days)
    skip_first_dataset_session: bool = True  # engine: `if first_pos==0: continue`
    first_scan_bar: int = 3                  # engine: range(3, len(g)-2)

    # --- indicators (engine.candidates_for) ---
    atr_len: int = 14
    atr_min_periods: int = 5
    atr_mult: float = 0.9                    # stop_dist = max(0.9*ATR14, close*0.0008)
    min_stop_frac: float = 0.0008
    rvol_lookback_sessions: int = 20         # RVOL_MAP: cum volume vs mean of prior 20 sessions, same slot

    # --- P1C ORB-15 trap reject (engine: 16<=m<=104) ---
    p1c_min_minute: int = 16
    p1c_max_minute: int = 104
    p1c_vwap_floor: float = 0.998            # shorts need close >= vwap*0.998
    # --- P2 midday range-wall pin fade (engine: 75<=m<=239; wall = high/low of first 15 bars) ---
    p2_min_minute: int = 75
    p2_max_minute: int = 239
    p2_range_bars: int = 15

    # --- exit (exit_opt.sim_simple, variant simple_tp1.2_mb20) ---
    target_R: float = 1.2
    stop_R: float = 1.0                      # stop tested on bar CLOSE only
    max_hold_bars: int = 20                  # 20 x 5m = 100 minutes
    cost_R: float = 0.15                     # deducted from every trade

    # --- selection (make_final.build: sort by date, module priority, |rvol-1|; head(1)) ---
    # Live-only policy, because the tested pick needs the whole day's candidates. See README.
    live_selection: str = "first_fire"

    # --- gates (NOT part of the tested selection; neutral on the tested sample) ---
    vix_prior_cap: Optional[float] = 25.0    # master_config.json regime_gate.vix_hard_cap_prior_close
    # --- optional doc-only layers, OFF because they were never backtested ---
    veto_rvol_above: Optional[float] = None  # strategy doc: 1.65
    min_quality_score: Optional[float] = None  # strategy doc: 60

    # --- risk (strategy doc section 2; live mode only) ---
    risk_pct: float = 0.50
    risk_pct_elevated: float = 0.25
    weekly_stop_R: float = -3.0


PROFILES = {
    # adopted profile, +1.2R target. Tested: n=57 win 70.2% mean +0.306R PF 1.74
    "reliability": Config(),
    # runner profile, +2.5R target. Tested: n=57 win 59.6% mean +0.601R PF 2.14
    "runner": replace(Config(), target_R=2.5),
}
