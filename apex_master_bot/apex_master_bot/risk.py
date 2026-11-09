"""Cash-backed paper risk limits. One assessment considers one alternative, never a basket."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

D = Decimal


@dataclass(frozen=True)
class Limits:
    intended: Decimal = D(".01")
    hard: Decimal = D(".02")
    daily: Decimal = D(".02")
    weekly: Decimal = D(".05")
    correlated: Decimal = D(".02")
    entries: int = 2

    def __post_init__(self):
        values = (self.intended, self.hard, self.daily, self.weekly, self.correlated)
        if not all(x.is_finite() and x > 0 for x in values):
            raise ValueError("invalid risk limits")
        if not (self.intended <= self.hard <= D(".02") and self.daily <= D(".02")
                and self.weekly <= D(".05") and self.entries in (1, 2)):
            raise ValueError("limits exceed paper policy")


@dataclass(frozen=True)
class Account:
    equity: Decimal = D("1500")
    settled_cash: Decimal = D("1500")
    buying_power: Decimal = D("1500")
    day_start_equity: Decimal = D("1500")
    week_start_equity: Decimal = D("1500")
    daily_committed: Decimal = D("0")
    weekly_loss: Decimal = D("0")
    correlated_open: Decimal = D("0")
    entries_today: int = 0
    v2_entries_today: int = 0
    mode: str = "cash"
    spread_approved: bool = False
    second_strategy_approved: bool = False
    integrity_ok: bool = False


@dataclass(frozen=True)
class Decision:
    count: int
    reason: str


def assess(account: Account, loss: Decimal, cash_required: Decimal, liquidity: int,
           *, limits: Limits = Limits(), spread: bool = True, v2: bool = True,
           supported: bool = False, fresh: bool = False, increases_position: bool = False) -> Decision:
    balances = (account.equity, account.settled_cash, account.buying_power, account.day_start_equity,
                account.week_start_equity, account.daily_committed, account.weekly_loss, account.correlated_open)
    if (not all(x.is_finite() and x >= 0 for x in balances)
            or min(account.equity, account.day_start_equity, account.week_start_equity) <= 0
            or any(type(x) is not int for x in (liquidity, account.entries_today, account.v2_entries_today))
            or not 0 <= account.v2_entries_today <= account.entries_today
            or liquidity < 0
            or account.mode not in ("cash", "margin")
            or not loss.is_finite() or loss <= 0 or not cash_required.is_finite() or cash_required <= 0):
        return Decision(0, "DATA FAILURE — INVALID RISK INPUT")
    daily_cap = min(account.equity, account.day_start_equity) * limits.daily
    budget = min(account.equity * limits.intended, account.equity * limits.hard,
                 daily_cap - account.daily_committed,
                 account.equity * limits.correlated - account.correlated_open)
    loss = loss.quantize(D(".01"), rounding=ROUND_CEILING)
    cash_required = cash_required.quantize(D(".01"), rounding=ROUND_CEILING)
    # Show an independently conclusive affordability failure even for indicative prices.
    if (account.daily_committed >= daily_cap or account.weekly_loss >= account.week_start_equity * limits.weekly
            or account.day_start_equity - account.equity >= daily_cap):
        return Decision(0, "SKIP — DAILY KILL SWITCH")
    if loss > budget or cash_required > min(account.buying_power, account.settled_cash):
        return Decision(0, "SKIP — POSITION TOO LARGE")
    if not account.integrity_ok or not fresh:
        return Decision(0, "DATA FAILURE — ACCOUNT OR QUOTE INTEGRITY")
    if increases_position or account.entries_today >= limits.entries or (v2 and account.v2_entries_today):
        return Decision(0, "SKIP — ENTRY LIMIT OR ADDING EXPOSURE")
    if (account.entries_today or not v2) and not account.second_strategy_approved:
        return Decision(0, "SKIP — SEPARATE STRATEGY APPROVAL REQUIRED")
    if spread and (account.mode != "margin" or not account.spread_approved):
        return Decision(0, "SKIP — SPREAD ACCOUNT APPROVAL REQUIRED")
    if not supported or liquidity < 1:
        return Decision(0, "SKIP — EVIDENCE OR LIQUIDITY INSUFFICIENT")
    count = min(int(budget // loss), int(min(account.buying_power, account.settled_cash) // cash_required), liquidity)
    return Decision(count, "ELIGIBLE — PAPER ONLY")
