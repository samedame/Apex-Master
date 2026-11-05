"""One trade per day.

`select_tested` is the rule that produced the published results (backtest/make_final.py):
    sort the day's P1C/P2 index candidates by (module priority P1C before P2, |RVOL - 1|) and take the first.
It needs every candidate of the day, including ones that appear later than the entry bar, so it can only be
run in replay. `pick_first_fire` is the causal rule the live bot has to use instead.
"""
from .config import Config


def rank_key(c: dict, cfg: Config):
    return (cfg.module_priority[c["module"]], abs(c["rvol"] - 1.0))


def eligible(cands, cfg: Config):
    out = [c for c in cands if c["ticker"] in cfg.universe and c["module"] in cfg.module_priority]
    if cfg.veto_rvol_above is not None:
        out = [c for c in out if c["rvol"] <= cfg.veto_rvol_above]
    return out


def select_tested(day_cands, cfg: Config):
    pool = eligible(day_cands, cfg)
    return sorted(pool, key=lambda c: rank_key(c, cfg))[0] if pool else None


def pick_first_fire(new_cands, cfg: Config):
    """Candidates that completed on the same bar are ranked with the tested key; earliest bar always wins."""
    pool = eligible(new_cands, cfg)
    return sorted(pool, key=lambda c: rank_key(c, cfg))[0] if pool else None
