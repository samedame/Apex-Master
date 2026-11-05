"""Master v2 quote capture: on a signal day, log the REAL option quotes right after the open and score them at the close.

Why: the v2 evidence is on the underlying. The option fair values in the alert are model-free estimates from realized
open-to-close moves, not market prices. This module measures the gap between the two on every signal day:
  1. a few minutes after the open it snapshots the same-day (0DTE) chain and builds the structures the alert names;
  2. it compares the NATURAL fill (sell at bid, buy at ask) with the empirical fair value (the quote gate, informational);
  3. the next morning, settlement computes each structure's intrinsic P&L at the close, at mid and at the natural fill.
After about ten signals this shows whether spreads eat the edge. Paper only: the bot never places orders.

Limits, stated plainly: Yahoo option quotes can be delayed, so `snap_et` is when the bot looked, not necessarily the quote
time. Exits are scored at intrinsic value at the close (no exit spread), which flatters the result a little.
"""
import csv, datetime as dt, math, os, time
from typing import Callable, Dict, List, Optional
import pandas as pd
from .calendar_et import NY
from . import v2
from .v2 import CALL_DEBIT_FAIR, CALL_DEBIT_FAIR_W100, PUT_FAIR, PUT_FAIR_W50, V2, _jdump, _jload, _state_file

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

    def puts(self, expiry: str) -> pd.DataFrame:
        return self.t.option_chain(expiry).puts[["strike", "bid", "ask"]]

    def calls(self, expiry: str) -> pd.DataFrame:
        return self.t.option_chain(expiry).calls[["strike", "bid", "ask"]]

    def open_price(self, day: dt.date) -> Optional[float]:
        h = self.t.history(period="1d", interval="1m", prepost=False, auto_adjust=False)
        if h is None or h.empty:
            return None
        idx = pd.to_datetime(h.index)
        h = h[[i.date() == day for i in idx]]
        return float(h.Open.iloc[0]) if len(h) else None


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
    return d.dropna(subset=["strike"]).fillna({"bid": 0.0, "ask": 0.0}).sort_values("strike").reset_index(drop=True)


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
    if not (short.ask > 0 and long.ask > 0):
        return {"structure": f"put_{k:.2f}", "dead": True}
    mid = (short.bid + short.ask) / 2 - (long.bid + long.ask) / 2
    nat = float(short.bid - long.ask)
    ws = width / sigma_usd
    fair = fair_put(k, ws)
    return {"structure": f"put_{k:.2f}", "short_k": float(short.strike), "long_k": float(long.strike), "width": width,
            "width_sigma": ws, "mid": float(mid), "nat": nat, "mid_pct": float(mid) / width, "nat_pct": nat / width,
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
    if not (long.ask > 0 and short.ask > 0):
        return {"structure": "call_debit", "dead": True}
    mid = (long.bid + long.ask) / 2 - (short.bid + short.ask) / 2
    nat = float(long.ask - short.bid)                     # pay the ask, sell the bid
    ws = width / sigma_usd
    fair = fair_call(ws)
    return {"structure": "call_debit", "short_k": float(short.strike), "long_k": float(long.strike), "width": width,
            "width_sigma": ws, "mid": float(mid), "nat": nat, "mid_pct": float(mid) / width, "nat_pct": nat / width,
            "fair_pct": fair, "edge_pts": (fair - nat / width) * 100, "gate": _gate(nat / width <= fair, ws, CALL_W_RANGE)}


def build_structures(chain, expiry: str, spot: float, sigma_usd: float) -> List[dict]:
    puts, calls = chain.puts(expiry), chain.calls(expiry)
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

def _append(path: str, fields, row: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def quote_message(day: str, ticker: str, spot: float, sigma_usd: float, expiry: str, is0: bool, rows: List[dict], note: str = "") -> str:
    lines = [f"APEX MASTER v2 - QUOTE CHECK {day} {ticker} (paper): open {spot:.2f}, sigma ${sigma_usd:.2f}, expiry {expiry}{'' if is0 else ' (NOT 0DTE: gate not meaningful)'}. {note}".rstrip()]
    for s in rows:
        if s.get("dead"):
            lines.append(f"- {s['structure']}: no live quote")
            continue
        if s["structure"].startswith("put"):
            lines.append(f"- Put spread {s['short_k']:.0f}/{s['long_k']:.0f} (width {s['width']:.0f}): natural credit {s['nat']:.2f} = {s['nat_pct']:.1%} of width "
                         f"vs fair {s['fair_pct']:.1%} -> {s['gate']} ({s['edge_pts']:+.1f} pts)")
        else:
            lines.append(f"- Call spread {s['long_k']:.0f}/{s['short_k']:.0f} (width {s['width']:.0f}): natural debit {s['nat']:.2f} = {s['nat_pct']:.1%} of width "
                         f"vs fair {s['fair_pct']:.1%} -> {s['gate']} ({s['edge_pts']:+.1f} pts)")
    lines.append("PASS = the natural fill beats the model-free fair value. WIDTH_OFF = listed strikes too coarse for the fair value to apply. Informational: no margin was backtested; exits are not modelled.")
    return "\n".join(lines)


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
    now = now or dt.datetime.now(NY)
    if wait and now.date() == day:
        target = dt.datetime.combine(day, SNAP_AFTER, tzinfo=NY)
        secs = (target - now).total_seconds()
        if 0 < secs <= MAX_WAIT_S:
            sleeper(secs)
            now = target
    ticker, vix = st["ticker"], float(st["vix"])
    for i in range(attempts):
        spot = chain.open_price(day)
        if spot is None:
            if i + 1 < attempts:
                sleeper(retry_s)
            continue
        sigma = spot * vix / 100 / math.sqrt(252)
        exps = chain.expiries()
        expiry = day.isoformat() if day.isoformat() in exps else next((e for e in exps if e >= day.isoformat()), None)
        if expiry is None:
            break
        rows = build_structures(chain, expiry, spot, sigma)
        if any(not s.get("dead") for s in rows):
            snap = (now if i == 0 else dt.datetime.now(NY)).strftime("%H:%M:%S")
            is0 = expiry == day.isoformat()
            for s in rows:
                if s.get("dead"):
                    continue
                _append(os.path.join(ledger_dir, "v2_quotes.csv"), QUOTE_FIELDS,
                        {**s, "day": day.isoformat(), "ticker": ticker, "snap_et": snap, "expiry": expiry, "is_0dte": int(is0),
                         "spot_open": round(spot, 2), "sigma_usd": round(sigma, 3), "gate": s["gate"] if is0 else "N/A"})
            st["quotes_logged"] = True
            _jdump(st, sf)
            notify(quote_message(day.isoformat(), ticker, spot, sigma, expiry, is0, rows))
            return "done"
        if i + 1 < attempts:
            sleeper(retry_s)
    notify(f"APEX MASTER v2 - QUOTE CHECK {day.isoformat()} {ticker}: no live option quotes after {attempts} tries (Yahoo may be delayed or the chain empty). "
           f"Read the live chain by hand and compare with the fair values in the alert; log your fill.")
    return "no-quotes"


# ---------------------------------------------------------------- settlement of the quote log

def settle_quotes(day: str, close: float, ledger_dir: str) -> int:
    """Score every logged 0DTE structure for `day` at the close (intrinsic). Idempotent. Returns rows written."""
    qp = os.path.join(ledger_dir, "v2_quotes.csv")
    if not os.path.exists(qp):
        return 0
    rp = os.path.join(ledger_dir, "v2_quote_results.csv")
    done = set()
    if os.path.exists(rp):
        done = {(r.day, r.structure) for r in pd.read_csv(rp).itertuples()}
    q = pd.read_csv(qp)
    q = q[(q.day == day) & (q.is_0dte == 1)]
    n = 0
    for r in q.itertuples():
        if (r.day, r.structure) in done:
            continue
        s = {"structure": r.structure, "short_k": r.short_k, "long_k": r.long_k, "width": r.width, "mid": r.mid, "nat": r.nat}
        _append(rp, RESULT_FIELDS, {"day": day, "ticker": r.ticker, "structure": r.structure, "close": close,
                                    "pnl_mid_pct": round(pnl_at_close(s, close, "mid"), 4), "pnl_nat_pct": round(pnl_at_close(s, close, "nat"), 4),
                                    "gate": r.gate})
        n += 1
    return n


def quote_summary(ledger_dir: str) -> str:
    rp = os.path.join(ledger_dir, "v2_quote_results.csv")
    if not os.path.exists(rp):
        return ""
    r = pd.read_csv(rp)
    if r.empty:
        return ""
    g = r.groupby("structure").agg(n=("day", "count"), nat=("pnl_nat_pct", "mean"), mid=("pnl_mid_pct", "mean"))
    parts = [f"{s} n={int(x.n)} nat {x.nat:+.1%} mid {x.mid:+.1%}" for s, x in g.iterrows()]
    return "Option paper results (intrinsic at the close, % of width): " + "; ".join(parts)
