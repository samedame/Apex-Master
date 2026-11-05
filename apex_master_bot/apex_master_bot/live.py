"""Live (paper-alert) runner. Same signal, exit and RVOL code as the replay; only the selection rule differs
(first_fire - see selector.py / README). Run it every trading day before 09:35 ET; it exits after 16:00 ET.

Alerts go to the console, logs/alerts.log and, if DISCORD_WEBHOOK_URL is set, to Discord.
The bot never places orders.
"""
import csv, datetime as dt, json, math, os, sys, time, traceback, urllib.request
from zoneinfo import ZoneInfo
import pandas as pd
from .calendar_et import BASE, HALF_DAYS
from .config import TZ, Config, config_hash
from .data import CsvProvider, YahooProvider, vix_prior_close
from .exits import evaluate
from .regime import gate
from .selector import pick_first_fire
from .signals import add_indicators, scan_bar, session_cumvols

NY = ZoneInfo(TZ)
BAR = dt.timedelta(minutes=5)
EVENT_FILE = os.path.join(BASE, "event_days.txt")                      # one YYYY-MM-DD per line: FOMC / CPI / NFP / election days (strategy doc: no trade)


class RealClock:
    def now(self): return dt.datetime.now(NY)
    def sleep(self, s): time.sleep(s)


class SimClock:
    def __init__(self, start): self.t = start
    def now(self): return self.t
    def sleep(self, s): self.t += dt.timedelta(seconds=s)


class SimProvider:
    """Serves only bars that have COMPLETED at the simulated time, so the live loop cannot peek."""
    def __init__(self, data_dir, clock):
        self.csv, self.clock, self._c = CsvProvider(data_dir), clock, {}
    def bars(self, t):
        if t not in self._c: self._c[t] = self.csv.bars(t)
        df = self._c[t]
        return df[df.index + BAR <= self.clock.now()]
    def vix_daily(self): return self.csv.vix_daily()


class Notifier:
    def __init__(self, log_dir=None):
        log_dir = log_dir or os.path.join(BASE, "logs")
        os.makedirs(log_dir, exist_ok=True)
        self.path, self.hook = os.path.join(log_dir, "alerts.log"), os.environ.get("DISCORD_WEBHOOK_URL")
    def send(self, msg, ts=None):
        stamp = (ts or dt.datetime.now(NY)).strftime("%Y-%m-%d %H:%M:%S ET")
        print(f"[{stamp}]\n{msg}\n", flush=True)
        with open(self.path, "a") as f: f.write(f"[{stamp}] {msg}\n")
        return self.post(msg) if self.hook else False

    def post(self, msg):
        """POST to the Discord webhook. Returns True only when Discord accepted it (HTTP 2xx)."""
        try:
            req = urllib.request.Request(self.hook, data=json.dumps({"content": msg[:1900]}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "apex-master-bot"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return 200 <= r.status < 300
        except Exception as e:
            print("webhook failed:", type(e).__name__, str(e)[:120], file=sys.stderr)
            return False


def _state_path(d, day): os.makedirs(d, exist_ok=True); return os.path.join(d, f"{day}.json")

def _append(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row)); 
        if new: w.writeheader()
        w.writerow(row)

def _weekly_R(ledger_dir, day):
    p = os.path.join(ledger_dir, "trades.csv")
    if not os.path.exists(p): return 0.0
    t = pd.read_csv(p); t["date"] = pd.to_datetime(t["date"])
    monday = pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).weekday())
    return float(t[(t.date >= monday) & (t.date < pd.Timestamp(day))].R.sum())


def _fmt(v, d=2): return f"{v:.{d}f}"

def entry_alert(c, entry, cfg, band, risk_pct, acct):
    d = c["direction"]; sd = c["stop_dist"]
    stop, tgt = entry - d * sd * cfg.stop_R, entry + d * sd * cfg.target_R
    until = (c["ts"] + BAR * (cfg.max_hold_bars + 1)).strftime("%H:%M")
    side = "LONG (bullish)" if d == 1 else "SHORT (bearish)"
    size = f"\nSIZE: {risk_pct:g}% of account at risk = {math.floor(acct * risk_pct / 100 / sd)} shares of underlying per 1R" if acct else f"\nSIZE: {risk_pct:g}% of account at risk (R = {_fmt(sd)} per share)"
    return (f"APEX MASTER ENTRY - {c['ticker']} {c['module']} {side}\n"
            f"Signal bar close {_fmt(c['signal_close'])} @ {c['ts'].strftime('%H:%M')}  |  RVOL {_fmt(c['rvol'])}  |  VIX band {band}\n"
            f"Entry ~{_fmt(entry)} (open of the next 5-min bar)  R = {_fmt(sd)}\n"
            f"STOP: a 5-min bar CLOSING {'below' if d == 1 else 'above'} {_fmt(stop)} (-{cfg.stop_R:g}R, close-based, no resting order)\n"
            f"TARGET: {_fmt(tgt)} (+{cfg.target_R:g}R, bar high/low touch)   TIME EXIT: close of the bar ending {until} ET"
            f"{size}\nNOTE: levels are on the underlying ETF - that is what was backtested.")


def _event_days():
    with open(EVENT_FILE) as f:
        return {l.strip() for l in f}


def run_live(cfg: Config, args):
    sim = bool(getattr(args, "simulate_date", None))
    if sim:
        day = args.simulate_date
        clock = SimClock(dt.datetime.fromisoformat(day + "T09:20:00").replace(tzinfo=NY))
        provider = SimProvider(args.data, clock)
        notifier = Notifier(os.path.join(args.state_dir, "sim_logs"))
        notifier.hook = None
        state_dir, ledger_dir = os.path.join(args.state_dir, "sim"), os.path.join(args.ledger_dir, "sim")
    else:
        clock, provider, notifier = RealClock(), YahooProvider(), Notifier()
        state_dir, ledger_dir = args.state_dir, args.ledger_dir
        day = clock.now().strftime("%Y-%m-%d")
    acct = float(os.environ["ACCOUNT_SIZE"]) if os.environ.get("ACCOUNT_SIZE") else None
    sp = _state_path(state_dir, day)
    st = json.load(open(sp)) if os.path.exists(sp) else {"scanned": {}, "fired": {}, "trade": None, "done": False}
    def save():
        with open(sp, "w") as f:
            json.dump(st, f, indent=1, default=str)
    hb_path = os.path.join(state_dir, "heartbeat.json")
    hb = {"errors_in_row": 0, "error": None, "last_bar": None, "restarts": 0}
    if os.path.exists(hb_path):
        try:
            prev = json.load(open(hb_path))
            if prev.get("day") == day: hb["restarts"] = prev.get("restarts", 0) + 1
        except Exception:
            pass

    def beat(phase, **kw):
        """Written every loop. The watchdog reads this to tell 'running', 'stalled' and 'finished' apart."""
        hb.update(ts=clock.now().isoformat(), day=day, pid=os.getpid(), phase=phase, profile_hash=config_hash(cfg), **kw)
        tmp = hb_path + ".tmp"
        with open(tmp, "w") as f: json.dump(hb, f)
        os.replace(tmp, hb_path)

    if st["done"]:
        print("already finished today"); return

    def stand_down(reason):
        notifier.send(f"APEX MASTER - NO TRADE TODAY: {reason}", clock.now())
        st["done"], st["stand_down"], st["outcome"] = True, reason, "stood_down"
        save(); beat("done")

    if day in HALF_DAYS: return stand_down("half-day session (tested pipeline skips sessions under 60 bars)")
    if os.path.exists(EVENT_FILE) and day in _event_days():
        return stand_down("event day listed in event_days.txt")
    vix_prev = vix_prior_close(provider.vix_daily(), day)
    ok, band, why = gate(vix_prev, cfg.vix_prior_cap)
    if not ok: return stand_down(why)
    wk = _weekly_R(ledger_dir, day)
    if wk <= cfg.weekly_stop_R: return stand_down(f"weekly stop hit ({wk:+.1f}R this week)")
    risk_pct = cfg.risk_pct_elevated if band == "ELEVATED" else cfg.risk_pct
    open_t = clock.now().replace(hour=9, minute=35, second=0, microsecond=0)
    end_t = clock.now().replace(hour=16, minute=0, second=0, microsecond=0)
    # the last signal bar (P2: minute 239 from the open) completes at 13:34 ET; after that nothing can fire
    scan_cut = clock.now().replace(hour=9, minute=30, second=0, microsecond=0) + dt.timedelta(minutes=cfg.p2_max_minute + cfg.bar_minutes + 1)
    notifier.send(f"APEX MASTER armed {day} | VIX prior close {_fmt(vix_prev)} ({band}) | risk {risk_pct:g}% | "
                  f"profile target {cfg.target_R:g}R | PAPER ALERTS ONLY", clock.now())
    while clock.now() < open_t: clock.sleep(15)

    beat("armed")
    ledger_row_cfg = config_hash(cfg)

    def tick():
        now = clock.now()
        try:
            frames = {t: provider.bars(t) for t in cfg.universe}
        except Exception as e:
            hb["errors_in_row"] += 1
            beat("scanning", error=f"data: {type(e).__name__}: {e}"[:300])
            if hb["errors_in_row"] in (3, 10) or hb["errors_in_row"] % 30 == 0:
                notifier.send(f"APEX MASTER WARNING - data feed failing ({hb['errors_in_row']} polls in a row): {e}", now)
            return
        days = {}
        for t, df in frames.items():
            g = df[df.index.date == pd.Timestamp(day).date()]
            if len(g): days[t] = (df, g)
        spy_last = str(frames["SPY"].index[-1]) if "SPY" in frames and len(frames["SPY"]) else None
        hb["errors_in_row"] = 0
        beat("in_trade" if st["trade"] else "scanning", error=None, last_bar=spy_last)
        if not days:
            return
        if st["trade"] is None:
            new = []
            for t, (df, g) in days.items():
                n_done = int(sum(1 for ts in g.index if ts + BAR <= now))
                if n_done < 4: continue
                cum = session_cumvols(df)
                gi = add_indicators(g, cfg)
                fired = set(st["fired"].get(t, []))
                for i in range(st["scanned"].get(t, 2) + 1, n_done):
                    new += scan_bar(gi, i, t, cum, fired, cfg)
                st["scanned"][t] = max(st["scanned"].get(t, 2), n_done - 1)
                st["fired"][t] = sorted(fired)
            for c in new:
                _append(os.path.join(ledger_dir, "candidates.csv"), {k: c[k] for k in ("date", "ticker", "module", "direction", "ts", "minute", "rvol", "stop_dist")})
            latest_done = max(int(sum(1 for ts in g.index if ts + BAR <= now)) for _, g in days.values()) - 1
            # oldest signals first; one that is more than one bar old (bot was down / late) is logged, not chased
            for ts_group in sorted({c["ts"] for c in new}):
                pick = pick_first_fire([c for c in new if c["ts"] == ts_group], cfg)
                if not pick: continue
                if latest_done - pick["bar"] > 1:
                    notifier.send(f"MISSED (not chased): {pick['ticker']} {pick['module']} signalled {pick['ts'].strftime('%H:%M')} - entry window passed", now)
                    continue
                df, g = days[pick["ticker"]]
                entry = float(g["Open"].iloc[pick["bar"] + 1]) if len(g) > pick["bar"] + 1 else pick["signal_close"]
                notifier.send(entry_alert(pick, entry, cfg, band, risk_pct, acct), now)
                st["trade"] = {**pick, "ts": str(pick["ts"]), "entry": entry, "band": band, "risk_pct": risk_pct}
                st["outcome"] = "open"
                break
        else:
            tr = st["trade"]; df, g = days[tr["ticker"]]
            gi = add_indicators(g, cfg)
            O, H, L, C = (gi[k].values for k in ("Open", "High", "Low", "Close"))
            last_complete = int(sum(1 for ts in g.index if ts + BAR <= now)) - 1
            ex = evaluate(O, H, L, C, tr["bar"], tr["direction"], tr["stop_dist"], cfg,
                          last_complete=last_complete, session_over=now >= end_t)
            if ex["entry"] is not None and abs(ex["entry"] - tr["entry"]) > 0.005:
                d, sd = tr["direction"], tr["stop_dist"]
                notifier.send(f"LEVELS UPDATE {tr['ticker']}: actual next-bar open {_fmt(ex['entry'])} -> stop close-{'below' if d == 1 else 'above'} "
                              f"{_fmt(ex['entry'] - d * sd)}, target {_fmt(ex['entry'] + d * sd * cfg.target_R)}", now)
                tr["entry"] = ex["entry"]
            if ex["status"] == "closed":
                label = {"tp": "TARGET HIT", "stop": "STOP (bar closed through -1R)", "time": "TIME EXIT"}[ex["reason"]]
                notifier.send(f"APEX MASTER EXIT - {tr['ticker']} {label}: {ex['R']:+.2f}R after costs ({ex['bars']} bars)", now)
                _append(os.path.join(ledger_dir, "trades.csv"), dict(
                    date=day, ticker=tr["ticker"], module=tr["module"], direction=tr["direction"], signal_ts=tr["ts"],
                    minute=tr["minute"], rvol=round(tr["rvol"], 4), entry=round(ex["entry"], 4), stop_dist=round(tr["stop_dist"], 4),
                    R=round(ex["R"], 4), reason=ex["reason"], bars=ex["bars"], band=tr["band"], risk_pct=tr["risk_pct"],
                    cfg=ledger_row_cfg, real_cost_R=""))
                st["done"], st["outcome"] = True, "traded"

    while clock.now() < end_t and not st["done"]:
        if st["trade"] is None and clock.now() >= scan_cut:
            break
        try:
            tick()
        except Exception as e:                      # never die silently mid-session: record it, tell the user, keep going
            hb["errors_in_row"] += 1
            beat("error", error=f"{type(e).__name__}: {e}"[:300])
            traceback.print_exc()
            if hb["errors_in_row"] in (1, 10) or hb["errors_in_row"] % 30 == 0:
                notifier.send(f"APEX MASTER ERROR in the live loop ({type(e).__name__}: {e}). It keeps retrying; check the logs.", clock.now())
        save()
        clock.sleep(args.poll)
    if st["trade"] is None:
        notifier.send("APEX MASTER - session over, no candidate fired: NO TRADE (a valid outcome).", clock.now())
        st["outcome"] = "no_candidate"
    elif not st["done"]:
        notifier.send("APEX MASTER WARNING - session ended with the trade still open. Check your position manually.", clock.now())
        st["outcome"] = "open_at_close"
    st["done"] = True; save(); beat("done")


def discord_test():
    """Used by the discord-test workflow and `python3 -m apex_master_bot discord-test`."""
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not hook:
        print("DISCORD_WEBHOOK_URL is not set (GitHub: Settings > Secrets and variables > Actions > New repository secret; the NAME is DISCORD_WEBHOOK_URL, the URL goes in the value box).")
        return False
    if not hook.startswith("https://discord.com/api/webhooks/") and not hook.startswith("https://discordapp.com/api/webhooks/"):
        print("DISCORD_WEBHOOK_URL is set but does not look like a Discord webhook URL (expected https://discord.com/api/webhooks/<id>/<token>).")
        return False
    n = Notifier()
    ok = n.post("APEX MASTER: webhook test OK. If you can read this, session alerts, failure alerts and end-of-day summaries will reach this channel.")
    print("Discord accepted the test message." if ok else "Discord REJECTED the message or could not be reached (see error above). Check the URL was not truncated and the webhook still exists.")
    return ok
