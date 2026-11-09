"""Master v2 watchdog (a silent day must not hide a dead bot) and real-quote capture."""
import datetime as dt, json, os, tempfile, unittest
import pandas as pd
import yaml
from apex_master_bot import v2, v2_quotes as q
from apex_master_bot.calendar_et import BASE
from tests.test_v2 import DAY, scene

ROOT = os.path.dirname(BASE)


def jl(path):
    with open(path) as f:
        return json.load(f)


def at(h, m, day=DAY):
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=v2.NY)


# ---------------------------------------------------------------- fake option chain (SPY open 500, VIX 25 -> sigma about 7.875)
QUOTES_PUT = {494: (0.60, 0.62), 492: (0.18, 0.20), 496: (1.05, 1.07), 490: (0.05, 0.07)}
QUOTES_CALL = {500: (3.55, 3.60), 504: (1.60, 1.65)}


def frame(quotes, lo=480, hi=520):
    return pd.DataFrame([{"strike": float(k), "bid": quotes.get(k, (0.01, 0.03))[0], "ask": quotes.get(k, (0.01, 0.03))[1]} for k in range(lo, hi + 1)])


class FakeChain:
    def __init__(self, puts=None, calls=None, expiries=None, spot=500.0):
        self._p, self._c, self._e, self.spot = puts, calls, expiries, spot
    def expiries(self): return self._e or [DAY.isoformat()]
    def puts(self, e): return frame(QUOTES_PUT) if self._p is None else self._p
    def calls(self, e): return frame(QUOTES_CALL) if self._c is None else self._c
    def open_price(self, day): return self.spot


def signal_state(td):
    sent = []
    v2.run_check(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append)
    return sent


class Watchdog(unittest.TestCase):
    def test_missing_check_is_announced_and_run(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            res = v2.run_watchdog(DAY, scene(25, (0.05, 0.5, 0.5)), td, td, sent.append, now=at(9, 40))
            self.assertTrue(res["ran_today"])
            self.assertIn("WATCHDOG", sent[0]); self.assertIn("no v2 check was logged", sent[0])
            self.assertTrue(any("TRADE SIGNAL" in m for m in sent))               # and it ran the check itself
            self.assertTrue(any("LATE" in m for m in sent))
            self.assertEqual(jl(os.path.join(td, "v2", f"{DAY}.json"))["decision"], "TRADE")

    def test_silent_when_check_exists_or_too_early(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent = []
            res = v2.run_watchdog(DAY, scene(25), td, td, sent.append, now=at(9, 40))
            self.assertEqual((sent, res["ran_today"]), ([], False))
        with tempfile.TemporaryDirectory() as td:
            sent = []
            res = v2.run_watchdog(DAY, scene(25), td, td, sent.append, now=at(8, 40))   # the early DST cron line
            self.assertEqual((sent, res["ran_today"]), ([], False))
            self.assertFalse(os.path.exists(os.path.join(td, "v2")))

    def test_closed_day_is_quiet(self):
        with tempfile.TemporaryDirectory() as td:
            sent = []
            sat = dt.date(2026, 3, 14)
            v2.run_watchdog(sat, scene(25), td, td, sent.append, now=at(9, 40, sat))
            self.assertEqual(sent, [])

    def test_missed_signal_day_is_backfilled_but_not_before_the_start(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "v2"))
            with open(os.path.join(td, "v2", "_start.json"), "w") as f:
                json.dump({"start": "2026-03-10"}, f)
            prov = scene(25, (0.05, 0.5, 0.5), extra={"SPY": {"2026-03-09": (100, 110, 90, 91)}})    # 03-09 closed near its low, VIX 20.0
            sent = []
            res = v2.run_watchdog(DAY, prov, td, td, sent.append, now=at(9, 40))
            days = [d for d, _ in res["backfilled"]]
            self.assertIn("2026-03-10", days); self.assertNotIn("2026-03-09", days)
            self.assertTrue(any("MISSED SIGNAL" in m and "2026-03-10" in m for m in sent))
            st = jl(os.path.join(td, "v2", "2026-03-10.json"))
            self.assertTrue(st["backfilled"] and st["late"] and st["decision"] == "TRADE")
            # a second run does not repeat any of it
            sent.clear()
            v2.run_watchdog(DAY, prov, td, td, sent.append, now=at(9, 45))
            self.assertEqual(len(sent), 1)
            self.assertIn("ETF benchmark", sent[0])
            sent.clear()
            v2.run_watchdog(DAY, prov, td, td, sent.append, now=at(9, 50))
            self.assertEqual(sent, [])

    def test_backfilled_signal_is_scored_next_morning(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "v2"))
            with open(os.path.join(td, "v2", "_start.json"), "w") as f:
                json.dump({"start": "2026-03-10"}, f)
            prov = scene(25, (0.05, 0.5, 0.5), extra={"SPY": {"2026-03-09": (100, 110, 90, 91), "2026-03-10": (100, 104, 99, 103)}})
            v2.run_watchdog(DAY, prov, td, td, lambda m: None, now=at(9, 40))
            sent = []
            v2.settle(DAY, prov, td, td, sent.append)
            tr = pd.read_csv(os.path.join(td, "v2_trades.csv"))
            self.assertEqual(list(tr.day), ["2026-03-10"])
            self.assertAlmostEqual(float(tr.net_bp[0]), (103 / 100 - 1) * 1e4 - 2, places=1)

    def test_start_marker_written_once(self):
        with tempfile.TemporaryDirectory() as td:
            v2.run_check(DAY, scene(16.6), td, td, lambda m: None)
            v2.run_check(DAY + dt.timedelta(days=1), scene(16.6, prior="2026-03-11"), td, td, lambda m: None)
            self.assertEqual(jl(os.path.join(td, "v2", "_start.json"))["start"], DAY.isoformat())


class Structures(unittest.TestCase):
    def test_four_structures_and_gate(self):
        rows = {s["structure"]: s for s in q.build_structures(FakeChain(), DAY.isoformat(), 500.0, 7.875)}
        p75 = rows["put_0.75"]
        self.assertEqual((p75["short_k"], p75["long_k"], p75["width"]), (494.0, 492.0, 2.0))
        self.assertAlmostEqual(p75["nat"], 0.40); self.assertAlmostEqual(p75["nat_pct"], 0.20)
        self.assertEqual(p75["gate"], "PASS")                                         # 20.0% >= fair 13.7%
        self.assertEqual(rows["put_0.50"]["gate"], "PASS")                            # 21.5% >= 20.3%
        self.assertEqual(rows["put_1.00"]["gate"], "FAIL")                            # 5.5% < 9.3%
        c = rows["call_debit"]
        self.assertEqual((c["long_k"], c["short_k"]), (500.0, 504.0))
        self.assertAlmostEqual(c["nat"], 2.00); self.assertEqual(c["gate"], "FAIL")   # 50% > fair 45.2%

    def test_coarse_strikes_do_not_produce_a_misleading_gate(self):
        coarse = frame({}, lo=480, hi=520).iloc[::5].reset_index(drop=True)             # $5 strikes: width 5 = 0.63 sigma
        rows = {s["structure"]: s for s in q.build_structures(FakeChain(puts=coarse, calls=coarse), DAY.isoformat(), 500.0, 7.875)}
        self.assertEqual(rows["put_0.75"]["gate"], "WIDTH_OFF")

    def test_fair_value_interpolates_with_width(self):
        self.assertAlmostEqual(q.fair_put(0.75, 0.25), 0.137); self.assertAlmostEqual(q.fair_put(0.75, 0.50), 0.115)
        self.assertAlmostEqual(q.fair_put(0.75, 0.375), (0.137 + 0.115) / 2)
        self.assertAlmostEqual(q.fair_call(0.5), 0.452); self.assertAlmostEqual(q.fair_call(1.0), 0.337)

    def test_dead_quotes_are_flagged_not_priced(self):
        dead = pd.DataFrame([{"strike": float(k), "bid": 0.0, "ask": 0.0} for k in range(480, 521)])
        rows = q.build_structures(FakeChain(puts=dead, calls=dead), DAY.isoformat(), 500.0, 7.875)
        self.assertTrue(all(r.get("dead") for r in rows))

    def test_intrinsic_pnl_at_close(self):
        s = {"structure": "put_0.75", "short_k": 494.0, "long_k": 492.0, "width": 2.0, "mid": 0.41, "nat": 0.40}
        self.assertAlmostEqual(q.pnl_at_close(s, 497, "nat"), 0.20)
        self.assertAlmostEqual(q.pnl_at_close(s, 493, "nat"), (0.40 - 1.0) / 2)
        self.assertAlmostEqual(q.pnl_at_close(s, 480, "nat"), (0.40 - 2.0) / 2)       # capped at full width
        c = {"structure": "call_debit", "short_k": 504.0, "long_k": 500.0, "width": 4.0, "mid": 1.97, "nat": 2.0}
        self.assertAlmostEqual(q.pnl_at_close(c, 502, "nat"), (2.0 - 2.0) / 4)
        self.assertAlmostEqual(q.pnl_at_close(c, 510, "nat"), (4.0 - 2.0) / 4)


class RunQuotes(unittest.TestCase):
    def test_no_signal_no_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(q.run_quotes(DAY, FakeChain(), td, td, lambda m: None), "no-trade")
            v2.run_check(DAY, scene(16.6), td, td, lambda m: None)
            self.assertEqual(q.run_quotes(DAY, FakeChain(), td, td, lambda m: None), "no-trade")

    def test_waits_for_0931_logs_once_and_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent, slept = [], []
            r = q.run_quotes(DAY, FakeChain(), td, td, sent.append, now=at(9, 21), sleeper=slept.append)
            self.assertEqual(r, "done"); self.assertAlmostEqual(slept[0], 600)
            df = pd.read_csv(os.path.join(td, "v2_quotes.csv"))
            self.assertEqual(len(df), 4); self.assertTrue((df.is_0dte == 1).all())
            self.assertIn("QUOTE CHECK", sent[0]); self.assertIn("PASS", sent[0]); self.assertIn("FAIL", sent[0])
            self.assertEqual(q.run_quotes(DAY, FakeChain(), td, td, sent.append, now=at(9, 40), sleeper=slept.append), "already")
            self.assertEqual(len(pd.read_csv(os.path.join(td, "v2_quotes.csv"))), 4)

    def test_dead_chain_retries_then_says_so(self):
        dead = pd.DataFrame([{"strike": float(k), "bid": 0.0, "ask": 0.0} for k in range(480, 521)])
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            sent, slept = [], []
            r = q.run_quotes(DAY, FakeChain(puts=dead, calls=dead), td, td, sent.append, now=at(9, 40), sleeper=slept.append)
            self.assertEqual(r, "no-quotes"); self.assertEqual(len(slept), 2)
            self.assertIn("no live option quotes", sent[0])
            self.assertFalse(os.path.exists(os.path.join(td, "v2_quotes.csv")))

    def test_non_0dte_expiry_is_logged_but_not_gated(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            q.run_quotes(DAY, FakeChain(expiries=["2026-03-13"]), td, td, lambda m: None, now=at(9, 40), sleeper=lambda s: None)
            df = pd.read_csv(os.path.join(td, "v2_quotes.csv"), keep_default_na=False)
            self.assertTrue((df.is_0dte == 0).all() and (df.gate == "N/A").all())
            self.assertEqual(q.settle_quotes(DAY.isoformat(), 497.0, td), 0)               # never scored

    def test_scored_at_the_close_when_the_trade_settles(self):
        with tempfile.TemporaryDirectory() as td:
            signal_state(td)
            q.run_quotes(DAY, FakeChain(), td, td, lambda m: None, now=at(9, 40), sleeper=lambda s: None)
            nxt = DAY + dt.timedelta(days=1)
            prov = scene(25, (0.5, 0.5, 0.5), prior="2026-03-11", extra={"SPY": {"2026-03-11": (498, 499, 495, 497)}})
            v2.run_check(nxt, prov, td, td, lambda m: None)
            res = pd.read_csv(os.path.join(td, "v2_quote_results.csv")).set_index("structure")
            self.assertAlmostEqual(res.loc["put_0.75", "pnl_nat_pct"], 0.20)
            self.assertAlmostEqual(res.loc["put_1.00", "pnl_nat_pct"], 0.055)
            self.assertAlmostEqual(res.loc["call_debit", "pnl_nat_pct"], -0.5)           # closed below the long strike
            v2.settle(dt.date(2026, 3, 13), prov, td, td, lambda m: None)
            self.assertEqual(len(pd.read_csv(os.path.join(td, "v2_quote_results.csv"))), 4)   # idempotent
            self.assertIn("Option paper results", v2.status(td))


class Wiring(unittest.TestCase):
    def test_workflows(self):
        with open(os.path.join(ROOT, ".github", "workflows", "v2-watchdog.yml")) as f:
            wd = yaml.safe_load(f)
        steps = wd["jobs"]["watchdog"]["steps"]
        self.assertTrue(any("v2-watchdog" in s.get("run", "") for s in steps))
        crons = [c["cron"] for c in wd[True]["schedule"]] if True in wd else [c["cron"] for c in wd["on"]["schedule"]]
        self.assertEqual(crons, ["40 13,14 * * 1-5", "25 20,21 * * 1-5"])
        with open(os.path.join(ROOT, ".github", "workflows", "master-session.yml")) as f:
            ms = yaml.safe_load(f)
        names = [s.get("name", "") for s in ms["jobs"]["v2"]["steps"]]
        i_check = next(i for i, n in enumerate(names) if "v2 pre-open" in n)
        i_save = next(i for i, n in enumerate(names) if "Save v2 check state" in n)
        i_q = next(i for i, n in enumerate(names) if "Dispatch v2 option quote snapshot" in n)
        self.assertTrue(i_check < i_save < i_q)
        self.assertEqual(ms["jobs"]["session"]["needs"], "v2")
        self.assertEqual(ms["jobs"]["v2"]["concurrency"]["group"], wd["concurrency"]["group"])
        self.assertLessEqual(ms["jobs"]["session"]["timeout-minutes"], 360)             # GitHub's hosted-runner limit
        self.assertEqual(ms["permissions"]["actions"], "write")
        with open(os.path.join(ROOT, ".github", "workflows", "v2-quotes.yml")) as f:
            vq = yaml.safe_load(f)
        self.assertTrue(any("v2-quotes" in st.get("run", "") for st in vq["jobs"]["quotes"]["steps"]))
        self.assertEqual(vq["concurrency"]["group"], wd["concurrency"]["group"])


if __name__ == "__main__":
    unittest.main()
