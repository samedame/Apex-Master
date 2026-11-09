"""Timestamped listed verticals and paper payoff scenarios."""
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .calendar_et import NY
from .risk import D

MULTIPLIER = 100
ASSIGNMENT_FLAGS = ("early assignment", "physical delivery", "after-hours exercise and pin risk")


def age_seconds(as_of: dt.datetime, observed: dt.datetime) -> float:
    if as_of.utcoffset() is None or observed.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return (as_of.astimezone(dt.timezone.utc) - observed.astimezone(dt.timezone.utc)).total_seconds()


def valid_market(bid: Decimal, ask: Decimal) -> bool:
    return bid.is_finite() and ask.is_finite() and D(0) < bid <= ask


@dataclass(frozen=True)
class Quote:
    underlying: str
    symbol: str
    expiry: dt.date
    right: str
    strike: Decimal
    bid: Decimal
    ask: Decimal
    observed: dt.datetime
    source: str
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    multiplier: int = MULTIPLIER


@dataclass(frozen=True)
class Reference:
    underlying: str
    price: Decimal
    observed: dt.datetime
    source: str


@dataclass(frozen=True)
class Economics:
    structure: str
    width: Decimal
    credit: bool
    natural: Decimal
    midpoint: Decimal
    round_trip_fees: Decimal
    adverse_slippage: Decimal
    max_loss: Decimal
    max_profit: Decimal
    breakeven: Decimal
    liquidity: int

    @property
    def return_on_risk(self):
        return self.max_profit / self.max_loss


def vertical(long: Quote, short: Quote, ref: Reference, as_of: dt.datetime, *,
             fees: Decimal = D("2.60"), slippage: Decimal = D("2"),
             max_age_s: int = 60, max_skew_s: int = 15) -> Economics:
    """Require provider bid/ask timestamps, standard listed symbols and synchronized observations."""
    if as_of.utcoffset() is None or not 0 < max_age_s <= 60 or not 0 <= max_skew_s <= max_age_s:
        raise ValueError("invalid snapshot cutoff or timing policy")
    if (not ref.source or not ref.price.is_finite() or ref.price <= 0
            or not 0 <= age_seconds(as_of, ref.observed) <= max_age_s):
        raise ValueError("invalid underlying reference")
    if (long.underlying != short.underlying or long.underlying != ref.underlying
            or long.expiry != short.expiry or long.expiry < as_of.astimezone(NY).date()
            or long.right != short.right or long.right not in ("C", "P") or long.source != short.source):
        raise ValueError("incompatible legs")
    for leg in (long, short):
        if not leg.strike.is_finite() or leg.strike <= 0 or leg.multiplier != MULTIPLIER or not leg.source:
            raise ValueError("unsupported contract")
        strike_code = leg.strike * 1000
        expected = f"{leg.underlying}{leg.expiry:%y%m%d}{leg.right}{int(strike_code):08}"
        if strike_code != int(strike_code) or leg.symbol.replace(" ", "") != expected:
            raise ValueError("contract identity mismatch")
        if not valid_market(leg.bid, leg.ask):
            raise ValueError("invalid bid/ask")
        bound = ref.price if leg.right == "C" else leg.strike
        if leg.ask - leg.bid > min(D(".50"), (leg.ask + leg.bid) * D(".125")) or leg.ask > bound:
            raise ValueError("wide or anomalous market")
        if not 0 <= age_seconds(as_of, leg.observed) <= max_age_s:
            raise ValueError("stale or future quote")
        if any(size is not None and (type(size) is not int or size < 0) for size in (leg.bid_size, leg.ask_size)):
            raise ValueError("invalid quote size")
    ages = [age_seconds(as_of, x.observed) for x in (long, short, ref)]
    if max(ages) - min(ages) > max_skew_s:
        raise ValueError("unsynchronized snapshot")
    if not all(x.is_finite() and x >= 0 for x in (fees, slippage)):
        raise ValueError("invalid costs")
    bullish = long.strike < short.strike
    credit = bullish == (long.right == "P")
    width = abs(long.strike - short.strike)
    signed = short.bid - long.ask
    mid_signed = (short.bid + short.ask - long.bid - long.ask) / 2
    natural, midpoint = (signed, mid_signed) if credit else (-signed, -mid_signed)
    if not 0 < natural < width or not 0 < midpoint < width:
        raise ValueError("invalid vertical premium")
    cost = fees + slippage
    max_loss = (width - natural if credit else natural) * MULTIPLIER + cost
    max_profit = (natural if credit else width - natural) * MULTIPLIER - cost
    anchor = short.strike if credit else long.strike
    premium_after_cost = natural + (-cost if credit else cost) / MULTIPLIER
    breakeven = anchor + premium_after_cost * (1 if long.right == "C" else -1)
    structure = f"{'bull' if bullish else 'bear'}_{'call' if long.right == 'C' else 'put'}_{'credit' if credit else 'debit'}"
    return Economics(structure, width, credit, natural, midpoint, fees, slippage, max_loss, max_profit,
                     breakeven, min(long.ask_size or 0, short.bid_size or 0))


def expiry_pnl(long: Quote, short: Quote, economics: Economics, terminal: Decimal) -> Decimal:
    """Simplified intrinsic scenario with costs, excluding exit spread and assignment."""
    if not terminal.is_finite() or terminal <= 0:
        raise ValueError("missing or invalid terminal price")
    sign = 1 if long.right == "C" else -1
    payoff = max(D(0), sign * (terminal - long.strike)) - max(D(0), sign * (terminal - short.strike))
    entry = economics.natural if economics.credit else -economics.natural
    return (payoff + entry) * MULTIPLIER - economics.round_trip_fees - economics.adverse_slippage


def quote_side_pnl(long: Quote, short: Quote, economics: Economics, exit_long: Quote, exit_short: Quote,
                   ref: Reference, exit_as_of: dt.datetime) -> Decimal:
    """Validate a later snapshot and value liquidation by selling the long and buying the short."""
    if ((exit_long.symbol, exit_short.symbol) != (long.symbol, short.symbol)
            or min(exit_long.observed, exit_short.observed) <= max(long.observed, short.observed)):
        raise ValueError("exit quotes must follow entry for the same contracts")
    vertical(exit_long, exit_short, ref, exit_as_of)
    entry = economics.natural if economics.credit else -economics.natural
    return (entry + exit_long.bid - exit_short.ask) * MULTIPLIER - economics.round_trip_fees - economics.adverse_slippage
