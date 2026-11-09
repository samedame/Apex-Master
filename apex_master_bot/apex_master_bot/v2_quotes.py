"""Indicative Yahoo chain snapshots alongside timestamped paper execution research."""
import datetime as dt, math, os, time
from typing import Callable, List, Optional
import pandas as pd
from .calendar_et import NY, OPEN_T, session_close
from .options_execution import D
from .risk import Account, assess
from .state_io import append_unique, git_revision, ledger_lock
from .v2 import is_session_day
from .v2 import CALL_DEBIT_FAIR, CALL_DEBIT_FAIR_W100, PUT_FAIR, PUT_FAIR_W50, _jdump, _jload, _state_file

PUT_WIDTH_SIGMA = 0.25
CALL_WIDTH_SIGMA = 0.5
CALL_FAIR = CALL_DEBIT_FAIR["long at open, width 0.5 sigma"]
SNAP_AFTER = dt.time(9, 31)                  # first minute with real quotes
MAX_WAIT_S = 15 * 60

QUOTE_FIELDS = ["day", "ticker", "snap_et", "expiry", "is_0dte", "spot_open", "sigma_usd", "structure", "short_k", "long_k", "width",
                "width_sigma", "mid", "nat", "mid_pct", "nat_pct", "fair_pct", "edge_pts", "gate"]
RESULT_FIELDS = ["day", "ticker", "structure", "close", "pnl_mid_pct", "pnl_nat_pct", "gate"]


# ---------------------------------------------------------------- chain providers

class YahooChain:
    """Same-day option chains from Yahoo (via yfinance). Quotes may be delayed; zero bid/ask means no live quote."""

    def __init__(self, ticker: str):
        import yfinance as yf
        self.t = yf.Ticker(ticker)

    def expiries(self) -> List[str]:
        return list(self.t.options)

    source = "Yahoo Finance via yfinance"
    def tables(self, expiry: str):
        chain = self.t.option_chain(expiry)
        return chain.puts, chain.calls

    def open_price(self, day: dt.date) -> Optional[float]:
        h = self.t.history(period="1d", interval="1m", prepost=False, auto_adjust=False)
        if h is None or h.empty or h.index.tz is None:
            return None
        opening = dt.datetime.combine(day, OPEN_T, tzinfo=NY)
        rows = h[h.index == opening]
        return float(rows.Open.iloc[0]) if len(rows) == 1 else None


# ---------------------------------------------------------------- structures

PUT_W_RANGE = (0.20, 0.60)          # width in sigma units where interpolating the model-free fair value is reasonable
CALL_W_RANGE = (0.40, 1.20)


def fair_put(k: float, width_sigma: float) -> float:
    """Empirical fair credit (share of width) at the width the listed strikes allow, interpolated between 0.25 and 0.5 sigma."""
    f25, f50 = PUT_FAIR[k][1], PUT_FAIR_W50[k]
    return f25 + (f50 - f25) * (width_sigma - PUT_WIDTH_SIGMA) / PUT_WIDTH_SIGMA


def fair_call(width_sigma: float) -> float:
    f50, f100 = CALL_FAIR, CALL_DEBIT_FAIR_W100
    return f50 + (f100 - f50) * (width_sigma - CALL_WIDTH_SIGMA) / CALL_WIDTH_SIGMA


def _gate(ok: bool, ws: float, rng) -> str:
    if not (rng[0] <= ws <= rng[1]):
        return "WIDTH_OFF"           # listed strikes are too coarse for the fair value to apply: look at the chain by hand
    return "PASS" if ok else "FAIL"

def _clean(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in ("strike", "bid", "ask"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[d.strike.map(math.isfinite) & (d.strike > 0)].drop_duplicates("strike", keep=False).sort_values("strike").reset_index(drop=True)


def _valid(leg):
    bid, ask = leg.bid, leg.ask
    return (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask
            and ask - bid <= min(.50, max(.05, (bid + ask) * .125)))


def _leg(leg):
    symbol = leg.get("contractSymbol")
    return {"symbol": symbol if isinstance(symbol, str) else None, "bid": float(leg.bid),
            "ask": float(leg.ask), "bid_size": None, "ask_size": None, "quote_at": None}


def _row(d: pd.DataFrame, strike: float):
    return d.loc[(d.strike - strike).abs().idxmin()]


def put_spread(puts: pd.DataFrame, spot: float, sigma_usd: float, k: float) -> Optional[dict]:
    """Bull put credit spread: short at the listed strike at or below open - k sigma, long about 0.25 sigma lower."""
    d = _clean(puts)
    below = d[d.strike <= spot - k * sigma_usd]
    if below.empty:
        return None
    short = below.iloc[-1]
    lower = d[d.strike < short.strike]
    if lower.empty:
        return None
    long = _row(lower, short.strike - PUT_WIDTH_SIGMA * sigma_usd)
    width = float(short.strike - long.strike)
    if not (_valid(short) and _valid(long)):
        return {"structure": f"put_{k:.2f}", "dead": True}
    mid = (short.bid + short.ask) / 2 - (long.bid + long.ask) / 2
    nat = float(short.bid - long.ask)
    ws = width / sigma_usd
    if not (0 < nat < width and 0 < mid < width):
        return {"structure": f"put_{k:.2f}", "dead": True, "gate": _gate(False, ws, PUT_W_RANGE)}
    fair = fair_put(k, ws)
    return {"structure": f"put_{k:.2f}", "short_k": float(short.strike), "long_k": float(long.strike), "width": width,
            "short_leg": _leg(short), "long_leg": _leg(long), "width_sigma": ws, "mid": float(mid), "nat": nat, "mid_pct": float(mid) / width, "nat_pct": nat / width,
            "fair_pct": fair, "edge_pts": (nat / width - fair) * 100, "gate": _gate(nat / width >= fair and nat > 0, ws, PUT_W_RANGE)}


def call_spread(calls: pd.DataFrame, spot: float, sigma_usd: float) -> Optional[dict]:
    """Bull call debit spread: long at the listed strike nearest the open, short about 0.5 sigma higher."""
    d = _clean(calls)
    if d.empty:
        return None
    long = _row(d, spot)
    upper = d[d.strike > long.strike]
    if upper.empty:
        return None
    short = _row(upper, long.strike + CALL_WIDTH_SIGMA * sigma_usd)
    width = float(short.strike - long.strike)
    if not (_valid(short) and _valid(long)):
        return {"structure": "call_debit", "dead": True}
    mid = (long.bid + long.ask) / 2 - (short.bid + short.ask) / 2
    nat = float(long.ask - short.bid)                     # pay the ask, sell the bid
    ws = width / sigma_usd
    if not (0 < nat < width and 0 < mid < width):
        return {"structure": "call_debit", "dead": True, "gate": _gate(False, ws, CALL_W_RANGE)}
    fair = fair_call(ws)
    return {"structure": "call_debit", "short_k": float(short.strike), "long_k": float(long.strike), "width": width,
            "short_leg": _leg(short), "long_leg": _leg(long), "width_sigma": ws, "mid": float(mid), "nat": nat, "mid_pct": float(mid) / width, "nat_pct": nat / width,
            "fair_pct": fair, "edge_pts": (fair - nat / width) * 100, "gate": _gate(nat / width <= fair, ws, CALL_W_RANGE)}


def build_structures(chain, expiry: str, spot: float, sigma_usd: float) -> List[dict]:
    if not all(math.isfinite(x) and x > 0 for x in (spot, sigma_usd)):
        raise ValueError("invalid open reference or volatility")
    puts, calls = chain.tables(expiry) if hasattr(chain, "tables") else (chain.puts(expiry), chain.calls(expiry))
    out = [put_spread(puts, spot, sigma_usd, k) for k in PUT_FAIR] + [call_spread(calls, spot, sigma_usd)]
    return [s for s in out if s]


def pnl_at_close(s: dict, close: float, fill: str) -> float:
    """Intrinsic P&L at expiry as a share of width. fill = 'mid' or 'nat'. No exit spread is charged."""
    w, px = s["width"], s["mid"] if fill == "mid" else s["nat"]
    if s["structure"].startswith("put"):
        loss = min(w, max(0.0, s["short_k"] - close))
        return (px - loss) / w
    payoff = min(w, max(0.0, close - s["long_k"]))
    return (payoff - px) / w


# ---------------------------------------------------------------- run

FEES = D("2.60")
SLIPPAGE = D("2")


def quote_message(day, ticker, spot, sigma_usd, expiry, is0, rows, note=""):
    lines = [f"APEX MASTER — DAILY DECISION | {day} | {ticker} | QUOTE CHECK",
             f"Original v2 TRADE SIGNAL. ETF benchmark open {spot:.2f} → close. Volatility proxy ${sigma_usd:.2f}.",
             f"{note} | Expiry {expiry}" + ("" if is0 else " (NOT 0DTE, research only)"),
             "Indicative quotes. Provider bid/ask timestamps and displayed sizes unavailable.",
             "Experimental regime uncertain. ETF evidence only. No calibrated probability."]
    for row in rows:
        if row.get("dead"):
            lines.append(f"- {row['structure']}: invalid quote or premium")
            continue
        loss, profit, decision = _indicative_risk(row)
        action = "credit" if row["structure"].startswith("put") else "debit"
        gate = f" | {row['gate']} model comparison" if is0 else ""
        lines.append(f"- {row['structure']} short/long {row['short_k']:g}/{row['long_k']:g} "
                     f"${row['nat'] * 100:.2f} {action}{gate}. "
                     f"Max loss ${loss:.2f}, profit ${profit:.2f}. {decision.reason} ({decision.count} contracts).")
    lines.extend([f"One-contract costs: ${FEES} fees and ${SLIPPAGE} adverse slippage.",
                  "Final status: SKIP — zero contracts on the $1,500 paper account. No fill recorded."])
    return "\n".join(lines)


def _indicative_risk(row):
    credit = row["structure"].startswith("put")
    width, price = D(str(row["width"])), D(str(row["nat"]))
    cost = FEES + SLIPPAGE
    loss = (width - price if credit else price) * 100 + cost
    profit = (price if credit else width - price) * 100 - cost
    return loss, profit, assess(Account(), loss, loss, 0)


@ledger_lock
def run_quotes(day: dt.date, chain, state_dir: str, ledger_dir: str, notify: Callable[[str], None], now: Optional[dt.datetime] = None,
               sleeper: Callable[[float], None] = time.sleep, attempts: int = 3, retry_s: int = 30, wait: bool = True) -> str:
    """Snapshot real quotes for today's v2 signal. Returns 'no-trade', 'done', 'already', or 'no-quotes'."""
    sf = _state_file(state_dir, day.isoformat())
    if not os.path.exists(sf):
        return "no-trade"
    st = _jload(sf)
    if st.get("decision") != "TRADE":
        return "no-trade"
    if st.get("quotes_logged"):
        return "already"
    clock = (lambda: now) if now is not None else (lambda: dt.datetime.now(NY))
    if st.get("quote_snapshot"):
        return _finish_snapshot(st, sf, ledger_dir, notify)
    now = clock().astimezone(NY)
    if now.date() != day or not is_session_day(day):
        return "outside-session"
    if wait and now.date() == day:
        target = dt.datetime.combine(day, SNAP_AFTER, tzinfo=NY)
        secs = (target - now).total_seconds()
        if 0 < secs <= MAX_WAIT_S:
            sleeper(secs)
            now = max(target, clock().astimezone(NY))
    ticker, vix = st["ticker"], float(st["vix"])
    close_at = dt.datetime.combine(day, session_close(day), tzinfo=NY)
    source = getattr(chain, "source", type(chain).__name__)
    for i in range(attempts):
        if not dt.datetime.combine(day, SNAP_AFTER, tzinfo=NY) <= now < close_at:
            return "outside-session"
        try:
            spot = chain.open_price(day)
            if spot is None:
                raise ValueError("opening bar missing")
            sigma = spot * vix / 100 / math.sqrt(252)
            expiry = min((e for e in chain.expiries() if e >= day.isoformat()), default=None)
            rows = build_structures(chain, expiry, spot, sigma) if expiry else []
        except (ValueError, KeyError, TypeError, RuntimeError, OSError):
            rows = []
        captured = max(now, clock().astimezone(NY))
        if captured >= close_at:
            return "outside-session"
        if any(not row.get("dead") for row in rows):
            is0 = expiry == day.isoformat()
            log_rows = []
            details = []
            for row in rows:
                if row.get("dead"):
                    details.append(row)
                    continue
                log_rows.append({**row, "day": day.isoformat(), "ticker": ticker,
                                 "snap_et": captured.strftime("%H:%M:%S"), "expiry": expiry, "is_0dte": int(is0),
                                 "spot_open": round(spot, 2), "sigma_usd": round(sigma, 3),
                                 "gate": row["gate"] if is0 else "N/A"})
                loss, profit, risk = _indicative_risk(row)
                details.append({**row, "max_loss": str(loss), "max_profit": str(profit),
                                "contracts_allowed": risk.count, "risk_status": risk.reason})
            if not st.get("quote_snapshot"):
                st["quote_snapshot"] = {"captured_at": captured.isoformat(), "expiry": expiry,
                                        "source": source, "indicative": True, "rows": details,
                                        "underlying": ticker, "spot_open": spot,
                                        "reference_at": dt.datetime.combine(day, OPEN_T, tzinfo=NY).isoformat(),
                                        "commit": git_revision(), "strategy_version": "v3-paper",
                                        "fees": str(FEES), "slippage": str(SLIPPAGE), "ledger_rows": log_rows}
                _jdump(st, sf)
            return _finish_snapshot(st, sf, ledger_dir, notify)
        if i + 1 < attempts:
            sleeper(retry_s)
            now = max(now, clock().astimezone(NY))
    if not st.get("quote_failure_alerted"):
        st["quote_failure_alerted"] = True
        _jdump(st, sf)
        notify(f"APEX MASTER v2 | {day} {ticker} | DATA FAILURE: no live option quotes after {attempts} tries. "
               "ETF benchmark preserved. Zero contracts authorized.")
    return "no-quotes"


def _finish_snapshot(st, sf, ledger_dir, notify):
    snapshot = st["quote_snapshot"]
    append_unique(os.path.join(ledger_dir, "v2_quotes.csv"), QUOTE_FIELDS, snapshot["ledger_rows"],
                  ("day", "structure"))
    st["quotes_logged"] = True
    _jdump(st, sf)
    notify(quote_message(st["day"], st["ticker"], snapshot["spot_open"],
                         snapshot["ledger_rows"][0]["sigma_usd"], snapshot["expiry"],
                         snapshot["expiry"] == st["day"], snapshot["rows"],
                         f"Captured {snapshot['captured_at']} ET | {snapshot['source']}"))
    return "done"


# ---------------------------------------------------------------- settlement of the quote log

def settle_quotes(day: str, close: float, ledger_dir: str) -> int:
    """Score every logged 0DTE structure for `day` at the close (intrinsic). Idempotent. Returns rows written."""
    qp = os.path.join(ledger_dir, "v2_quotes.csv")
    if not os.path.exists(qp):
        return 0
    rp = os.path.join(ledger_dir, "v2_quote_results.csv")
    if not math.isfinite(close) or close <= 0:
        return 0
    q = pd.read_csv(qp)
    q = q[(q.day == day) & (q.is_0dte == 1)]
    rows = []
    for r in q.itertuples():
        s = {"structure": r.structure, "short_k": r.short_k, "long_k": r.long_k, "width": r.width, "mid": r.mid, "nat": r.nat}
        rows.append({"day": day, "ticker": r.ticker, "structure": r.structure, "close": close,
                                    "pnl_mid_pct": round(pnl_at_close(s, close, "mid"), 4), "pnl_nat_pct": round(pnl_at_close(s, close, "nat"), 4),
                                    "gate": r.gate})
    return append_unique(rp, RESULT_FIELDS, rows, ("day", "structure"))


def quote_summary(ledger_dir: str) -> str:
    rp = os.path.join(ledger_dir, "v2_quote_results.csv")
    if not os.path.exists(rp):
        return ""
    r = pd.read_csv(rp)
    if r.empty:
        return ""
    g = r.groupby("structure").agg(n=("day", "count"), nat=("pnl_nat_pct", "mean"), mid=("pnl_mid_pct", "mean"))
    parts = [f"{s} n={int(x.n)} nat {x.nat:+.1%} mid {x.mid:+.1%}" for s, x in g.iterrows()]
    return "Option paper results (simplified expiry intrinsic, no exit spread or assignment, % of width): " + "; ".join(parts)
