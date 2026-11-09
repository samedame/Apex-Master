"""Master v2 (regime-gated IBS dip-buy): pre-open paper alert. The bot never places orders.

Rule (research/master_v2/README.md): previous VIX close >= 20 AND previous-day IBS < 0.10; take the first of
SPY, QQQ, IWM in that order; long at the open, exit at the close; at most one trade per day.
IBS = (close - low) / (high - low).

Everything needed is known before the open, so one pre-open check is the whole job. `decide()` is the single
rule used by both the live check and the 30-year replay, so the replay test proves the live logic.
Each later morning the check also settles earlier signal days into the paper ledger and applies the forward-test
pause/retire rules.
"""
import datetime as dt, io, json, math, os, urllib.request
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import pandas as pd
from .calendar_et import BASE, NY, OPEN_T, holidays, session_close
from .state_io import append_unique, atomic_text, git_revision, ledger_lock
from .market_regime import Observation, assess_regime, event_calendar, load_events


@dataclass(frozen=True)
class V2Config:
    vix_min: float = 20.0                    # previous VIX close >= this (no upper cap: VIX >= 25 gave 69.5% of the profit)
    ibs_max: float = 0.10                    # previous-day IBS strictly below this
    order: Tuple[str, ...] = ("SPY", "QQQ", "IWM")
    cost_bp: float = 2.0                     # round trip on the underlying, as backtested
    vix_tolerance: float = 0.5               # Yahoo vs FRED VIX close may differ by this much before we call it a conflict
    pause_cum_bp: float = -1600.0            # forward-test plan: pause if cumulative net return falls below this
    retire_at_trades: int = 40               # forward-test plan: retire if the mean is <= 0 at this many trades
    haircut_bp: float = 9.0                  # planning figure: about half of the in-sample +18.19 bp


V2 = V2Config()

# Empirical, model-free fair values on the 734 pick days (strikes in units of sigma from the open, sigma = VIX_prior/100/sqrt(252)).
# put credit spread, width 0.25 sigma: short strike distance -> (historical win rate, fair credit as share of width)
PUT_FAIR = {0.50: (0.768, 0.203), 0.75: (0.838, 0.137), 1.00: (0.888, 0.093)}
CALL_DEBIT_FAIR = {"long at open, width 0.5 sigma": 0.452}
# same pick days, width 0.5 sigma instead of 0.25 sigma (used to interpolate when the listed strikes force another width)
PUT_FAIR_W50 = {0.50: 0.170, 0.75: 0.115, 1.00: 0.076}
CALL_DEBIT_FAIR_W100 = 0.337


class DataError(Exception):
    """Inputs are missing, stale or inconsistent. The check then makes NO decision and says so loudly."""


def ibs_of(high: float, low: float, close: float) -> Optional[float]:
    if (any(x is None or not math.isfinite(x) for x in (high, low, close))
            or not 0 < low < high or not low <= close <= high):
        return None
    return (close - low) / (high - low)


def decide(ibs: Dict[str, Optional[float]], vix_prior: float, cfg: V2Config = V2) -> dict:
    """The rule. ibs maps ticker -> previous-day IBS (None if unavailable). Pure function."""
    out = {"trade": False, "ticker": None, "reason": "", "vix": vix_prior, "ibs": dict(ibs)}
    if vix_prior is None or math.isnan(vix_prior):
        out["reason"] = "no VIX"
        return out
    if vix_prior < cfg.vix_min:
        out["reason"] = f"VIX {vix_prior:.2f} < {cfg.vix_min:g}: calm-market regime, the signal loses money here"
        return out
    for t in cfg.order:
        v = ibs.get(t)
        if v is not None and v < cfg.ibs_max:
            out.update(trade=True, ticker=t, reason=f"VIX {vix_prior:.2f} >= {cfg.vix_min:g} and {t} IBS {v:.3f} < {cfg.ibs_max:g}")
            return out
    out["reason"] = f"VIX {vix_prior:.2f} >= {cfg.vix_min:g} but no ETF has IBS < {cfg.ibs_max:g}"
    return out


# ---------------------------------------------------------------- replay (30-year parity with the research)

def replay(data_dir: str, cfg: V2Config = V2, start: str = "1993-02-01") -> pd.DataFrame:
    """Re-run the rule over saved daily bars. Needs SPY/QQQ/IWM_1d.csv and VIX_1d.csv (Yahoo format)."""
    daily = {t: load_daily_csv(os.path.join(data_dir, f"{t}_1d.csv")) for t in cfg.order}
    vix = load_daily_csv(os.path.join(data_dir, "VIX_1d.csv"))["Close"]
    prep = {}
    for t, d in daily.items():
        rng = (d.High - d.Low).where((d.High - d.Low) != 0)
        prep[t] = (d.index, ((d.Close - d.Low) / rng).tolist(), d.Open.tolist(), d.Close.tolist())
    vi, vv = vix.index, vix.tolist()
    dates = sorted(set().union(*[set(p[0]) for p in prep.values()]))
    rows = []
    for d0 in dates:
        if d0 < pd.Timestamp(start):
            continue
        ibs = {}
        for t, (idx, ib, _, _) in prep.items():
            p = idx.searchsorted(d0) - 1                      # previous row of this ticker's own series
            v = ib[p] if p >= 0 else None
            ibs[t] = None if v is None or v != v else v
        pv = vi.searchsorted(d0) - 1
        vp = vv[pv] if pv >= 0 else float("nan")
        dec = decide(ibs, vp, cfg)
        if not dec["trade"]:
            continue
        idx, _, op, cl = prep[dec["ticker"]]
        j = idx.searchsorted(d0)
        if j >= len(idx) or idx[j] != d0:                      # the ETF must have traded that day (as in the research)
            continue
        oc = cl[j] / op[j] - 1
        rows.append({"date": d0.date().isoformat(), "ticker": dec["ticker"], "ibs_prior": dec["ibs"][dec["ticker"]],
                     "vix_prior": vp, "open": op[j], "close": cl[j], "oc": oc, "net_bp": oc * 1e4 - cfg.cost_bp})
    return pd.DataFrame(rows)


def load_daily_csv(path: str) -> pd.DataFrame:
    d = pd.read_csv(path, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_localize(None).normalize()
    d = d[~d.index.duplicated()].sort_index()
    for c in ("Open", "High", "Low", "Close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["Open", "High", "Low", "Close"])


# ---------------------------------------------------------------- data providers

class YahooV2:
    """Live feed: Yahoo daily bars for the three ETFs and ^VIX, plus FRED VIXCLS as an independent VIX check."""

    def __init__(self):
        import yfinance as yf
        self.yf = yf

    def daily(self, ticker: str) -> pd.DataFrame:
        try:
            d = self.yf.Ticker(ticker).history(period="2mo", interval="1d", auto_adjust=False, timeout=10)
        except Exception as exc:
            raise DataError(f"{ticker}: Yahoo fetch failed ({type(exc).__name__})") from exc
        if d is None or d.empty:
            raise DataError(f"no daily bars for {ticker}")
        d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
        return d[~d.index.duplicated(keep="last")].sort_index()[["Open", "High", "Low", "Close"]].dropna()

    def vix(self) -> pd.Series:
        return self.daily("^VIX")["Close"].astype(float)

    def fred_vix(self) -> Optional[pd.Series]:
        try:
            req = urllib.request.Request("https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
                                         headers={"User-Agent": "apex-master-bot"})
            with urllib.request.urlopen(req, timeout=20) as r:
                df = pd.read_csv(io.StringIO(r.read().decode()))
            df.columns = ["date", "v"]
            df["v"] = pd.to_numeric(df["v"], errors="coerce")
            df = df.dropna()
            return pd.Series(df.v.values, index=pd.to_datetime(df.date)).sort_index()
        except Exception:
            return None


class CsvV2:
    """Saved-bars provider for tests and offline checks. Same file layout as research/master_v2/data."""

    def __init__(self, data_dir: str):
        self.dir = data_dir

    def daily(self, ticker: str) -> pd.DataFrame:
        name = "VIX" if ticker == "^VIX" else ticker
        return load_daily_csv(os.path.join(self.dir, f"{name}_1d.csv"))[["Open", "High", "Low", "Close"]]

    def vix(self) -> pd.Series:
        return self.daily("^VIX")["Close"].astype(float)

    def fred_vix(self) -> Optional[pd.Series]:
        p = os.path.join(self.dir, "FRED_VIXCLS.csv")
        if not os.path.exists(p):
            return None
        df = pd.read_csv(p); df.columns = ["date", "v"]; df["v"] = pd.to_numeric(df["v"], errors="coerce"); df = df.dropna()
        return pd.Series(df.v.values, index=pd.to_datetime(df.date)).sort_index()


# ---------------------------------------------------------------- the pre-open check

def expected_prior_session(day: dt.date) -> dt.date:
    """Last weekday before `day` that is not an NYSE holiday (market_holidays.txt). Half days count as sessions."""
    h = holidays()
    d = day - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in h:
        d -= dt.timedelta(days=1)
    return d


def is_session_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day.isoformat() not in holidays()


def _prior_bar_vix(provider, day: dt.date, cfg: V2Config) -> Tuple[float, str]:
    """Previous VIX close, validated against the expected prior session and cross-checked with FRED."""
    exp = pd.Timestamp(expected_prior_session(day))
    v = provider.vix()
    v = v[v.index < pd.Timestamp(day)]
    if v.empty or v.index[-1] != exp:
        raise DataError(f"VIX: last bar is {v.index[-1].date() if len(v) else 'none'}, expected {exp.date()}")
    y = float(v.iloc[-1])
    if not math.isfinite(y) or y <= 0:
        raise DataError("invalid prior Yahoo VIX")
    f = provider.fred_vix()
    if f is None or exp not in f.index:
        return y, "Yahoo only (FRED not yet posted)"
    fv = float(f.loc[exp])
    if not math.isfinite(fv) or fv <= 0:
        raise DataError("invalid prior FRED VIX")
    if (fv >= cfg.vix_min) != (y >= cfg.vix_min):
        raise DataError(f"VIX sources disagree across the gate: Yahoo {y:.2f}, FRED {fv:.2f}")
    if abs(fv - y) > cfg.vix_tolerance:
        return y, f"Yahoo {y:.2f}, FRED {fv:.2f} (differ, same side of the gate)"
    return y, f"Yahoo and FRED agree ({fv:.2f})"


def check(day: dt.date, provider, cfg: V2Config = V2, diagnostics=None) -> dict:
    """Decision for the session on `day`, from data through the previous session only."""
    if not is_session_day(day):
        return {"day": day.isoformat(), "decision": "CLOSED", "reason": "not a session day"}
    exp = pd.Timestamp(expected_prior_session(day))
    vix, vsrc = _prior_bar_vix(provider, day, cfg)
    ibs, bars = {}, {}
    for t in cfg.order:
        d = provider.daily(t)
        d = d[d.index < pd.Timestamp(day)]
        if d.empty or d.index[-1] != exp:
            raise DataError(f"{t}: last bar is {d.index[-1].date() if len(d) else 'none'}, expected {exp.date()}")
        r = d.iloc[-1]
        ibs[t] = ibs_of(float(r.High), float(r.Low), float(r.Close))
        if ibs[t] is None:
            raise DataError(f"{t}: invalid previous-session high/low/close")
        history = d.Close.tail(20)
        if diagnostics is not None and len(history) == 20 and all(math.isfinite(x) and x > 0 for x in history):
            diagnostics[f"{t}_trend20"] = float(history.iloc[-1] / history.mean() - 1)
        bars[t] = {"high": float(r.High), "low": float(r.Low), "close": float(r.Close)}
    if diagnostics is not None:
        diagnostics["vix"] = vix
    dec = decide(ibs, vix, cfg)
    out = {"day": day.isoformat(), "decision": "TRADE" if dec["trade"] else "NO_TRADE", "reason": dec["reason"], "vix": vix,
           "vix_source": vsrc, "ibs": ibs, "ticker": dec["ticker"], "prior_session": exp.date().isoformat()}
    if dec["trade"]:
        c = bars[dec["ticker"]]["close"]
        out["prior_close"] = c
        out["sigma_pct"] = vix / 100 / math.sqrt(252) * 100
        out["sigma_usd"] = c * vix / 100 / math.sqrt(252)
    return out


def trade_alert(r: dict, late: bool = False, cfg: V2Config = V2) -> str:
    events = ", ".join(f"{e['name']} {e['scheduled_at'][11:16]} ET" for e in r.get("events", []))
    return "\n".join([
        f"APEX MASTER — DAILY DECISION | {r['day']} | {r.get('checked_at', 'timestamp unavailable')}",
        f"Original v2 TRADE SIGNAL — {r['ticker']} | {r['reason']}",
        f"Prior session {r['prior_session']} | {r['vix_source']}",
        "Frozen ETF benchmark: long at the open, exit at the close, one entry, no intraday stop.",
        f"Experimental regime: {r.get('regime', {}).get('state', 'uncertain')} | "
        f"volatility {r.get('regime', {}).get('volatility', 'unknown')}. No calibrated directional probability.",
        "Scheduled risk: calendar unavailable." if r.get("event_data_error")
        else f"Scheduled risk: {events}" if events
        else "Scheduled risk: no event in the partial calendar for this session.",
        "ETF replay: 734 trades, +18.19 bp/trade after assumed 2 bp costs. Options evidence unverified.",
        "LATE — official open is a benchmark only." if late else "Option economics pending a post-open snapshot.",
        "Final status: PAPER ONLY — benchmark signal. Zero contracts authorized.",
    ])


def data_alert(day: dt.date, err: str) -> str:
    return (f"APEX MASTER — DAILY DECISION | {day.isoformat()} | "
            f"Original v2 NO DECISION | DATA FAILURE — {err}. Zero contracts authorized.")


# ---------------------------------------------------------------- ledger, state, settlement

CHECK_FIELDS = ["day", "decision", "ticker", "vix", "vix_source", "ibs_SPY", "ibs_QQQ", "ibs_IWM", "reason", "late"]
TRADE_FIELDS = ["day", "ticker", "vix", "ibs", "open", "close", "gross_bp", "net_bp", "cum_net_bp", "n"]


def _append(path: str, fields, row: dict):
    key = ("day", "decision") if fields == CHECK_FIELDS else ("day",)
    return append_unique(path, fields, [row], key)


def _jload(path):
    with open(path) as f:
        return json.load(f)


def _jdump(obj, path):
    atomic_text(path, json.dumps(obj, indent=1, allow_nan=False) + "\n")


def _state_file(state_dir: str, day: str) -> str:
    d = os.path.join(state_dir, "v2")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{day}.json")


def _read_trades(ledger_dir: str) -> pd.DataFrame:
    p = os.path.join(ledger_dir, "v2_trades.csv")
    return pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=TRADE_FIELDS)


def _settle(today: dt.date, provider, state_dir: str, ledger_dir: str, notify, cfg: V2Config = V2) -> list:
    """Score earlier signal days (paper) from the daily open and close once the bar exists. Returns messages sent."""
    sent = []
    sd = os.path.join(state_dir, "v2")
    if not os.path.isdir(sd):
        return sent
    for fn in sorted(os.listdir(sd)):
        if not fn.endswith(".json"):
            continue
        st = _jload(os.path.join(sd, fn))
        if st.get("decision") != "TRADE" or st.get("settled") or st["day"] >= today.isoformat():
            continue
        d = provider.daily(st["ticker"])
        ts = pd.Timestamp(st["day"])
        if ts not in d.index:
            continue                                            # bar not posted yet: try again next run
        r = d.loc[ts]
        if not all(math.isfinite(float(x)) and float(x) > 0 for x in (r.Open, r.Close)):
            continue
        gross = (float(r.Close) / float(r.Open) - 1) * 1e4
        net = gross - cfg.cost_bp
        tr = _read_trades(ledger_dir)
        existing = tr[tr.day == st["day"]]
        cum, n = ((float(tr.net_bp.sum()) + net, len(tr) + 1) if existing.empty
                  else (float(existing.iloc[0].cum_net_bp), int(existing.iloc[0].n)))
        _append(os.path.join(ledger_dir, "v2_trades.csv"), TRADE_FIELDS,
                {"day": st["day"], "ticker": st["ticker"], "vix": st["vix"], "ibs": st["ibs"][st["ticker"]], "open": float(r.Open),
                 "close": float(r.Close), "gross_bp": round(gross, 2), "net_bp": round(net, 2), "cum_net_bp": round(cum, 2), "n": n})
        try:
            from .v2_quotes import settle_quotes
            marked = settle_quotes(st["day"], float(r.Close), ledger_dir)
        except Exception as e:                                   # quote scoring must never block settlement
            notify(f"APEX MASTER v2: quote scoring error {type(e).__name__}: {str(e)[:120]}")
            continue  # the ETF ledger is idempotent, so retry quote settlement next run
        st["settled"] = True
        _jdump(st, os.path.join(sd, fn))
        timing = "missed/late signal" if st.get("late") else "signal"
        msg = (f"APEX MASTER v2 - ETF benchmark ({timing}, no recorded fill) {st['day']}: {st['ticker']} open {float(r.Open):.2f} -> close {float(r.Close):.2f}, "
               f"{net:+.1f} bp net. Forward test: {n} trades, cumulative {cum:+.0f} bp, mean {cum / n:+.1f} bp.")
        if marked:
            msg += f" {marked} option scenarios scored at simplified expiry intrinsic, excluding exit spreads and assignment."
        if cum < cfg.pause_cum_bp:
            msg += f"\nPAUSE AND REVIEW: cumulative {cum:+.0f} bp is below the {cfg.pause_cum_bp:.0f} bp limit from the forward-test plan."
        if n >= cfg.retire_at_trades and cum / n <= 0:
            msg += f"\nRETIRE: {n} trades and the mean is {cum / n:+.1f} bp (<= 0), the retire rule in the forward-test plan."
        notify(msg)
        sent.append(msg)
    return sent


settle = ledger_lock(_settle)


def _run_check(day: dt.date, provider, state_dir: str, ledger_dir: str, notify, now: Optional[dt.datetime] = None,
              cfg: V2Config = V2) -> dict:
    """Settle earlier signals, then decide for `day`. Idempotent: a day already decided is not alerted twice."""
    try:
        _settle(day, provider, state_dir, ledger_dir, notify, cfg)
    except Exception as e:                                       # settlement must never block the decision
        notify(f"APEX MASTER v2: settlement error {type(e).__name__}: {str(e)[:160]}")
    _mark_start(state_dir, day)
    sf = _state_file(state_dir, day.isoformat())
    if os.path.exists(sf):
        prev = _jload(sf)
        if prev.get("decision") in ("TRADE", "NO_TRADE", "CLOSED"):
            return prev
    clock = (lambda: now) if now is not None else (lambda: dt.datetime.now(NY))
    diagnostics = {}
    try:
        r = check(day, provider, cfg, diagnostics=diagnostics)
    except DataError as e:
        r = {"day": day.isoformat(), "decision": "NO_DECISION", "reason": str(e)}
    checked = clock().astimezone(NY)
    late = checked.date() != day or checked.time() >= OPEN_T
    provenance = {"checked_at": checked.isoformat(), "strategy_version": "v2",
                  "commit": git_revision(), "provider": type(provider).__name__}
    if r["decision"] == "NO_DECISION":
        r.update(provenance, late=late)
        added = _append(os.path.join(ledger_dir, "v2_checks.csv"), CHECK_FIELDS, {**r, "late": int(late)})
        _jdump(r, sf)
        if added:
            notify(data_alert(day, r["reason"]))
        return r
    if diagnostics:
        # Receipt time is conservative. Daily feeds do not expose original publication timestamps.
        r["regime"] = assess_regime(
            [Observation(name, value, checked, provenance["provider"]) for name, value in diagnostics.items()],
            as_of=checked,
        )
    if checked.date() == day and r["decision"] != "CLOSED":
        try:
            r["events"] = event_calendar(load_events(os.path.join(BASE, "research_events.json")),
                                         as_of=checked, since=dt.datetime.combine(day, dt.time(), tzinfo=NY),
                                         until=dt.datetime.combine(day, session_close(day), tzinfo=NY))
        except (OSError, ValueError, TypeError):
            r["event_data_error"] = True
    r.update(provenance, late=late)
    if r["decision"] != "CLOSED":
        _append(os.path.join(ledger_dir, "v2_checks.csv"), CHECK_FIELDS,
                {**r, "ibs_SPY": r.get("ibs", {}).get("SPY"), "ibs_QQQ": r.get("ibs", {}).get("QQQ"), "ibs_IWM": r.get("ibs", {}).get("IWM"),
                 "late": int(late)})
    _jdump(r, sf)
    if r["decision"] == "TRADE":
        notify(trade_alert(r, late, cfg))
    return r


# ---------------------------------------------------------------- watchdog: a silent day must never hide a dead bot

run_check = ledger_lock(_run_check)

WATCHDOG_AFTER = dt.time(9, 35)              # before this the 09:20 dispatch may still be running; do nothing


def _mark_start(state_dir: str, day: dt.date):
    """The forward test starts on the first day the module runs. Backfill never reaches before it."""
    p = os.path.join(state_dir, "v2", "_start.json")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _jdump({"start": day.isoformat()}, p)


def _start(state_dir: str) -> Optional[dt.date]:
    p = os.path.join(state_dir, "v2", "_start.json")
    return dt.date.fromisoformat(_jload(p)["start"]) if os.path.exists(p) else None


def prior_sessions(day: dt.date, n: int) -> list:
    out, d = [], day
    while len(out) < n:
        d = expected_prior_session(d)
        out.append(d)
    return out


@ledger_lock
def run_watchdog(day: dt.date, provider, state_dir: str, ledger_dir: str, notify, now: Optional[dt.datetime] = None,
                 lookback: int = 10, cfg: V2Config = V2) -> dict:
    """If today's check never ran, say so and run it now (flagged LATE). Also score any earlier session days the bot missed,
    from the start of the forward test, so every signal day counts even if the dispatch failed. Silent when all is well."""
    now = (now or dt.datetime.now(NY)).astimezone(NY)
    out = {"ran_today": False, "backfilled": []}
    if now.date() == day and now.time() < WATCHDOG_AFTER:
        return out
    start = _start(state_dir)
    if is_session_day(day):
        sf = os.path.join(state_dir, "v2", f"{day.isoformat()}.json")
        ok = os.path.exists(sf) and _jload(sf).get("decision") in ("TRADE", "NO_TRADE")
        if ok:
            _settle(day, provider, state_dir, ledger_dir, notify, cfg)
        else:
            if not os.path.exists(sf):
                notify(f"APEX MASTER v2 WATCHDOG: no v2 check was logged for {day.isoformat()} by {now:%H:%M} ET (the 09:20 run did not happen or failed). Running it now.")
            _run_check(day, provider, state_dir, ledger_dir, notify, now=now, cfg=cfg)
            out["ran_today"] = True
            start = start or day
    else:
        _settle(day, provider, state_dir, ledger_dir, notify, cfg)
    if start is None:
        return out
    for d in prior_sessions(day, lookback):
        if d < start:
            continue
        sf = os.path.join(state_dir, "v2", f"{d.isoformat()}.json")
        existing = _jload(sf) if os.path.exists(sf) else None
        if existing and existing.get("decision") != "NO_DECISION":
            continue
        try:
            r = check(d, provider, cfg)
        except DataError as e:
            if existing:
                continue
            r = {"day": d.isoformat(), "decision": "NO_DECISION", "reason": f"backfill: {e}"}
        r.update(late=True, backfilled=True, checked_at=now.isoformat(), strategy_version="v2",
                 commit=git_revision(), provider=type(provider).__name__)
        if r["decision"] != "CLOSED":
            _append(os.path.join(ledger_dir, "v2_checks.csv"), CHECK_FIELDS,
                    {**r, "ibs_SPY": r.get("ibs", {}).get("SPY"), "ibs_QQQ": r.get("ibs", {}).get("QQQ"), "ibs_IWM": r.get("ibs", {}).get("IWM"), "late": 1})
        _jdump(r, sf)
        out["backfilled"].append((d.isoformat(), r["decision"]))
        if r["decision"] == "TRADE":
            notify(f"APEX MASTER v2 WATCHDOG: {d.isoformat()} was a MISSED SIGNAL ({r['ticker']}: {r['reason']}). It is scored on paper next, because every signal day counts in the forward test.")
    return out



def run_eod(provider, state_dir, ledger_dir, notify, now=None):
    now = (now or dt.datetime.now(NY)).astimezone(NY)
    day = now.date()
    close = dt.datetime.combine(day, session_close(day), tzinfo=NY)
    if not is_session_day(day) or now < close + dt.timedelta(minutes=20):
        return []
    return settle(day + dt.timedelta(days=1), provider, state_dir, ledger_dir, notify)


def status(ledger_dir: str, cfg: V2Config = V2) -> str:
    """One-line forward-test summary (also the weekly heartbeat, since no-trade days are silent)."""
    cp = os.path.join(ledger_dir, "v2_checks.csv")
    checks = pd.read_csv(cp) if os.path.exists(cp) else pd.DataFrame(columns=CHECK_FIELDS)
    tr = _read_trades(ledger_dir)
    n = len(tr)
    last = checks.day.iloc[-1] if len(checks) else "never"
    sig = int((checks.decision == "TRADE").sum()) if len(checks) else 0
    nd = int((checks.decision == "NO_DECISION").sum()) if len(checks) else 0
    base = f"APEX MASTER v2 weekly: {len(checks)} checks (last {last}), {sig} signals, {nd} data failures, {n} settled paper trades"
    if n:
        base += f", cumulative {tr.net_bp.sum():+.0f} bp, mean {tr.net_bp.mean():+.1f} bp, hit {(tr.net_bp > 0).mean():.0%}"
    else:
        base += f". Quiet is normal: the rule fires about 24 times a year, only when VIX >= {cfg.vix_min:g}."
    try:
        from .v2_quotes import quote_summary
        q = quote_summary(ledger_dir)
        if q:
            base += "\n" + q
    except Exception:
        pass
    return base
