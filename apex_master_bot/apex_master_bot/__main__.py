import argparse, json, os, sys
import pandas as pd
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
    l = sub.add_parser("live", help="run today's session (paper alerts)")
    l.add_argument("--profile", default="reliability", choices=list(PROFILES))
    l.add_argument("--simulate-date", help="YYYY-MM-DD: drive the live loop from saved bars with a fake clock")
    l.add_argument("--data", help="bars folder (required with --simulate-date)")
    l.add_argument("--state-dir", default="state")
    l.add_argument("--ledger-dir", default="ledger")
    l.add_argument("--poll", type=int, default=30, help="seconds between polls")
    a = ap.parse_args(argv)
    cfg = PROFILES[a.profile]
    if a.cmd == "replay":
        t, cands, skipped = rp.run(CsvProvider(a.data), cfg, a.selection)
        print(json.dumps(rp.stats(t), indent=2))
        if skipped:
            print("gate-skipped days:", skipped)
        if a.published:
            print(json.dumps(rp.compare(t, pd.read_csv(a.published)), indent=2))
        if a.out:
            t.to_csv(a.out, index=False)
    else:
        from .live import run_live
        run_live(cfg, a)


if __name__ == "__main__":
    main()
