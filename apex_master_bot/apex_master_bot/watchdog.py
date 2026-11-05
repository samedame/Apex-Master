"""Watchdog: run it every few minutes (the scheduler does). It stays silent on a healthy day and alerts when
the bot is not running, has stalled, has a dead data feed, or ended the day with a trade nobody closed.
It also posts one end-of-day line so a missed day never looks like a quiet "no trade" day.

  python3 -m apex_master_bot watchdog            # exit code 1 if anything needs attention
"""
import datetime as dt, json, os
from .calendar_et import BASE, is_trading_day, now_et

STALE_HEARTBEAT_S = 240        # the loop polls every 30 s; 4 minutes of silence means it stopped
STALE_BAR_S = 14 * 60          # newest SPY 5-minute bar older than this during the session = feed problem
GRACE_START = dt.time(9, 40)   # bot should be armed by now
SESSION_END = dt.time(16, 5)
EOD_LAST = dt.time(18, 0)      # stop nagging about the end-of-day findings after this
RESEND_S = 30 * 60


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def check(now, state_dir, ledger_dir):
    """Pure function: returns a list of (key, severity, message). severity is 'alert' or 'info'."""
    day = now.date()
    if not is_trading_day(day):
        return []
    t = now.time()
    if t < GRACE_START:
        return []
    ds = day.isoformat()
    hb = _read(os.path.join(state_dir, "heartbeat.json"))
    st = _read(os.path.join(state_dir, f"{ds}.json"))
    hb_today = hb if hb and hb.get("day") == ds else None
    out = []

    if t < SESSION_END:
        if st and st.get("done"):
            return []
        if hb_today is None:
            return [("not-running", "alert", f"APEX MASTER WATCHDOG: the bot has not started today ({ds}). No heartbeat found. "
                     "Check that the scheduler job is loaded and the computer was awake.")]
        age = (now - dt.datetime.fromisoformat(hb_today["ts"])).total_seconds()
        if age > STALE_HEARTBEAT_S:
            err = f" Last error: {hb_today['error']}" if hb_today.get("error") else ""
            out.append(("stalled", "alert", f"APEX MASTER WATCHDOG: the bot stopped updating {age / 60:.0f} min ago (last phase "
                        f"'{hb_today.get('phase')}').{err} The scheduler restarts it within a few minutes; if this repeats, check logs/."))
        elif hb_today.get("last_bar") and t >= dt.time(9, 55):
            last = dt.datetime.fromisoformat(hb_today["last_bar"]).astimezone(now.tzinfo)
            bar_age = (now - last).total_seconds()
            if bar_age > STALE_BAR_S:
                out.append(("feed-stale", "alert", f"APEX MASTER WATCHDOG: newest SPY 5-minute bar is from {last:%H:%M} ET "
                            f"({bar_age / 60:.0f} min old). The data feed looks stuck; alerts are not trustworthy."))
        if hb_today.get("errors_in_row", 0) >= 3 and hb_today.get("error"):
            out.append(("errors", "alert", f"APEX MASTER WATCHDOG: {hb_today['errors_in_row']} polls in a row failed: {hb_today['error']}"))
        return out

    # end of day
    if t > EOD_LAST:
        return []
    if st is None or not st.get("done"):
        why = "never ran today" if hb_today is None else "did not finish the session cleanly"
        return [("eod-incomplete", "alert", f"APEX MASTER WATCHDOG: the bot {why} ({ds}). Check for an open position manually.")]
    outcome = st.get("outcome", "unknown")
    ledger = os.path.join(ledger_dir, "trades.csv")
    closed_today = False
    R = None
    if os.path.exists(ledger):
        import csv
        with open(ledger) as f:
            for row in csv.DictReader(f):
                if row.get("date") == ds:
                    closed_today, R = True, float(row["R"])
    if st.get("trade") and not closed_today:
        return [("open-trade", "alert", f"APEX MASTER WATCHDOG: {ds} has a trade ({st['trade'].get('ticker')}) with no closing entry in the ledger. "
                 "Treat it as open and check manually.")]
    if outcome == "traded" and closed_today:
        msg = f"APEX MASTER {ds}: traded {st['trade']['ticker']} {st['trade']['module']}, {R:+.2f}R."
    elif outcome == "stood_down":
        msg = f"APEX MASTER {ds}: no trade (stood down: {st.get('stand_down')})."
    elif outcome == "no_candidate":
        msg = f"APEX MASTER {ds}: bot ran all session, no setup fired. No trade."
    else:
        msg = f"APEX MASTER {ds}: finished with outcome '{outcome}'."
    return [("eod-summary", "info", msg)]


def run(state_dir=None, ledger_dir=None, now=None, notifier=None):
    state_dir = state_dir or os.path.join(BASE, "state")
    ledger_dir = ledger_dir or os.path.join(BASE, "ledger")
    now = now or now_et()
    findings = check(now, state_dir, ledger_dir)
    if findings and notifier is None:
        from .live import Notifier
        notifier = Notifier()
    sent_path = os.path.join(state_dir, "watchdog.json")
    sent = _read(sent_path) or {}
    changed = False
    for key, sev, msg in findings:
        k = f"{now.date()}:{key}"
        last = sent.get(k)
        age = (now - dt.datetime.fromisoformat(last)).total_seconds() if last else None
        if last and (sev == "info" or age < RESEND_S):
            continue                                   # already told you recently / today
        notifier.send(msg, now)
        sent[k] = now.isoformat()
        changed = True
    if changed:
        os.makedirs(state_dir, exist_ok=True)
        with open(sent_path, "w") as f:
            json.dump({k: v for k, v in sent.items() if k[:10] >= (now.date() - dt.timedelta(days=3)).isoformat()}, f)
    return findings
