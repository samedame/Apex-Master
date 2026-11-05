"""Scoreboard, watchdog and scheduler tests. Run: python3 -m unittest discover -s tests -v"""
import datetime as dt, json, os, shutil, sys, tempfile, types, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from apex_master_bot import ensure, scoreboard, watchdog
from apex_master_bot.calendar_et import NY, is_trading_day
from apex_master_bot.config import Config, config_hash
import dataclasses

DATA = os.path.join(ROOT, "..", "data")


def at(h, m, day="2026-11-04"):
    y, mo, d = map(int, day.split("-"))
    return dt.datetime(y, mo, d, h, m, tzinfo=NY)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.state, self.ledger = os.path.join(self.d, "state"), os.path.join(self.d, "ledger")
        os.makedirs(self.state); os.makedirs(self.ledger)
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)
    def wj(self, name, obj, where=None):
        with open(os.path.join(where or self.state, name), "w") as f:
            json.dump(obj, f)


def ledger_df(R, cfgs, start="2026-11-05", step=2):
    dates = pd.date_range(start, periods=len(R), freq=f"{step}D")
    return pd.DataFrame(dict(date=dates, R=R, cfg=cfgs))


class Scoreboard(Tmp):
    def test_no_data(self):
        r = scoreboard.evaluate(scoreboard.load_trades(os.path.join(self.ledger, "trades.csv")), self.state)
        self.assertEqual(r["verdict"], "NO DATA")

    def test_pass_only_when_both_100_trades_and_182_days(self):
        R = [1.05, 1.05, -1.15] * 34                                  # 102 trades, 66.7% wins, PF ~1.8
        t = ledger_df(R, ["a"] * len(R), step=2)                       # spans 202 days
        r = scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])
        self.assertEqual(r["verdict"], "PASS", scoreboard.render(r))
        t2 = ledger_df(R, ["a"] * len(R), step=1)                      # 102 trades but only 101 days
        r2 = scoreboard.evaluate(t2, self.state, today=t2.date.iloc[-1])
        self.assertEqual(r2["verdict"], "IN PROGRESS")
        self.assertFalse(r2["progress"]["decision_ready"])

    def test_fail_at_decision_point(self):
        R = [1.05, -1.15, -1.15, 1.05, -1.15] * 20 + [0.1, 0.1]       # ~40% wins, negative mean -> kill criteria also hit
        t = ledger_df(R, ["a"] * len(R), step=2)
        r = scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])
        self.assertEqual(r["verdict"], "KILLED")

    def test_kill_on_profit_factor_after_50(self):
        R = [1.05, -1.15] * 25                                         # 50 trades, PF 0.91 -> mean -0.05: not killed
        t = ledger_df(R, ["a"] * 50)
        self.assertNotEqual(scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])["verdict"], "KILLED")
        R = [0.5, -1.15] * 25                                          # PF 0.43
        t = ledger_df(R, ["a"] * 50)
        self.assertEqual(scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])["verdict"], "KILLED")
        t = ledger_df(R[:40], ["a"] * 40)                              # under 50 trades: kill tests do not run
        self.assertNotEqual(scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])["verdict"], "KILLED")

    def test_config_change_restarts_count(self):
        t = ledger_df([1.0] * 60 + [1.0] * 10, ["old"] * 60 + ["new"] * 10)
        r = scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])
        self.assertEqual((r["metrics"]["n"], r["ignored_trades"], r["cohort_cfg"]), (10, 60, "new"))

    def test_real_cost_kill_switches_on_when_logged(self):
        t = ledger_df([1.0, -1.0] * 5, ["a"] * 10)
        t["real_cost_R"] = 0.6
        r = scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])
        self.assertTrue(any(k["hit"] is True and "cost" in k["name"] for k in r["kill_checks"]))

    def test_gate_share_kill(self):
        for i in range(25):
            self.wj(f"2026-12-{i + 1:02d}.json", dict(done=True, stand_down="VIX prior close 27 >= 25" if i < 12 else ""))
        t = ledger_df([1.0, -0.5] * 5, ["a"] * 10)
        r = scoreboard.evaluate(t, self.state, today=t.date.iloc[-1])
        self.assertEqual(r["verdict"], "KILLED")

    def test_metrics_drawdown_and_streak(self):
        m = scoreboard.metrics([1, 1, -1, -1, -1, 1, -1], boot=200)
        self.assertEqual((m["max_dd"], m["max_losses"]), (-3.0, 3))

    def test_config_hash_ignores_sizing_but_not_rules(self):
        c = Config()
        self.assertEqual(config_hash(c), config_hash(dataclasses.replace(c, risk_pct=0.1)))
        self.assertNotEqual(config_hash(c), config_hash(dataclasses.replace(c, target_R=2.5)))
        self.assertNotEqual(config_hash(c), config_hash(dataclasses.replace(c, vix_prior_cap=30.0)))


class Watchdog(Tmp):
    def hb(self, now, age_s=30, bar_age_min=6, **kw):
        h = dict(ts=(now - dt.timedelta(seconds=age_s)).isoformat(), day=now.date().isoformat(), phase="scanning",
                 errors_in_row=0, error=None, last_bar=(now - dt.timedelta(minutes=bar_age_min)).isoformat())
        h.update(kw)
        self.wj("heartbeat.json", h)

    def keys(self, now):
        return [f[0] for f in watchdog.check(now, self.state, self.ledger)]

    def test_quiet_when_healthy(self):
        now = at(11, 0); self.hb(now)
        self.assertEqual(self.keys(now), [])

    def test_not_running(self):
        self.assertEqual(self.keys(at(10, 0)), ["not-running"])
        self.assertEqual(self.keys(at(9, 30)), [])                      # inside the grace period

    def test_stalled_and_feed_stale_and_errors(self):
        now = at(11, 0)
        self.hb(now, age_s=600); self.assertEqual(self.keys(now), ["stalled"])
        self.hb(now, bar_age_min=30); self.assertEqual(self.keys(now), ["feed-stale"])
        self.hb(now, errors_in_row=4, error="data: boom"); self.assertEqual(self.keys(now), ["errors"])

    def test_old_day_heartbeat_counts_as_not_running(self):
        now = at(11, 0); self.hb(at(11, 0, "2026-11-03"))
        self.assertEqual(self.keys(now), ["not-running"])

    def test_non_trading_days_are_silent(self):
        self.assertEqual(self.keys(at(11, 0, "2026-11-07")), [])        # Saturday
        self.assertEqual(self.keys(at(11, 0, "2026-11-26")), [])        # Thanksgiving, listed in market_holidays.txt
        self.assertEqual(self.keys(at(11, 0, "2026-11-27")), [])        # half-day, bot stands down
        self.assertTrue(is_trading_day(dt.date(2026, 11, 4)))

    def test_finished_day_is_silent_during_session(self):
        now = at(12, 0); self.wj("2026-11-04.json", dict(done=True, outcome="stood_down", stand_down="x"))
        self.assertEqual(self.keys(now), [])

    def test_end_of_day_summary_and_open_trade(self):
        now = at(16, 10)
        self.wj("2026-11-04.json", dict(done=True, outcome="traded", trade=dict(ticker="IWM", module="P1C")))
        self.assertEqual(self.keys(now), ["open-trade"])                # trade in state, nothing in the ledger
        pd.DataFrame([dict(date="2026-11-04", R=1.05)]).to_csv(os.path.join(self.ledger, "trades.csv"), index=False)
        f = watchdog.check(now, self.state, self.ledger)
        self.assertEqual((f[0][0], f[0][1]), ("eod-summary", "info")); self.assertIn("+1.05R", f[0][2])
        self.assertEqual(self.keys(at(19, 0)), [])                      # no late-evening nagging

    def test_eod_when_bot_never_finished(self):
        self.assertEqual(self.keys(at(16, 10)), ["eod-incomplete"])

    def test_dedupe_and_resend(self):
        sent = []
        n = types.SimpleNamespace(send=lambda m, ts=None: sent.append(m))
        watchdog.run(self.state, self.ledger, now=at(10, 0), notifier=n)
        watchdog.run(self.state, self.ledger, now=at(10, 5), notifier=n)
        self.assertEqual(len(sent), 1)                                  # same alert, 5 minutes later: not repeated
        watchdog.run(self.state, self.ledger, now=at(10, 40), notifier=n)
        self.assertEqual(len(sent), 2)                                  # still broken after 30 min: reminded


class Ensure(Tmp):
    def test_decide(self):
        self.assertFalse(ensure.decide(at(10, 0, "2026-11-07"), self.state)[0])
        self.assertFalse(ensure.decide(at(8, 0), self.state)[0])
        self.assertFalse(ensure.decide(at(16, 30), self.state)[0])
        self.assertEqual(ensure.decide(at(10, 0), self.state), (True, "start"))
        self.wj("2026-11-04.json", dict(done=True))
        self.assertEqual(ensure.decide(at(10, 0), self.state)[1], "today's session is already finished")

    def test_pid_file(self):
        open(os.path.join(self.state, "live.pid"), "w").write(str(os.getpid()))
        self.assertEqual(ensure.decide(at(10, 0), self.state), (False, "bot already running"))
        open(os.path.join(self.state, "live.pid"), "w").write("99999999")      # dead process: restart
        self.assertTrue(ensure.decide(at(10, 0), self.state)[0])

    def test_run_calls_runner_and_cleans_pid(self):
        calls = []
        ensure.run(Config(), state_dir=self.state, ledger_dir=self.ledger, now=at(10, 0), runner=lambda c, a: calls.append(a))
        self.assertEqual(len(calls), 1)
        self.assertFalse(os.path.exists(os.path.join(self.state, "live.pid")))
        ensure.run(Config(), state_dir=self.state, ledger_dir=self.ledger, now=at(8, 0), runner=lambda c, a: calls.append(a))
        self.assertEqual(len(calls), 1)


class LiveLoopOps(Tmp):
    def _sim(self, day, fail_ticks=0):
        from apex_master_bot import live
        orig = live.SimProvider.bars
        count = {"calls": 0}
        def flaky(self_, t):
            count["calls"] += 1
            if count["calls"] <= fail_ticks * 3:
                raise RuntimeError("simulated feed outage")
            return orig(self_, t)
        live.SimProvider.bars = flaky
        try:
            import io, contextlib
            buf = io.StringIO()
            a = types.SimpleNamespace(simulate_date=day, data=DATA, state_dir=self.state, ledger_dir=self.ledger, poll=60)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                live.run_live(Config(), a)
            return buf.getvalue()
        finally:
            live.SimProvider.bars = orig

    def test_heartbeat_state_and_ledger_columns(self):
        self._sim("2026-10-30")
        hb = json.load(open(os.path.join(self.state, "sim", "heartbeat.json")))
        st = json.load(open(os.path.join(self.state, "sim", "2026-10-30.json")))
        t = pd.read_csv(os.path.join(self.ledger, "sim", "trades.csv"))
        self.assertEqual((hb["phase"], hb["day"], st["outcome"], st["done"]), ("done", "2026-10-30", "traded", True))
        self.assertEqual(t.cfg.iloc[0], config_hash(Config()))
        self.assertIn("real_cost_R", t.columns)

    def test_survives_a_feed_outage_and_still_takes_the_same_trade(self):
        out = self._sim("2026-10-30", fail_ticks=4)
        t = pd.read_csv(os.path.join(self.ledger, "sim", "trades.csv"))
        self.assertEqual((t.ticker.iloc[0], round(t.R.iloc[0], 2)), ("QQQ", 1.05))
        self.assertNotIn("Traceback", out)

    def test_stand_down_is_recorded_for_the_scoreboard(self):
        from apex_master_bot import live
        import io, contextlib
        a = types.SimpleNamespace(simulate_date="2026-10-29", data=DATA, state_dir=self.state, ledger_dir=self.ledger, poll=60)
        with contextlib.redirect_stdout(io.StringIO()):
            live.run_live(dataclasses.replace(Config(), vix_prior_cap=10.0), a)
        st = json.load(open(os.path.join(self.state, "sim", "2026-10-29.json")))
        self.assertEqual(st["outcome"], "stood_down"); self.assertTrue(st["stand_down"].startswith("VIX"))


if __name__ == "__main__":
    unittest.main()
