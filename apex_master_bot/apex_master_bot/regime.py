"""Risk gate. Only the VIX leg of the strategy doc's regime layer is implemented, because it is the part with
a numeric definition in master_config.json (vix_hard_cap_prior_close = 25) and it never binds in the tested
sample (VIX prior close < 25 on every tested day). The full Regime Engine v4 calculator (bbc_daily.py) is
not in this folder, so its other downgrades are not reproduced."""
import math

LEVELS = ["CALM", "NORMAL", "ELEVATED", "HIGH", "STRESS"]


def vix_band(v: float) -> str:
    if v is None or math.isnan(v):
        return "UNKNOWN"
    return "CALM" if v < 15 else "NORMAL" if v < 20 else "ELEVATED" if v < 25 else "HIGH" if v < 30 else "STRESS"


def gate(vix_prior: float, cap):
    """Returns (allowed, band, reason)."""
    band = vix_band(vix_prior)
    if cap is not None and not math.isnan(vix_prior) and vix_prior >= cap:
        return False, band, f"VIX prior close {vix_prior:.2f} >= {cap:g} ({band})"
    return True, band, ""
