"""Causality, option economics, policy, and crash/concurrency regressions."""
import datetime as dt
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from apex_master_bot import v2, v2_quotes
from apex_master_bot.calendar_et import session_close
from apex_master_bot.market_regime import Event, Observation, assess_regime, event_calendar
from apex_master_bot.option_replay import replay_record
from apex_master_bot.options_execution import Quote, Reference, expiry_pnl, vertical
from apex_master_bot.risk import Account, D, assess
from tests.test_v2 import DAY, scene
from tests.test_v2_ops import FakeChain, at, signal_state


AS_OF = at(9, 32)
REF = Reference("SPY", D("500"), AS_OF, "fixture NBBO")


def leg(right, strike, bid, ask):
    return Quote("SPY", f"SPY{DAY:%y%m%d}{right}{strike * 1000:08}", DAY, right,
                 D(strike), D(bid), D(ask), AS_OF, "fixture NBBO", bid_size=4, ask_size=3)


class Options(unittest.TestCase):
    def test_four_payoffs_and_breakevens(self):
        low_c, high_c = leg("C", 499, "2.00", "2.05"), leg("C", 502, ".50", ".55")
        low_p, high_p = leg("P", 498, ".50", ".55"), leg("P", 501, "2.00", "2.05")
        cases = [
            (low_c, high_c, "bull_call_debit", "159.60", "140.40", "500.596"),
            (high_c, low_c, "bear_call_credit", "159.60", "140.40", "500.404"),
            (low_p, high_p, "bull_put_credit", "159.60", "140.40", "499.596"),
            (high_p, low_p, "bear_put_debit", "159.60", "140.40", "499.404"),
        ]
        for long, short, structure, loss, profit, breakeven in cases:
            with self.subTest(structure=structure):
                e = vertical(long, short, REF, AS_OF)
                self.assertEqual(e.structure, structure)
                self.assertEqual((e.max_loss, e.max_profit, e.breakeven, e.liquidity),
                                 (D(loss), D(profit), D(breakeven), 3))
                self.assertEqual(expiry_pnl(long, short, e, e.breakeven), 0)

    def test_quote_failures(self):
        long, short = leg("C", 499, "2", "2.05"), leg("C", 502, ".50", ".55")
        for bad in [
            replace(long, bid=D("NaN")), replace(long, bid=D("0")), replace(long, bid=D("3")),
            replace(long, ask=D("3")), replace(long, symbol="OTHER"), replace(long, multiplier=10),
            replace(long, observed=AS_OF - dt.timedelta(seconds=61)),
            replace(long, observed=AS_OF + dt.timedelta(seconds=1)),
            replace(long, observed=AS_OF - dt.timedelta(seconds=16)),
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                vertical(bad, short, REF, AS_OF)

    def test_jsonl_replay_with_timestamped_exit(self):
        def payload(stamp, long_bid, long_ask):
            long = replace(leg("C", 499, long_bid, long_ask), observed=stamp)
            short = replace(leg("C", 502, ".50", ".55"), observed=stamp)

            def serialize(q):
                return {**asdict(q), "expiry": q.expiry.isoformat(), "observed": q.observed.isoformat()}

            return {"as_of": stamp.isoformat(), "long": serialize(long), "short": serialize(short),
                    "underlying": {"symbol": "SPY", "price": 500,
                                   "source": "fixture", "observed": stamp.isoformat()}}

        record = {"entry": payload(AS_OF, "2", "2.05"), "exit": payload(at(15, 59), "2.50", "2.55"),
                  "terminal_scenarios": [498, 503]}
        out = replay_record(record)
        self.assertEqual(out["quote_side_pnl"], D("35.40"))
        self.assertEqual(out["risk"]["count"], 0)
        self.assertIn("simplified expiry intrinsic", out["expiry_scenario"]["label"])
        del record["exit"]
        self.assertIsNone(replay_record(record)["quote_side_pnl"])
        record["entry"] = payload(at(9, 29), "2", "2.05")
        with self.assertRaisesRegex(ValueError, "outside regular"):
            replay_record(record)


class Risk(unittest.TestCase):
    def test_floor_permissions_and_kill_switch(self):
        approved = Account(mode="margin", spread_approved=True, integrity_ok=True)
        cases = [
            (approved, "250", "250", 4, 0, "POSITION TOO LARGE"),
            (approved, "7.501", "8", 4, 1, "ELIGIBLE"),
            (approved, "7.50", "8", 4, 2, "ELIGIBLE"),
            (replace(approved, settled_cash=D("8")), "7", "8", 4, 1, "ELIGIBLE"),
            (replace(approved, weekly_loss=D("75")), "7", "8", 4, 0, "KILL SWITCH"),
            (replace(approved, daily_committed=D("30")), "7", "8", 4, 0, "KILL SWITCH"),
            (replace(approved, correlated_open=D("25")), "7", "8", 4, 0, "POSITION TOO LARGE"),
            (replace(approved, v2_entries_today=1, entries_today=1), "7", "8", 4, 0, "ENTRY LIMIT"),
            (replace(approved, mode="cash"), "7", "8", 4, 0, "APPROVAL"),
            (replace(approved, integrity_ok=False), "7", "8", 4, 0, "DATA FAILURE"),
        ]
        for account, loss, cash, liquidity, count, reason in cases:
            with self.subTest(reason=reason):
                out = assess(account, D(loss), D(cash), liquidity, supported=True, fresh=True)
                self.assertEqual(out.count, count)
                self.assertIn(reason, out.reason)

    def test_second_strategy_needs_independent_approval(self):
        account = Account(mode="margin", spread_approved=True, integrity_ok=True,
                          entries_today=1, v2_entries_today=1, daily_committed=D("15"))
        self.assertEqual(assess(account, D("10"), D("10"), 1, v2=False, supported=True, fresh=True).count, 0)
        account = replace(account, second_strategy_approved=True)
        self.assertEqual(assess(account, D("10"), D("10"), 1, v2=False, supported=True, fresh=True).count, 1)
        self.assertEqual(assess(account, D("10"), D("10"), 1, v2=False, supported=True, fresh=True,
                                increases_position=True).count, 0)


class PointInTime(unittest.TestCase):
    def test_future_features_and_calendar_announcements_are_hidden(self):
        future = AS_OF + dt.timedelta(minutes=1)
        old = AS_OF - dt.timedelta(days=5)
        view = assess_regime([Observation("vix", 25, future, "fixture"),
                              Observation("SPY_trend20", 1, old, "fixture")], as_of=AS_OF)
        self.assertEqual(view["observations"], {})
        self.assertIsNone(view["bullish_probability"])
        events = [Event("CPI", future, old, "fixture", published_at=future, surprise=1.0),
                  Event("FOMC", future, future, "fixture")]
        rows = event_calendar(events, as_of=AS_OF, until=future)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "CPI")
        self.assertIsNone(rows[0]["surprise"])
        released = event_calendar(events, as_of=future, since=AS_OF, until=future)
        self.assertEqual(next(row for row in released if row["name"] == "CPI")["surprise"], 1.0)

    def test_calendar_and_dst(self):
        self.assertFalse(v2.is_session_day(dt.date(2027, 6, 18)))
        self.assertTrue(v2.is_session_day(dt.date(2027, 11, 26)))
        self.assertEqual(session_close(dt.date(2027, 11, 26)), dt.time(13))
        self.assertEqual(v2.expected_prior_session(dt.date(2027, 11, 29)), dt.date(2027, 11, 26))
        self.assertNotEqual(at(9, 30, dt.date(2026, 3, 6)).utcoffset(), AS_OF.utcoffset())

    def test_close_vix_disagreement_and_bad_bar_fail_closed(self):
        with self.assertRaisesRegex(v2.DataError, "disagree"):
            v2.check(DAY, scene(20.1, fred=19.9))
        self.assertIsNone(v2.ibs_of(105, 100, 99))
        self.assertIsNone(v2.ibs_of(float("inf"), 100, 102))


class Operations(unittest.TestCase):
    def test_open_boundary_and_parallel_checks(self):
        with tempfile.TemporaryDirectory() as td, ThreadPoolExecutor(max_workers=4) as pool:
            sent = []
            provider = scene(25, (0.05, 0.5, 0.5))
            rows = list(pool.map(lambda _: v2.run_check(DAY, provider, td, td, sent.append, now=at(9, 30)),
                                 range(8)))
            self.assertTrue(all(r["late"] for r in rows))
            self.assertEqual(len(sent), 1)
            self.assertIn("benchmark only", sent[0])
            self.assertEqual(len(pd.read_csv(Path(td) / "v2_checks.csv")), 1)

    def test_quotes_restart_after_batch_failure(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent = []
            with patch.object(v2_quotes, "append_unique", side_effect=OSError("simulated write failure")):
                with self.assertRaises(OSError):
                    v2_quotes.run_quotes(DAY, FakeChain(), td, td, sent.append, now=AS_OF)
            self.assertEqual(sent, [])
            self.assertEqual(v2_quotes.run_quotes(DAY, None, td, td, sent.append, now=at(16, 30)), "done")
            self.assertEqual(len(sent), 1)
            self.assertIn("zero contracts", sent[0])
            self.assertEqual(len(pd.read_csv(Path(td) / "v2_quotes.csv")), 4)
            state = json.loads((Path(td) / "v2" / f"{DAY}.json").read_text())
            self.assertIsNone(state["quote_snapshot"]["rows"][0]["long_leg"]["quote_at"])

    def test_outside_session_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            for now in (at(9, 29), at(16, 1), at(9, 32, DAY + dt.timedelta(days=1))):
                self.assertEqual(v2_quotes.run_quotes(DAY, None, td, td, self.fail, now=now, wait=False),
                                 "outside-session")
