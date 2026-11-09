"""Prospective paired ETF shadow test and indicative 0DTE quote observations."""
import datetime as dt
import math
from dataclasses import replace
from pathlib import Path

from .calendar_et import NY, OPEN_T, session_close
from .options_execution import D
from .risk import Account, assess
from .state_io import git_revision, ledger_lock
from .v2 import DataError, V2, _jdump, _jload, decide, is_session_day
from .v2_quotes import FEES, SLIPPAGE, _valid

SHADOW = replace(V2, order=("QQQ", "IWM", "SPY"))
VERSION = "qqq-first-v1"
ENTRY_START = dt.time(9, 31)
ENTRY_END = dt.time(9, 45)
EXIT_WINDOW = dt.timedelta(minutes=15)


def _selection(day, now, state_dir):
    path = Path(state_dir) / "v2" / f"{day}.json"
    baseline = _jload(path) if path.exists() else {}
    result = {"session": str(day), "version": VERSION, "paper_only": True,
              "recorded_at": now.isoformat(), "commit": git_revision(),
              "v2_checked_at": baseline.get("checked_at"), "baseline": baseline.get("ticker"),
              "qqq_first": None, "decision": "SKIP", "reason": "NO_PREOPEN_V2_DECISION",
              "options": {}, "contracts_authorized": 0}
    if now.time() >= OPEN_T:
        result["reason"] = "MISSED_PREOPEN_SELECTION"
        return result
    if baseline.get("decision") not in ("TRADE", "NO_TRADE") or not baseline.get("checked_at"):
        return result
    checked = dt.datetime.fromisoformat(baseline["checked_at"]).astimezone(NY)
    if checked.date() != day or checked.time() >= OPEN_T or checked > now or baseline.get("late"):
        return result
    shadow = decide(baseline["ibs"], baseline["vix"], SHADOW)
    result.update(qqq_first=shadow["ticker"], prior_session=baseline["prior_session"],
                  prior_vix=baseline["vix"], prior_ibs=baseline["ibs"], vix_source=baseline["vix_source"])
    if not shadow["trade"]:
        result["reason"] = "NO_SIGNAL"
        return result
    result.update(decision="PAPER_SIGNAL", reason=shadow["reason"],
                  options={ticker: {} for ticker in dict.fromkeys((baseline["ticker"], shadow["ticker"]))})
    return result


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def _leg(row):
    import pandas as pd

    trade_at = pd.to_datetime(row.get("lastTradeDate"), utc=True, errors="coerce")
    return {"symbol": str(row.contractSymbol), "strike": _number(row.strike),
            "bid": _number(row.bid), "ask": _number(row.ask), "bid_size": None, "ask_size": None,
            "quote_observed_at": None, "quote_age_seconds": None,
            "last_trade_at": trade_at.isoformat() if pd.notna(trade_at) else None}


def _snapshot(day, ticker, phase, existing, chain, clock, window_end):
    row = {"status": "SKIP", "reason": "MISSING_CHAIN", "contracts_authorized": 0}
    if phase == "exit" and not existing.get("legs"):
        return {**row, "reason": "NO_PINNED_ENTRY_CONTRACTS", "captured_at": clock().isoformat()}
    try:
        source = chain(ticker)
        row["source"] = source.source
        if str(day) not in source.expiries():
            return {**row, "reason": "NO_0DTE_LISTING", "captured_at": clock().isoformat()}
        if phase == "entry":
            spot = _number(source.open_price(day))
            if spot is None or spot <= 0:
                return {**row, "reason": "MISSING_OPEN_REFERENCE", "captured_at": clock().isoformat()}
            row["reference"] = {"price": spot, "bar_start": dt.datetime.combine(day, OPEN_T, tzinfo=NY).isoformat()}
        _, calls = source.tables(str(day))
        captured = clock()
        row.update(captured_at=captured.isoformat(), expiry=str(day), indicative=True)
        if captured >= window_end:
            return {**row, "reason": "MISSED_WINDOW"}
        if "contractSize" in calls:
            calls = calls[calls.contractSize == "REGULAR"]
        calls = calls[calls.contractSymbol.notna()].copy().reset_index(drop=True)
        calls["strike"] = calls.strike.map(_number)
        calls = calls[calls.strike > 0].drop_duplicates("contractSymbol", keep=False)
        if phase == "entry":
            # Fixed prospectively: nearest listed call to the ETF open, then next higher strike.
            calls = calls.sort_values(["strike", "contractSymbol"]).drop_duplicates("strike", keep=False)
            if calls.empty:
                return {**row, "reason": "NO_LISTED_CALLS"}
            long = calls.loc[(calls.strike - spot).abs().idxmin()]
            higher = calls[calls.strike > long.strike]
            if higher.empty:
                return {**row, "reason": "NO_HIGHER_STRIKE"}
            short = higher.iloc[0]
        else:
            calls = calls.set_index("contractSymbol", drop=False)
            ids = [existing["legs"][side]["symbol"] for side in ("long", "short")]
            if any(symbol not in calls.index for symbol in ids):
                return {**row, "reason": "PINNED_CONTRACT_MISSING"}
            long, short = (calls.loc[symbol] for symbol in ids)
            if any(leg.strike != existing["legs"][side]["strike"]
                   for side, leg in (("long", long), ("short", short))):
                return {**row, "reason": "PINNED_CONTRACT_CHANGED"}
        row["legs"] = {"long": _leg(long), "short": _leg(short)}
        width = D(str(short.strike)) - D(str(long.strike))
        row["width"] = str(width)
        for leg in (long, short):
            strike_code = D(str(leg.strike)) * 1000
            expected = f"{ticker}{day:%y%m%d}C{int(strike_code):08}"
            if strike_code != int(strike_code) or str(leg.contractSymbol).replace(" ", "") != expected:
                return {**row, "reason": "INVALID_CONTRACT_IDENTITY"}
        prices = row["legs"]
        if any(prices[side][field] is None for side in prices for field in ("bid", "ask")):
            return {**row, "reason": "MISSING_BID_ASK"}
        if not all(_valid(leg) for leg in (long, short)):
            return {**row, "reason": "INVALID_OR_WIDE_BID_ASK"}
        if phase == "entry":
            premium = D(str(long.ask)) - D(str(short.bid))
            if not 0 < premium < width:
                return {**row, "reason": "INVALID_NATURAL_DEBIT"}
            loss = premium * 100 + FEES + SLIPPAGE
            risk = assess(Account(), loss, loss, 0)
            return {**row, "reason": "UNAFFORDABLE" if risk.reason.endswith("POSITION TOO LARGE") else "QUOTE_TIME_UNVERIFIED",
                    "natural_debit_per_share": str(premium), "max_loss_one_contract": str(loss),
                    "fees": str(FEES), "adverse_slippage": str(SLIPPAGE), "risk_status": risk.reason}
        premium = D(str(long.bid)) - D(str(short.ask))
        if not -width < premium < width:
            return {**row, "reason": "ANOMALOUS_LIQUIDATION_VALUE"}
        return {**row, "status": "INDICATIVE_MARK", "reason": "QUOTE_TIME_UNVERIFIED",
                "natural_liquidation_per_share": str(premium)}
    except Exception as exc:
        return {**row, "reason": "PROVIDER_OR_SCHEMA_FAILURE", "error_type": type(exc).__name__,
                "captured_at": clock().isoformat()}


def _settle_benchmarks(ledger_dir, day, now, provider):
    # Retry recently unposted close bars. Only prospectively selected sessions can settle.
    if provider is None:
        return
    files = sorted((Path(ledger_dir) / "shadow").glob("????-??-??.json"))[-10:]
    daily = {}
    for path in files:
        session = dt.date.fromisoformat(path.stem)
        ready = dt.datetime.combine(session, session_close(session), tzinfo=NY) + dt.timedelta(minutes=20)
        if session > day or now < ready:
            continue
        result = _jload(path)
        if result["decision"] != "PAPER_SIGNAL":
            continue
        options = result["options"]
        for legs in options.values():
            for phase in ("entry", "exit"):
                legs.setdefault(phase, {"status": "SKIP", "reason": "MISSED_WINDOW",
                                        "recorded_at": now.isoformat(), "contracts_authorized": 0})
        if not result.get("etf_benchmark"):
            marks = {}
            for ticker in options:
                try:
                    if ticker not in daily:
                        daily[ticker] = provider.daily(ticker)
                    bars = daily[ticker]
                    match = bars[bars.index.date == session]
                    if len(match) != 1:
                        continue
                    opening, closing = (_number(match.iloc[0][field]) for field in ("Open", "Close"))
                    if opening is not None and closing is not None and min(opening, closing) > 0:
                        marks[ticker] = {"open": opening, "close": closing,
                                         "net_bp": (closing / opening - 1) * 10000 - V2.cost_bp}
                except (DataError, OSError, TypeError, ValueError, RuntimeError):
                    continue
            if len(marks) == len(options):
                result["etf_benchmark"] = {
                    "scored_at": now.isoformat(), "source": type(provider).__name__, "no_fills": True,
                    "assumed_cost_bp": V2.cost_bp, "by_ticker": marks,
                    "qqq_first_minus_baseline_bp": marks[result["qqq_first"]]["net_bp"] - marks[result["baseline"]]["net_bp"],
                }
            else:
                result["etf_benchmark_status"] = "MISSING_CLOSE_BAR"
            if result.get("etf_benchmark"):
                result.pop("etf_benchmark_status", None)
        _jdump(result, path)


@ledger_lock
def run(phase, state_dir, ledger_dir, chain, provider=None, clock=None, session=None):
    """Operate on today's Eastern session only, without changing baseline state."""
    clock = clock or (lambda: dt.datetime.now(NY))
    now = clock().astimezone(NY)
    day = now.date()
    if session is not None and session != str(day):
        return "wrong-session"
    if not is_session_day(day):
        return "closed"
    path = Path(ledger_dir) / "shadow" / f"{day}.json"
    close = dt.datetime.combine(day, session_close(day), tzinfo=NY)
    entry_start = dt.datetime.combine(day, ENTRY_START, tzinfo=NY)
    entry_end = dt.datetime.combine(day, ENTRY_END, tzinfo=NY)
    exit_start = close - EXIT_WINDOW
    if phase == "auto":
        if now.time() < OPEN_T:
            return "too-early"
        if now < entry_start:
            return "too-early"
        phase = "entry" if now < entry_end else "exit" if exit_start <= now < close else "reconcile"
    if phase == "entry" and now < entry_start:
        return "too-early"
    if phase == "exit" and now < exit_start:
        return "too-early"
    if phase == "reconcile" and now < close:
        return "between-windows"

    result = _jload(path) if path.exists() else _selection(day, now, state_dir)
    if phase == "select" and result["reason"] == "NO_PREOPEN_V2_DECISION" and now.time() < OPEN_T:
        result = _selection(day, now, state_dir)
    _jdump(result, path)
    if phase == "reconcile":
        _settle_benchmarks(ledger_dir, day, now, provider)
        return "reconciled"
    if phase == "select" or result["decision"] != "PAPER_SIGNAL":
        return result["reason"]
    end = entry_end if phase == "entry" else close
    for ticker, marks in result["options"].items():
        if phase in marks:
            continue
        stamp = clock().astimezone(NY)
        marks[phase] = (_snapshot(day, ticker, phase, marks.get("entry", {}), chain,
                                  lambda: clock().astimezone(NY), end)
                        if stamp < end else {"status": "SKIP", "reason": "MISSED_WINDOW",
                                             "recorded_at": stamp.isoformat(), "contracts_authorized": 0})
        _jdump(result, path)
    return phase
