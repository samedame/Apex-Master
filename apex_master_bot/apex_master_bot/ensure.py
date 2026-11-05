"""Scheduler entry point. The scheduler (launchd/cron) calls this every ~5 minutes at ANY local time zone; it decides
by itself whether the bot should be running right now (ET clock, trading day, not finished, not already running)
and starts it if so. If the bot crashed, the next call restarts it and the saved state resumes the session.
"""
import datetime as dt, os, types
from .calendar_et import BASE, is_trading_day, now_et

WINDOW_START, WINDOW_END = dt.time(9, 10), dt.time(15, 59)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def decide(now, state_dir):
    """Returns (should_start, reason)."""
    if not is_trading_day(now.date()):
        return False, "not a trading day"
    if not (WINDOW_START <= now.time() < WINDOW_END):
        return False, "outside the 09:10-15:59 ET window"
    import json
    sp = os.path.join(state_dir, f"{now.date().isoformat()}.json")
    if os.path.exists(sp):
        with open(sp) as f:
            if json.load(f).get("done"):
                return False, "today's session is already finished"
    pidf = os.path.join(state_dir, "live.pid")
    if os.path.exists(pidf):
        try:
            with open(pidf) as f:
                pid = int(f.read().strip())
            if _alive(pid):
                return False, "bot already running"
        except ValueError:
            pass
    return True, "start"


def run(profile_cfg, poll=30, state_dir=None, ledger_dir=None, now=None, runner=None):
    state_dir = state_dir or os.path.join(BASE, "state")
    ledger_dir = ledger_dir or os.path.join(BASE, "ledger")
    now = now or now_et()
    go, why = decide(now, state_dir)
    if not go:
        print(f"ensure: {why}")
        return why
    os.makedirs(state_dir, exist_ok=True)
    pidf = os.path.join(state_dir, "live.pid")
    with open(pidf, "w") as f:
        f.write(str(os.getpid()))
    try:
        if runner is None:
            from .live import run_live as runner
        runner(profile_cfg, types.SimpleNamespace(simulate_date=None, data=None, state_dir=state_dir, ledger_dir=ledger_dir, poll=poll))
    finally:
        try:
            os.remove(pidf)
        except OSError:
            pass
    return "ran"
