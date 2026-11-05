"""Forward-test scoreboard: scores ledger/trades.csv against the pass and kill bars registered in section 9 of
APEX_CHRONOS_MASTER_STRATEGY.md.

  python3 -m apex_master_bot scoreboard            # prints the report, writes ledger/scoreboard.json
  python3 -m apex_master_bot scoreboard --notify   # also posts a short summary to Discord

Rules taken from the document:
  * Freeze: any parameter change restarts the count at zero. The ledger stamps every trade with a config
    fingerprint (config_hash); only the trailing run of trades with the CURRENT fingerprint is scored.
  * Duration: first 100 trades or 6 months, whichever is LATER.
  * Pass (all): win >= 60%, PF >= 1.30, mean >= +0.10R with bootstrap 95% CI lower bound > -0.05R,
    max drawdown >= -8R, no more than 6 losses in a row.
  * Kill (any): PF < 0.90 after 50 trades; mean < -0.10R after 50 trades; real round-trip cost > 0.45R;
    the regime gate would have blocked > 40% of days.
The ledger R already includes the 0.15R cost proxy. When quote logging exists, fill the `real_cost_R` column and
the real-cost kill test switches on by itself.
"""
import glob, json, os
import numpy as np
import pandas as pd
from .calendar_et import BASE

TRADES_TARGET, DAYS_TARGET = 100, 182
PASS = dict(win=0.60, pf=1.30, mean=0.10, ci_low=-0.05, max_dd=-8.0, max_losses=6)
KILL = dict(min_n=50, pf=0.90, mean=-0.10, real_cost=0.45, gate_share=0.40, min_days=20)


def load_trades(path):
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date", "R", "cfg"])
    t = pd.read_csv(path)
    t["date"] = pd.to_datetime(t["date"])
    if "cfg" not in t.columns:
        t["cfg"] = "unknown"
    t["cfg"] = t["cfg"].fillna("unknown").astype(str)
    return t.sort_values("date").reset_index(drop=True)


def current_cohort(t):
    """Trailing run of trades that share the newest config fingerprint."""
    if t.empty:
        return t, 0
    last = t["cfg"].iloc[-1]
    i = len(t)
    while i > 0 and t["cfg"].iloc[i - 1] == last:
        i -= 1
    return t.iloc[i:].reset_index(drop=True), i


def metrics(R, boot=20000, seed=1):
    R = np.asarray(R, float)
    n = len(R)
    if n == 0:
        return dict(n=0)
    wins = R[R > 0].sum()
    losses = -R[R < 0].sum()
    eq = np.cumsum(R)
    dd = float((eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]).min())
    run = best = 0
    for r in R:
        run = run + 1 if r < 0 else 0
        best = max(best, run)
    rng = np.random.default_rng(seed)
    means = rng.choice(R, size=(boot, n), replace=True).mean(axis=1) if n > 1 else np.array([R.mean()])
    lo, hi = np.percentile(means, [2.5, 97.5])
    return dict(n=n, win=float((R > 0).mean()), mean=float(R.mean()), sum=float(R.sum()),
                pf=float(wins / losses) if losses > 0 else float("inf"), max_dd=dd, max_losses=int(best),
                ci_low=float(lo), ci_high=float(hi))


def gate_share(state_dir):
    """Share of observed trading days on which the VIX gate stood the bot down."""
    days = gated = 0
    for p in glob.glob(os.path.join(state_dir, "20??-??-??.json")):
        try:
            with open(p) as f:
                s = json.load(f)
        except Exception:
            continue
        if not s.get("done"):
            continue
        days += 1
        gated += str(s.get("stand_down", "")).startswith("VIX")
    return days, gated


def evaluate(t_all, state_dir, today=None):
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    cohort, ignored = current_cohort(t_all)
    m = metrics(cohort["R"].values) if len(cohort) else dict(n=0)
    n = m["n"]
    first = cohort["date"].iloc[0] if n else None
    days = int((today - first).days) if first is not None else 0
    ready = n >= TRADES_TARGET and days >= DAYS_TARGET
    out = dict(cohort_cfg=cohort["cfg"].iloc[0] if n else None, ignored_trades=int(ignored), metrics=m,
               progress=dict(trades=n, trades_target=TRADES_TARGET, days=days, days_target=DAYS_TARGET, decision_ready=bool(ready)))
    if n == 0:
        out["verdict"] = "NO DATA"; out["pass_checks"] = []; out["kill_checks"] = []
        return out
    P = PASS
    pass_checks = [
        ("win rate >= 60%", m["win"], m["win"] >= P["win"], f"{m['win']:.1%}"),
        ("profit factor >= 1.30", m["pf"], m["pf"] >= P["pf"], f"{m['pf']:.2f}"),
        ("mean >= +0.10R", m["mean"], m["mean"] >= P["mean"], f"{m['mean']:+.3f}R"),
        ("bootstrap 95% CI lower bound > -0.05R", m["ci_low"], m["ci_low"] > P["ci_low"], f"{m['ci_low']:+.3f}R"),
        ("max drawdown >= -8R", m["max_dd"], m["max_dd"] >= P["max_dd"], f"{m['max_dd']:.1f}R"),
        ("losing streak <= 6", m["max_losses"], m["max_losses"] <= P["max_losses"], f"{m['max_losses']}"),
    ]
    K = KILL
    kill = []
    if n >= K["min_n"]:
        kill.append(("profit factor < 0.90 after 50 trades", m["pf"] < K["pf"], f"PF {m['pf']:.2f}"))
        kill.append(("mean < -0.10R after 50 trades", m["mean"] < K["mean"], f"mean {m['mean']:+.3f}R"))
    else:
        kill.append((f"PF / mean kill tests (start at {K['min_n']} trades)", None, f"{n}/{K['min_n']} trades"))
    rc = pd.to_numeric(cohort.get("real_cost_R"), errors="coerce").dropna() if "real_cost_R" in cohort else pd.Series(dtype=float)
    if len(rc):
        kill.append(("real round-trip cost > 0.45R", float(rc.mean()) > K["real_cost"], f"mean logged cost {rc.mean():.2f}R over {len(rc)} trades"))
    else:
        kill.append(("real round-trip cost > 0.45R", None, "not measured yet (needs quote logging)"))
    d, g = gate_share(state_dir)
    if d >= K["min_days"]:
        kill.append(("VIX gate blocked > 40% of days", g / d > K["gate_share"], f"{g}/{d} days"))
    else:
        kill.append(("VIX gate blocked > 40% of days", None, f"{g}/{d} days observed (needs {K['min_days']})"))
    killed = any(k[1] is True for k in kill)
    passed = all(c[2] for c in pass_checks)
    if killed:
        verdict = "KILLED"
    elif not ready:
        verdict = "IN PROGRESS"
    else:
        verdict = "PASS" if passed else "FAIL"
    out.update(verdict=verdict, pass_checks=[dict(name=a, value=b, ok=bool(c), shown=d_) for a, b, c, d_ in pass_checks],
               kill_checks=[dict(name=a, hit=b, shown=c) for a, b, c in kill])
    return out


def render(r):
    p, m = r["progress"], r["metrics"]
    lines = ["APEX MASTER forward test - scoreboard", "=" * 40]
    if r["verdict"] == "NO DATA":
        return "\n".join(lines + ["No closed trades in the ledger yet.", f"VERDICT: NO DATA (need {TRADES_TARGET} trades and {DAYS_TARGET} days)"])
    lines.append(f"Config fingerprint: {r['cohort_cfg']}" + (f"   ({r['ignored_trades']} earlier trades under other settings are NOT counted - the doc restarts the count on any change)" if r["ignored_trades"] else ""))
    lines.append(f"Progress: {p['trades']}/{p['trades_target']} trades, {p['days']}/{p['days_target']} days "
                 f"({'decision due' if p['decision_ready'] else 'both are needed before the pass/fail call'})")
    lines.append(f"Record: n={m['n']}  win {m['win']:.1%}  mean {m['mean']:+.3f}R  total {m['sum']:+.1f}R  PF {m['pf']:.2f}")
    lines.append("")
    lines.append("Pass bars (all required at the decision point; shown live for information)")
    for c in r["pass_checks"]:
        lines.append(f"  [{'ok' if c['ok'] else '--'}] {c['name']:<42} {c['shown']}")
    lines.append("")
    lines.append("Kill criteria (any one ends the test)")
    for k in r["kill_checks"]:
        mark = "HIT" if k["hit"] is True else ("clear" if k["hit"] is False else "n/a")
        lines.append(f"  [{mark:>5}] {k['name']:<42} {k['shown']}")
    lines += ["", f"VERDICT: {r['verdict']}",
              "Note: with few trades the intervals are very wide; do not read anything into ok/-- marks before the decision point."]
    return "\n".join(lines)


def run(ledger_dir=None, state_dir=None, notify=False, today=None):
    ledger_dir = ledger_dir or os.path.join(BASE, "ledger")
    state_dir = state_dir or os.path.join(BASE, "state")
    t = load_trades(os.path.join(ledger_dir, "trades.csv"))
    r = evaluate(t, state_dir, today)
    text = render(r)
    print(text)
    os.makedirs(ledger_dir, exist_ok=True)
    with open(os.path.join(ledger_dir, "scoreboard.json"), "w") as f:
        json.dump(r, f, indent=1, default=str)
    if notify:
        from .live import Notifier
        m = r["metrics"]
        short = (f"APEX MASTER scoreboard: {r['verdict']} | {m.get('n', 0)}/{TRADES_TARGET} trades"
                 + (f" | win {m['win']:.0%} mean {m['mean']:+.2f}R PF {m['pf']:.2f} DD {m['max_dd']:.1f}R" if m.get("n") else ""))
        Notifier().send(short)
    return r
