import argparse, json, os, sys
import pandas as pd
from .calendar_et import BASE
from .config import PROFILES
from .data import CsvProvider
from . import replay as rp


def main(argv=None):
    ap = argparse.ArgumentParser(prog="apex_master_bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay", help="re-run the tested pipeline on saved bars and check it against the published trade log")
    r.add_argument("--data", required=True, help="folder with SPY_5m.csv QQQ_5m.csv IWM_5m.csv VIX_1d.csv")
    r.add_argument("--profile", default="reliability", choices=list(PROFILES))
    r.add_argument("--selection", default="tested", choices=["tested", "first_fire"])
    r.add_argument("--published", help="published trade CSV to compare against")
    r.add_argument("--out", help="write the trade list here")

    def dirs(p):
        p.add_argument("--state-dir", default=os.path.join(BASE, "state"))
        p.add_argument("--ledger-dir", default=os.path.join(BASE, "ledger"))

    l = sub.add_parser("live", help="run today's session in the foreground (paper alerts)")
    l.add_argument("--profile", default="reliability", choices=list(PROFILES))
    l.add_argument("--simulate-date", help="YYYY-MM-DD: drive the live loop from saved bars with a fake clock")
    l.add_argument("--data", help="bars folder (required with --simulate-date)")
    l.add_argument("--poll", type=int, default=30, help="seconds between polls")
    dirs(l)
    e = sub.add_parser("ensure", help="scheduler entry: start the live bot if it should be running right now and is not")
    e.add_argument("--profile", default="reliability", choices=list(PROFILES))
    e.add_argument("--poll", type=int, default=30)
    dirs(e)
    w = sub.add_parser("watchdog", help="alert if the bot is down, stalled, has a dead feed, or left a trade open")
    w.add_argument("--eod", action="store_true", help="evaluate the end-of-day state now (used right after a session)")
    dirs(w)
    sub.add_parser("discord-test", help="send a test message to DISCORD_WEBHOOK_URL and report whether Discord accepted it")
    sc = sub.add_parser("scoreboard", help="score the forward test against the strategy document's pass and kill bars")
    sc.add_argument("--notify", action="store_true", help="also post a one-line summary to Discord")
    dirs(sc)
    v = sub.add_parser("v2-check", help="Master v2 pre-open check (paper alert): settles earlier signals, then decides for today")
    v.add_argument("--date", help="YYYY-MM-DD session to decide for (default: today, ET)")
    v.add_argument("--data", help="saved-bars folder instead of Yahoo/FRED (tests, offline)")
    v.add_argument("--no-notify", action="store_true", help="print only, do not post to Discord")
    dirs(v)
    vw = sub.add_parser("v2-watchdog", help="Master v2: if today's check never ran, say so and run it; score session days the bot missed")
    vw.add_argument("--date"); vw.add_argument("--data"); vw.add_argument("--no-notify", action="store_true")
    dirs(vw)
    vq = sub.add_parser("v2-quotes", help="Master v2: on a signal day, log real option quotes just after the open (paper)")
    vq.add_argument("--date"); vq.add_argument("--no-notify", action="store_true")
    vq.add_argument("--no-wait", action="store_true", help="do not wait for 09:31 ET")
    dirs(vq)
    vs = sub.add_parser("v2-status", help="one-line Master v2 forward-test summary")
    vs.add_argument("--notify", action="store_true")
    dirs(vs)
    vr = sub.add_parser("v2-replay", help="re-run the Master v2 rule on saved daily bars and compare with the research trade list")
    vr.add_argument("--data", required=True, help="folder with SPY_1d.csv QQQ_1d.csv IWM_1d.csv VIX_1d.csv")
    vr.add_argument("--published", help="research/master_v2/results/master_v2_trades.csv")
    a = ap.parse_args(argv)
    if a.cmd == "replay":
        cfg = PROFILES[a.profile]
        t, cands, skipped = rp.run(CsvProvider(a.data), cfg, a.selection)
        print(json.dumps(rp.stats(t), indent=2))
        if skipped:
            print("gate-skipped days:", skipped)
        if a.published:
            print(json.dumps(rp.compare(t, pd.read_csv(a.published)), indent=2))
        if a.out:
            t.to_csv(a.out, index=False)
    elif a.cmd == "live":
        from .live import run_live
        run_live(PROFILES[a.profile], a)
    elif a.cmd == "ensure":
        from . import ensure
        res = ensure.run(PROFILES[a.profile], poll=a.poll, state_dir=a.state_dir, ledger_dir=a.ledger_dir)
        if os.environ.get("GITHUB_OUTPUT"):                      # lets the workflow skip its wrap-up when nothing ran
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"result={'ran' if res == 'ran' else 'skip'}\n")
    elif a.cmd == "watchdog":
        from . import watchdog
        sys.exit(1 if any(f[1] == "alert" for f in watchdog.run(a.state_dir, a.ledger_dir, force_eod=a.eod)) else 0)
    elif a.cmd == "discord-test":
        from .live import discord_test
        sys.exit(0 if discord_test() else 1)
    elif a.cmd == "v2-check":
        import datetime as dt
        from . import v2
        from .live import Notifier
        day = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(v2.NY).date()
        prov = v2.CsvV2(a.data) if a.data else v2.YahooV2()
        n = Notifier()
        def notify(m):
            if a.no_notify:
                print(m + "\n")
            else:
                n.send(m)
        r = v2.run_check(day, prov, a.state_dir, a.ledger_dir, notify)
        print(f"v2 {r['day']}: {r['decision']} - {r.get('reason', '')}")
        # NO_DECISION already alerted Discord; a crash (uncaught exception) is what fails the CI step
    elif a.cmd == "v2-watchdog":
        import datetime as dt
        from . import v2
        from .live import Notifier
        day = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(v2.NY).date()
        prov = v2.CsvV2(a.data) if a.data else v2.YahooV2()
        n = Notifier()
        res = v2.run_watchdog(day, prov, a.state_dir, a.ledger_dir, (lambda m: print(m + "\n")) if a.no_notify else n.send)
        print(f"v2 watchdog {day}: ran_today={res['ran_today']} backfilled={res['backfilled']}")
    elif a.cmd == "v2-quotes":
        import datetime as dt
        from . import v2
        from .live import Notifier
        from .v2_quotes import make_chain, run_quotes
        import json as _j, os as _o
        day = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(v2.NY).date()
        sf = _o.path.join(a.state_dir, "v2", f"{day.isoformat()}.json")
        tk = None
        if _o.path.exists(sf):
            with open(sf) as _f:
                _st = _j.load(_f)
            tk = _st["ticker"] if _st.get("decision") == "TRADE" else None
        if tk is None:
            print(f"v2 quotes {day}: no signal today")
        else:
            n = Notifier()
            print("v2 quotes:", run_quotes(day, make_chain(tk), a.state_dir, a.ledger_dir, (lambda m: print(m + "\n")) if a.no_notify else n.send, wait=not a.no_wait))
    elif a.cmd == "v2-status":
        from . import v2
        from .live import Notifier
        line = v2.status(a.ledger_dir)
        if a.notify:
            Notifier().send(line)
        else:
            print(line)
    elif a.cmd == "v2-replay":
        from . import v2
        t = v2.replay(a.data)
        print(f"v2 replay: n={len(t)} mean net {t.net_bp.mean():+.2f} bp hit {(t.net_bp > 0).mean():.3f} sum {t.net_bp.sum():+.0f} bp")
        if a.published:
            p = pd.read_csv(a.published)
            same = len(t) == len(p) and (t.date.values == p.date.astype(str).values).all() and (t.ticker.values == p.ticker.values).all()
            print("matches published trade list (dates, tickers):", same,
                  "| max |net_bp diff|:", float((t.net_bp.values - p.net_bp.values).__abs__().max()) if same else "n/a")
    elif a.cmd == "scoreboard":
        from . import scoreboard
        scoreboard.run(a.ledger_dir, a.state_dir, a.notify)


if __name__ == "__main__":
    main()
