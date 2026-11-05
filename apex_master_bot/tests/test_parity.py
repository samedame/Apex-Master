"""Run:  cd apex_master_bot && python3 -m unittest discover -s tests -v
Proves the bot behaves like the backtest, using the bars and trade logs in ../data and ../results."""
import dataclasses, json, os, shutil, sys, tempfile, types, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from apex_master_bot.config import Config, PROFILES
from apex_master_bot.data import CsvProvider
from apex_master_bot import replay as rp
from apex_master_bot.exits import evaluate
from apex_master_bot.live import run_live
from apex_master_bot.regime import gate

DATA = os.path.join(ROOT, "..", "data")
RES = os.path.join(ROOT, "..", "results")
P = CsvProvider(DATA)


class Parity(unittest.TestCase):
    def _check(self, profile, published, exp):
        t, _, _ = rp.run(P, PROFILES[profile], "tested")
        c = rp.compare(t, pd.read_csv(os.path.join(RES, published)))
        self.assertEqual((c["same_trade"], c["same_R"], c["only_bot"], c["only_published"]), (57, 57, [], []))
        s = rp.stats(t)
        for k, v in exp.items():
            self.assertAlmostEqual(s[k], v, places=6)

    def test_reliability_profile_matches_published_log(self):
        self._check("reliability", "MASTER_trades_tp1.2.csv",
                    dict(n=57, win=0.7017543859649122, meanR=0.30558741539611217, PF=1.7431798499837303, sumR=17.418482677578393))

    def test_runner_profile_matches_published_log(self):
        self._check("runner", "RUNNER_trades_tp2.5.csv",
                    dict(n=57, win=0.5964912280701754, meanR=0.6013886196585049, PF=2.137513351068124, sumR=34.27915132053478))

    def test_vix_gate_is_neutral_on_tested_sample(self):
        t0, _, _ = rp.run(P, dataclasses.replace(Config(), vix_prior_cap=None))
        t1, _, s = rp.run(P, Config())
        self.assertEqual(s, []); self.assertEqual(rp.stats(t0), rp.stats(t1))


class Exits(unittest.TestCase):
    cfg = Config()
    def test_target_beats_stop_on_same_bar_and_costs_apply(self):
        # long, entry 100 (open of bar 1), R=1: bar 1 high 101.3 (>= +1.2R) but close 98.9 (< -1R): target wins, as in sim_simple
        O = [0, 100, 100]; H = [0, 101.3, 100]; L = [0, 98.5, 100]; C = [0, 98.9, 100]
        r = evaluate(np.array(O), np.array(H), np.array(L), np.array(C), 0, 1, 1.0, self.cfg)
        self.assertEqual((r["reason"], round(r["R"], 6)), ("tp", 1.05))

    def test_stop_uses_close_not_low(self):
        O = [0, 100, 100, 100]; H = [0, 100.5, 100.5, 100.5]; L = [0, 98.0, 99.5, 99.5]; C = [0, 99.5, 99.4, 98.7]
        r = evaluate(np.array(O), np.array(H), np.array(L), np.array(C), 0, 1, 1.0, self.cfg)
        self.assertEqual(r["reason"], "stop"); self.assertEqual(r["bars"], 3)      # bar 1 low pierced -1R but closed above it
        self.assertAlmostEqual(r["R"], -1.3 - 0.15)

    def test_forming_bar_can_only_trigger_target(self):
        O = [0, 100, 100]; H = [0, 100.5, 101.3]; L = [0, 99.5, 98.0]; C = [0, 100, 98.5]
        a = evaluate(np.array(O), np.array(H), np.array(L), np.array(C), 0, 1, 1.0, self.cfg, last_complete=1)
        self.assertEqual(a["reason"], "tp")                                           # forming bar touched +1.2R
        H2 = [0, 100.5, 100.9]
        b = evaluate(np.array(O), np.array(H2), np.array(L), np.array(C), 0, 1, 1.0, self.cfg, last_complete=1)
        self.assertEqual(b["status"], "open")                                         # close-based stop waits for the bar to complete


class LiveLoop(unittest.TestCase):
    def _run(self, day, cfg=None):
        tmp = tempfile.mkdtemp()
        try:
            a = types.SimpleNamespace(simulate_date=day, data=DATA, state_dir=tmp, ledger_dir=tmp, poll=60)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                run_live(cfg or Config(), a)
            p = os.path.join(tmp, "sim", "trades.csv")
            return buf.getvalue(), (pd.read_csv(p) if os.path.exists(p) else None)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_live_loop_reproduces_replay_first_fire_trades(self):
        t, _, _ = rp.run(P, Config(), "first_fire")
        for day in ("2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"):
            _, lt = self._run(day)
            ref = t[t.date == day].iloc[0]
            row = lt.iloc[0]
            self.assertEqual((row.ticker, row.module, int(row.direction), int(row.minute)), (ref.ticker, ref.module, int(ref.direction), int(ref.minute)), day)
            self.assertAlmostEqual(row.R, ref.R, places=3, msg=day)

    def test_vix_gate_stands_the_bot_down(self):
        out, lt = self._run("2026-10-29", dataclasses.replace(Config(), vix_prior_cap=10.0))
        self.assertIn("NO TRADE TODAY", out); self.assertIsNone(lt)

    def test_gate_function(self):
        self.assertFalse(gate(25.0, 25.0)[0]); self.assertTrue(gate(24.99, 25.0)[0]); self.assertEqual(gate(22, 25)[1], "ELEVATED")


if __name__ == "__main__":
    unittest.main()
