"""Prospective selection and real-time-only capture with deterministic provider fixtures."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from apex_master_bot import shadow, v2
from tests.test_v2 import DAY, scene
from tests.test_v2_ops import at


class Chain:
    source = "indicative test chain"

    def __init__(self, ticker, day=DAY, strikes=(500, 501, 502)):
        self.ticker = ticker
        self.day = day
        self.strikes = strikes

    def expiries(self):
        return [str(self.day)]

    def open_price(self, day):
        return 500.25

    def tables(self, expiry):
        rows = []
        for strike in self.strikes:
            bid = {500: 1.00, 501: .45, 502: .2}[strike]
            rows.append({"strike": strike, "bid": bid, "ask": bid + .02,
                         "contractSymbol": f"{self.ticker}{self.day:%y%m%d}C{strike * 1000:08}",
                         "contractSize": "REGULAR", "lastTradeDate": at(9, 30, self.day)})
        return pd.DataFrame(), pd.DataFrame(rows)


class Shadow(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state = str(self.root / "state")
        self.ledger = str(self.root / "ledger")
        self.prov = scene(25, (.05, .02, .04), extra={
            "SPY": {str(DAY): (100, 104, 99, 101)},
            "QQQ": {str(DAY): (100, 104, 99, 102)},
        })

    def baseline(self, hour=9, minute=20, day=DAY, provider=None):
        return v2.run_check(day, provider or self.prov, self.state, self.ledger, lambda _: None,
                            now=at(hour, minute, day))

    def step(self, phase, hour, minute, chain=Chain, day=DAY, session=None):
        return shadow.run(phase, self.state, self.ledger, chain, self.prov,
                          clock=lambda: at(hour, minute, day), session=session)

    def record(self, day=DAY):
        return json.loads((Path(self.ledger) / "shadow" / f"{day}.json").read_text())

    def test_prospective_pair_and_same_contract_exit(self):
        self.assertEqual(self.baseline()["ticker"], "SPY")
        baseline_state = Path(self.state) / "v2" / f"{DAY}.json"
        original = baseline_state.read_bytes()
        self.step("select", 9, 22)
        record = self.record()
        self.assertEqual((record["baseline"], record["qqq_first"]), ("SPY", "QQQ"))
        self.assertEqual(record["recorded_at"], at(9, 22).isoformat())
        self.assertEqual(self.step("entry", 9, 32), "entry")
        # Add a different strike universe. Existing symbols remain pinned.
        self.assertEqual(self.step("exit", 15, 50, lambda t: Chain(t, strikes=(500, 501))), "exit")
        self.assertEqual(self.step("entry", 9, 33, lambda _: self.fail("duplicate fetch")), "entry")
        record = self.record()
        for marks in record["options"].values():
            entry, exit = marks["entry"], marks["exit"]
            self.assertEqual(entry["reason"], "UNAFFORDABLE")
            self.assertEqual(entry["captured_at"], at(9, 32).isoformat())
            self.assertEqual(exit["captured_at"], at(15, 50).isoformat())
            self.assertEqual(exit["status"], "INDICATIVE_MARK")
            self.assertEqual(entry["legs"]["long"]["symbol"], exit["legs"]["long"]["symbol"])
            self.assertEqual(entry["legs"]["short"]["symbol"], exit["legs"]["short"]["symbol"])
            self.assertIsNone(entry["legs"]["long"]["quote_observed_at"])
            self.assertIsNotNone(entry["legs"]["long"]["last_trade_at"])
            self.assertEqual(entry["contracts_authorized"], 0)
        self.step("auto", 16, 25)
        self.assertAlmostEqual(self.record()["etf_benchmark"]["qqq_first_minus_baseline_bp"], 100)
        self.assertEqual(baseline_state.read_bytes(), original)

    def test_missed_open_does_not_reconstruct_selection(self):
        self.baseline(9, 35)
        self.step("auto", 9, 40, lambda _: self.fail("late signal cannot fetch"))
        self.assertEqual(self.record()["reason"], "MISSED_PREOPEN_SELECTION")

    def test_missing_and_unaffordable_candidates_are_preserved(self):
        self.baseline()
        self.step("select", 9, 22)
        self.step("entry", 9, 35, lambda t: Chain(t, day=DAY + dt.timedelta(days=2)))
        self.step("exit", 15, 50, lambda _: self.fail("no pinned contracts"))
        for marks in self.record()["options"].values():
            self.assertEqual(marks["entry"]["reason"], "NO_0DTE_LISTING")
            self.assertEqual(marks["exit"]["reason"], "NO_PINNED_ENTRY_CONTRACTS")

    def test_missing_exit_symbol_does_not_substitute(self):
        self.baseline()
        self.step("select", 9, 22)
        self.step("entry", 9, 35)
        self.step("exit", 15, 50, lambda t: Chain(t, strikes=(500, 502)))
        self.assertTrue(all(m["exit"]["reason"] == "PINNED_CONTRACT_MISSING"
                            for m in self.record()["options"].values()))

    def test_missed_windows_and_wrong_session(self):
        self.baseline()
        self.step("select", 9, 22)
        self.assertEqual(self.step("entry", 9, 32, session="2026-03-10"), "wrong-session")
        self.assertEqual(self.step("exit", 15, 42), "too-early")
        self.step("auto", 16, 25, lambda _: self.fail("after-hours fetch"))
        for marks in self.record()["options"].values():
            self.assertEqual([marks[p]["reason"] for p in ("entry", "exit")], ["MISSED_WINDOW"] * 2)

    def test_no_signal_is_logged(self):
        self.baseline(provider=scene(16.6))
        self.step("select", 9, 22)
        self.assertEqual(self.record()["reason"], "NO_SIGNAL")
        self.assertEqual(self.record()["options"], {})

    def test_half_day_uses_early_close(self):
        day = dt.date(2026, 11, 27)
        self.baseline(day=day, provider=scene(25, (.05, .02, .04), prior="2026-11-25"))
        self.step("select", 9, 22, day=day)
        self.step("entry", 9, 35, lambda t: Chain(t, day), day=day)
        self.assertEqual(self.step("auto", 12, 50, lambda t: Chain(t, day), day=day), "exit")
        self.assertEqual(self.record(day)["options"]["QQQ"]["exit"]["captured_at"], at(12, 50, day).isoformat())

    def test_same_ticker_fetches_once_and_scores_zero_delta(self):
        self.baseline(provider=scene(25, (.05, .5, .5)))
        self.step("select", 9, 22)
        calls = []

        def chain(ticker):
            calls.append(ticker)
            return Chain(ticker)

        self.step("entry", 9, 32, chain)
        self.step("auto", 16, 25)
        self.assertEqual(calls, ["SPY"])
        self.assertEqual(self.record()["etf_benchmark"]["qqq_first_minus_baseline_bp"], 0)

    def test_fetch_that_crosses_entry_cutoff_cannot_mark(self):
        self.baseline()
        self.step("select", 9, 22)
        stamps = iter((at(9, 44), at(9, 44), at(9, 45), at(9, 45)))
        shadow.run("entry", self.state, self.ledger, Chain, clock=lambda: next(stamps))
        self.assertTrue(all(mark["entry"]["reason"] == "MISSED_WINDOW"
                            for mark in self.record()["options"].values()))
