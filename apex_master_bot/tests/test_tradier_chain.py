"""Tradier-first option chain for the v2 quote check, with Yahoo as the fallback. Fully offline."""
import datetime as dt, os, tempfile, unittest
from unittest import mock
import pandas as pd
from apex_master_bot import tradier, v2, v2_quotes as q
from tests.test_v2_ops import DAY, FakeChain, signal_state, at

PROD = {"TRADIER_API_KEY": "SECRET-ABC"}
SANDBOX = dict(PROD, TRADIER_BASE_URL="https://sandbox.tradier.com/v1")


def opt(k, kind, bid=1.0, ask=1.1):
    return {"symbol": f"SPY{kind}{k}", "strike": float(k), "option_type": kind, "bid": bid, "ask": ask}


CHAIN = [opt(494, "put", 0.60, 0.62), opt(496, "put", 1.05, 1.07), opt(500, "call", 3.55, 3.60), opt(504, "call", 1.60, 1.65)]


class Labeled(FakeChain):
    label = "Yahoo (may be delayed)"


class TradierChainShape(unittest.TestCase):
    def test_puts_and_calls_split_by_type_with_the_columns_the_builder_reads(self):
        with mock.patch.dict(os.environ, PROD, clear=True), mock.patch.object(tradier, "chain", return_value=CHAIN):
            c = q.TradierChain("spy")
            puts, calls = c.puts("2026-11-05"), c.calls("2026-11-05")
        self.assertEqual(list(puts.columns), ["strike", "bid", "ask"])
        self.assertEqual(sorted(puts.strike), [494.0, 496.0])
        self.assertEqual(sorted(calls.strike), [500.0, 504.0])
        # the existing structure builder accepts it unchanged
        self.assertIsNotNone(q.put_spread(puts, 500.0, 7.875, 0.5))

    def test_open_price_is_the_0930_bar(self):
        bars = [{"time": "2026-11-05T09:30:00", "open": 500.25}, {"time": "2026-11-05T09:31:00", "open": 500.9}]
        with mock.patch.dict(os.environ, PROD, clear=True), mock.patch.object(tradier, "timesales", return_value=bars):
            self.assertEqual(q.TradierChain("SPY").open_price(dt.date(2026, 11, 5)), 500.25)
        with mock.patch.dict(os.environ, PROD, clear=True), mock.patch.object(tradier, "timesales", return_value=[]):
            self.assertIsNone(q.TradierChain("SPY").open_price(dt.date(2026, 11, 5)))

    def test_label_says_real_time_for_production_and_delayed_for_sandbox(self):
        with mock.patch.dict(os.environ, PROD, clear=True):
            self.assertIn("real time", q.TradierChain("SPY").label)
        with mock.patch.dict(os.environ, SANDBOX, clear=True):
            self.assertIn("15 min delayed", q.TradierChain("SPY").label)


class Fallback(unittest.TestCase):
    def test_tradier_failure_falls_back_to_yahoo_and_the_label_says_so(self):
        logs = []
        prim = mock.Mock(label="Tradier production (real time)")
        prim.puts.side_effect = tradier.TradierError("HTTP 401")
        prim.expiries.return_value = ["2026-11-05"]
        yahoo = Labeled()
        fc = q.FallbackChain(prim, lambda: yahoo, log=logs.append)
        self.assertEqual(fc.expiries(), ["2026-11-05"])
        self.assertFalse(fc.used_backup)
        self.assertEqual(len(fc.puts("2026-11-05")), 41)          # answered by the Yahoo fake
        self.assertTrue(fc.used_backup)
        self.assertIn("fell back to Yahoo", fc.label)
        self.assertTrue(any("HTTP 401" in l for l in logs))

    def test_empty_answers_also_fall_back(self):
        prim = mock.Mock(label="T")
        prim.puts.return_value = pd.DataFrame(columns=["strike", "bid", "ask"])
        fc = q.FallbackChain(prim, lambda: Labeled(), log=lambda m: None)
        self.assertFalse(fc.puts("x").empty)
        self.assertTrue(fc.used_backup)

    def test_yahoo_is_never_built_when_tradier_answers(self):
        prim = mock.Mock(label="T")
        prim.expiries.return_value = ["2026-11-05"]
        built = []
        fc = q.FallbackChain(prim, lambda: built.append(1))
        fc.expiries()
        self.assertEqual(built, [])

    def test_make_chain_picks_by_whether_a_key_is_configured(self):
        class Y:
            label = "Yahoo (may be delayed)"
            def __init__(self, t): self.t = t
        with mock.patch.object(q, "YahooChain", Y):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIsInstance(q.make_chain("SPY"), Y)
            with mock.patch.dict(os.environ, {"TRADIER_API_KEY": "  "}, clear=True):
                self.assertIsInstance(q.make_chain("SPY"), Y)
            with mock.patch.dict(os.environ, PROD, clear=True):
                self.assertIsInstance(q.make_chain("SPY"), q.FallbackChain)


class AlertNamesTheSource(unittest.TestCase):
    def test_quote_check_message_states_the_data_source(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent = []
            ch = Labeled()
            ch.label = "Tradier production (real time)"
            self.assertEqual(q.run_quotes(DAY, ch, td, td, sent.append, now=at(9, 40), sleeper=lambda s: None), "done")
            self.assertIn("Data: Tradier production (real time).", sent[0])

    def test_a_chain_without_a_label_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent = []
            self.assertEqual(q.run_quotes(DAY, FakeChain(), td, td, sent.append, now=at(9, 40), sleeper=lambda s: None), "done")
            self.assertNotIn("Data:", sent[0])


if __name__ == "__main__":
    unittest.main()
