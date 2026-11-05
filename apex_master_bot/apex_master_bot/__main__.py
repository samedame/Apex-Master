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
    dirs(w)
    sc = sub.add_parser("scoreboard", help="score the forward test against the strategy document's pass and kill bars")
    sc.add_argument("--notify", action="store_true", help="also post a one-line summary to Discord")
    dirs(sc)
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
        ensure.run(PROFILES[a.profile], poll=a.poll, state_dir=a.state_dir, ledger_dir=a.ledger_dir)
    elif a.cmd == "watchdog":
        from . import watchdog
        sys.exit(1 if any(f[1] == "alert" for f in watchdog.run(a.state_dir, a.ledger_dir)) else 0)
    elif a.cmd == "scoreboard":
        from . import scoreboard
        scoreboard.run(a.ledger_dir, a.state_dir, a.notify)


if __name__ == "__main__":
    main()
