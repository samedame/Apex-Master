"""Master v2 alert module: rule, data guards, settlement, forward-test rules, 30-year parity with the research."""
import datetime as dt, json, os, tempfile, unittest
import pandas as pd
from apex_master_bot import v2
from apex_master_bot.calendar_et import BASE

ROOT = os.path.dirname(BASE)
RES = os.path.join(ROOT, "research", "master_v2")
DAY = dt.date(2026, 3, 11)       # Wednesday; previous session Tuesday 2026-03-10


def bars(rows):
    """rows: {'YYYY-MM-DD': (open, high, low, close)}"""
    return pd.DataFrame(rows, index=["Open", "High", "Low", "Close"]).T.set_index(pd.to_datetime(list(rows))).astype(float)


class Fake:
    def __init__(self, daily, vix, fred=None):
        self._d, self._v, self._f = daily, vix, fred
    def daily(self, t): return self._d[t]
    def vix(self): return self._v
    def fred_vix(self): return self._f


def jl(path):
    with open(path) as f:
        return json.load(f)


def series(d): return pd.Series(list(d.values()), index=pd.to_datetime(list(d)), dtype=float)


def scene(vix=25.0, ibs=(0.05, 0.5, 0.5), prior="2026-03-10", fred=None, extra=None):
    """Three ETFs whose prior-session IBS equals `ibs`; range 90..110, close = low + ibs*20."""
    daily = {}
    for t, v in zip(("SPY", "QQQ", "IWM"), ibs):
        rows = {"2026-03-09": (100, 110, 90, 100), prior: (100, 110, 90, 90 + 20 * v)}
        if extra:
            rows.update(extra.get(t, {}))
        daily[t] = bars(rows)
    vx = {"2026-03-09": 20.0, prior: vix}
    return Fake(daily, series(vx), None if fred is None else series({prior: fred}))


class Rule(unittest.TestCase):
    def test_gate_and_threshold_edges(self):
        self.assertFalse(v2.decide({"SPY": 0.01}, 19.99)["trade"])
        self.assertTrue(v2.decide({"SPY": 0.01}, 20.0)["trade"])
        self.assertFalse(v2.decide({"SPY": 0.10}, 30)["trade"])            # strictly below 0.10
        self.assertTrue(v2.decide({"SPY": 0.0999}, 30)["trade"])

    def test_no_upper_vix_cap(self):
        self.assertTrue(v2.decide({"SPY": 0.01}, 60)["trade"])

    def test_first_etf_in_order_wins_not_lowest_ibs(self):
        d = v2.decide({"SPY": 0.09, "QQQ": 0.01, "IWM": 0.0}, 25)
        self.assertEqual(d["ticker"], "SPY")
        self.assertEqual(v2.decide({"SPY": 0.5, "QQQ": 0.08, "IWM": 0.0}, 25)["ticker"], "QQQ")
        self.assertEqual(v2.decide({"SPY": None, "QQQ": 0.5, "IWM": 0.0}, 25)["ticker"], "IWM")

    def test_flat_bar_has_no_ibs(self):
        self.assertIsNone(v2.ibs_of(10, 10, 10))
        self.assertAlmostEqual(v2.ibs_of(110, 90, 94), 0.2)

    def test_thirty_year_parity_with_research(self):
        data = os.path.join(RES, "data")
        pub = os.path.join(RES, "results", "master_v2_trades.csv")
        if not (os.path.isdir(data) and os.path.exists(pub)):
            self.skipTest("research/master_v2 not present")
        t, p = v2.replay(data), pd.read_csv(pub)
        self.assertEqual(len(t), len(p))
        self.assertEqual(list(t.date), list(p.date.astype(str)))
        self.assertEqual(list(t.ticker), list(p.ticker))
        self.assertLess(float((t.net_bp.values - p.net_bp.values).__abs__().max()), 1e-6)


class Check(unittest.TestCase):
    def test_trade_signal(self):
        r = v2.check(DAY, scene(25, (0.05, 0.5, 0.5)))
        self.assertEqual((r["decision"], r["ticker"]), ("TRADE", "SPY"))
        self.assertAlmostEqual(r["sigma_pct"], 25 / 100 / 252 ** 0.5 * 100)
        txt = v2.trade_alert(r)
        self.assertIn("paper only", txt); self.assertIn("Buy SPY at the open", txt); self.assertIn("Bull put spread", txt)

    def test_calm_market_no_trade(self):
        r = v2.check(DAY, scene(16.6, (0.01, 0.01, 0.01)))
        self.assertEqual(r["decision"], "NO_TRADE")

    def test_stale_etf_bar_is_a_data_error_not_a_decision(self):
        with self.assertRaises(v2.DataError):
            v2.check(DAY, scene(25, (0.05, 0.5, 0.5), prior="2026-03-09"))

    def test_vix_sources_disagreeing_across_the_gate(self):
        with self.assertRaises(v2.DataError):
            v2.check(DAY, scene(20.2, (0.05, 0.5, 0.5), fred=19.4))
        r = v2.check(DAY, scene(24.0, (0.05, 0.5, 0.5), fred=24.3))           # same side, close: fine
        self.assertEqual(r["decision"], "TRADE"); self.assertIn("agree", r["vix_source"])

    def test_weekend_and_holiday_are_closed(self):
        self.assertEqual(v2.check(dt.date(2026, 3, 14), scene())["decision"], "CLOSED")
        self.assertEqual(v2.expected_prior_session(dt.date(2026, 3, 9)), dt.date(2026, 3, 6))   # Monday -> Friday

    def test_ledger_idempotent_and_late_flag(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            now = dt.datetime(2026, 3, 11, 9, 50, tzinfo=v2.NY)
            r1 = v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append, now=now)
            r2 = v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append, now=now)
            self.assertEqual(len(sent), 1)                                       # no second alert
            self.assertTrue(r1["late"]); self.assertEqual(r2["decision"], "TRADE")
            self.assertIn("LATE", sent[0])
            self.assertEqual(len(pd.read_csv(os.path.join(td, "v2_checks.csv"))), 1)

    def test_data_failure_alerts_and_logs(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            r = v2.run_check(DAY, scene(25, prior="2026-03-09"), td, td, sent.append)
            self.assertEqual(r["decision"], "NO_DECISION")
            self.assertTrue(sent and "NO DECISION" in sent[0])

    def test_no_trade_day_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            v2.run_check(DAY, scene(16.6), td, td, sent.append)
            self.assertEqual(sent, [])


class Settle(unittest.TestCase):
    def _trade_then_settle(self, td, day_bar, prefill=None):
        sent = []
        v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append)
        if prefill:
            pd.DataFrame(prefill).to_csv(os.path.join(td, "v2_trades.csv"), index=False)
        nxt = DAY + dt.timedelta(days=1)
        prov = scene(25, (0.5, 0.5, 0.5), prior="2026-03-11", extra={"SPY": {"2026-03-11": day_bar}})
        sent.clear()
        v2.run_check(nxt, prov, td, td, sent.append)
        return sent

    def test_settles_next_morning_net_of_cost(self):
        with tempfile.TemporaryDirectory() as td:
            sent = self._trade_then_settle(td, (100, 103, 99, 102))          # +200 bp gross
            tr = pd.read_csv(os.path.join(td, "v2_trades.csv"))
            self.assertEqual(len(tr), 1)
            self.assertAlmostEqual(float(tr.net_bp[0]), 198.0, places=1)
            self.assertIn("+198.0 bp net", sent[0])
            self.assertTrue(jl(os.path.join(td, "v2", "2026-03-11.json"))["settled"])
            # settling again does nothing
            v2.settle(dt.date(2026, 3, 13), scene(25), td, td, sent.append)
            self.assertEqual(len(pd.read_csv(os.path.join(td, "v2_trades.csv"))), 1)

    def test_pause_rule(self):
        with tempfile.TemporaryDirectory() as td:
            pre = {k: [v] for k, v in dict(day="2026-01-05", ticker="SPY", vix=25, ibs=0.01, open=100, close=90, gross_bp=-1000,
                                           net_bp=-1500.0, cum_net_bp=-1500.0, n=1).items()}
            sent = self._trade_then_settle(td, (100, 100, 97, 98), prefill=pre)      # -200 gross -> cum below -1600
            self.assertTrue(any("PAUSE AND REVIEW" in m for m in sent))

    def test_retire_rule_at_40_trades(self):
        with tempfile.TemporaryDirectory() as td:
            pre = [dict(day=f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}", ticker="SPY", vix=25, ibs=0.01, open=100, close=100, gross_bp=0,
                        net_bp=-1.0, cum_net_bp=-(i + 1.0), n=i + 1) for i in range(39)]
            sent = self._trade_then_settle(td, (100, 101, 99, 100.1), prefill={k: [r[k] for r in pre] for k in pre[0]})   # +10 gross, mean still < 0
            self.assertTrue(any("RETIRE" in m for m in sent))

    def test_unposted_bar_stays_pending(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append)
            v2.settle(DAY + dt.timedelta(days=1), scene(25), td, td, sent.append)      # no 03-11 bar in the provider
            self.assertFalse(os.path.exists(os.path.join(td, "v2_trades.csv")))
            self.assertFalse(jl(os.path.join(td, "v2", "2026-03-11.json")).get("settled"))


class Status(unittest.TestCase):
    def test_empty_and_filled(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIn("0 checks", v2.status(td)); self.assertIn("Quiet is normal", v2.status(td))
            sent = []
            v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append)
            self.assertIn("1 signals", v2.status(td))


class Wiring(unittest.TestCase):
    def test_session_workflow_runs_v2_before_v1_and_saves_its_files(self):
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "master-session.yml")) as f:
            wf = yaml.safe_load(f)
        steps = wf["jobs"]["session"]["steps"]
        names = [s.get("name", "") for s in steps]
        i2 = next(i for i, n in enumerate(names) if "v2" in n.lower() and "check" in n.lower())
        i1 = next(i for i, n in enumerate(names) if n.startswith("Run today's session"))
        self.assertLess(i2, i1)
        self.assertTrue(steps[i2].get("continue-on-error"))
        self.assertIn("v2-check", steps[i2]["run"])


if __name__ == "__main__":
    unittest.main()
