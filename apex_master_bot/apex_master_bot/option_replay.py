"""Offline JSONL option quote ingestion and replay. No provider calls and no orders."""
import argparse
import datetime as dt
import json
from dataclasses import asdict

import numpy as np

from .calendar_et import NY, OPEN_T, session_close
from .options_execution import ASSIGNMENT_FLAGS, Quote, Reference, age_seconds, expiry_pnl, quote_side_pnl, vertical
from .risk import Account, D, assess
from .v2 import is_session_day


def snapshot(payload):
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be an object")
    as_of = dt.datetime.fromisoformat(payload["as_of"])
    ref_data = payload["underlying"]
    ref = Reference(ref_data["symbol"], D(str(ref_data["price"])),
                    dt.datetime.fromisoformat(ref_data["observed"]), ref_data["source"])
    legs = []
    for key in ("long", "short"):
        row = dict(payload[key])
        for field in ("strike", "bid", "ask"):
            row[field] = D(str(row[field]))
        row["expiry"] = dt.date.fromisoformat(row["expiry"])
        row["observed"] = dt.datetime.fromisoformat(row["observed"])
        legs.append(Quote(**row))
    day = as_of.astimezone(NY).date()
    opening = dt.datetime.combine(day, OPEN_T, tzinfo=NY)
    closing = dt.datetime.combine(day, session_close(day), tzinfo=NY)
    if not is_session_day(day) or not all(
        age_seconds(t, opening) >= 0 and age_seconds(closing, t) >= 0
        for t in (as_of, ref.observed, legs[0].observed, legs[1].observed)
    ):
        raise ValueError("snapshot outside regular session")
    return as_of, ref, *legs


def replay_record(payload):
    as_of, ref, long, short = snapshot(payload["entry"])
    eco = vertical(long, short, ref, as_of)
    same_day = long.expiry == as_of.astimezone(NY).date()
    # User-supplied quote data establishes economics only. The repository has no validated
    # option strategy or synchronized paper account ledger.
    risk = assess(Account(), eco.max_loss, eco.max_loss, eco.liquidity, fresh=True)
    result = {"entry": payload["entry"], "economics": asdict(eco), "risk": asdict(risk),
              "return_on_risk": eco.return_on_risk, "0dte": same_day,
              "long_moneyness": long.strike / ref.price - 1,
              "short_moneyness": short.strike / ref.price - 1,
              "bid_ask_age_s": {leg.symbol: age_seconds(as_of, leg.observed) for leg in (long, short)},
              "flags": [*ASSIGNMENT_FLAGS, "research only"],
              "quote_side_pnl": None, "expiry_scenario": None,
              "etf_share_benchmark": {"entry_reference": ref.price, "pnl_per_share": None,
                                      "risk": asdict(assess(Account(), ref.price, ref.price, 1,
                                                            spread=False, fresh=True))}}
    if "exit" in payload:
        exit_at, exit_ref, exit_long, exit_short = snapshot(payload["exit"])
        if age_seconds(exit_at, as_of) <= 0:
            raise ValueError("exit cutoff must follow entry cutoff")
        result["etf_share_benchmark"]["pnl_per_share"] = exit_ref.price - ref.price
        result["quote_side_pnl"] = quote_side_pnl(long, short, eco, exit_long, exit_short, exit_ref, exit_at)
    if "terminal_scenarios" in payload:
        if not same_day:
            raise ValueError("intraday expiry scenarios require 0DTE")
        pnl = [float(expiry_pnl(long, short, eco, D(str(px)))) for px in payload["terminal_scenarios"]]
        if not pnl:
            raise ValueError("empty terminal scenario set")
        result["expiry_scenario"] = {
            "label": "equal-weight sensitivity only, simplified expiry intrinsic, no exit spread or assignment",
            "n": len(pnl), "mean_pnl": float(np.mean(pnl)),
            "pnl_5_95_percentiles": np.quantile(pnl, [.05, .95]).tolist(),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl")
    args = parser.parse_args()
    failed = False
    with open(args.jsonl, encoding="utf-8") as file:
        for line_no, line in enumerate(file, 1):
            if not line.strip():
                continue
            try:
                result = replay_record(json.loads(line))
            except (ArithmeticError, ValueError, TypeError, KeyError, OverflowError) as exc:
                failed = True
                result = {"status": "DATA FAILURE", "reason": str(exc)}
            print(json.dumps({"line": line_no, **result}, default=str, allow_nan=False))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
