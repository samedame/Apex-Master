"""Observable regime diagnostics. Features never change the frozen v2 decision."""
import datetime as dt
import json
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .options_execution import age_seconds


@dataclass(frozen=True)
class Observation:
    name: str
    value: float
    known_at: dt.datetime
    source: str


@dataclass(frozen=True)
class Event:
    name: str
    scheduled_at: dt.datetime
    announced_at: dt.datetime
    source: str
    published_at: Optional[dt.datetime] = None
    surprise: Optional[float] = None


def event_calendar(events, *, as_of, until, since=None):
    """Return schedules announced by AS_OF. Mask outcomes until publication."""
    since = as_of if since is None else since
    horizon = age_seconds(until, since)
    if horizon < 0:
        raise ValueError("event horizon precedes AS_OF")
    result = []
    for event in events:
        if not event.source or age_seconds(as_of, event.announced_at) < 0:
            continue
        if not 0 <= age_seconds(event.scheduled_at, since) <= horizon:
            continue
        outcome = event.published_at is not None and age_seconds(as_of, event.published_at) >= 0
        result.append({"name": event.name, "scheduled_at": event.scheduled_at.isoformat(),
                       "announced_at": event.announced_at.isoformat(), "source": event.source,
                       "surprise": event.surprise if outcome else None})
    return sorted(result, key=lambda row: dt.datetime.fromisoformat(row["scheduled_at"]))


def load_events(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    for row in rows:
        for field in ("scheduled_at", "announced_at", "published_at"):
            if row.get(field) is not None:
                row[field] = dt.datetime.fromisoformat(row[field])
    return [Event(**row) for row in rows]


def assess_regime(observations, *, as_of, max_age=dt.timedelta(days=4)):
    latest = {}
    for obs in observations:
        age = age_seconds(as_of, obs.known_at)
        if not obs.source or not math.isfinite(obs.value) or not 0 <= age <= max_age.total_seconds():
            continue
        if obs.name not in latest or latest[obs.name].known_at < obs.known_at:
            latest[obs.name] = obs
    components = [latest[name] for name in ("SPY_trend20", "QQQ_trend20", "IWM_trend20") if name in latest]
    score = 50 + 50 * sum((x.value > 0) - (x.value < 0) for x in components) / 3 if len(components) == 3 else None
    vix = latest.get("vix")
    return {"as_of": as_of.isoformat(), "display_score": score,
            "state": "uncertain" if score is None else "bullish" if score >= 75 else "bearish" if score <= 25 else "neutral",
            "bullish_probability": None, "bearish_probability": None,
            "volatility": "unknown" if vix is None else "elevated" if vix.value >= 20 else "below 20",
            "confidence": "uncalibrated", "factors": [x.name for x in components],
            "observations": {x.name: {"value": x.value, "source": x.source,
                                     "known_at": x.known_at.isoformat(),
                                     "age_s": age_seconds(as_of, x.known_at)} for x in latest.values()},
            "skip_reasons": ["no independently validated directional model"]
            + (["missing or stale market inputs"] if score is None or vix is None else [])}


def daily_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Close-known features on an already aligned session grid. Missing rows remain missing."""
    close = bars.Close.where(bars.Close > 0)
    returns = close.pct_change(fill_method=None)
    prior = close.shift()
    true_range = pd.concat([bars.High - bars.Low, (bars.High - prior).abs(), (bars.Low - prior).abs()], axis=1)
    return pd.DataFrame({
        "return": returns,
        "gap": bars.Open / prior - 1,
        "intraday": close / bars.Open - 1,
        "ibs": (close - bars.Low) / (bars.High - bars.Low).where(bars.High > bars.Low),
        "trend20": close / close.rolling(20).mean() - 1,
        "atr14": true_range.max(axis=1, skipna=False).rolling(14).mean(),
        "rv20": returns.rolling(20).std() * math.sqrt(252),
    })
