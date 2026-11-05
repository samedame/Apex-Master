"""Fetch market data into a fresh directory. Usage: python -I fetch.py OUTDIR"""
import sys, os, time, io
import pandas as pd
import yfinance as yf
import requests

out = sys.argv[1]
os.makedirs(out, exist_ok=True)

TICKERS = ["SPY", "QQQ", "IWM", "NVDA", "TSLA", "META", "AMD", "AAPL", "MSFT", "AMZN", "COIN", "MSTR"]
log = []

def grab(sym, interval, period, name):
    for attempt in range(4):
        try:
            d = yf.download(sym, interval=interval, period=period, auto_adjust=False,
                            progress=False, threads=False)
            if d is None or len(d) == 0:
                raise RuntimeError("empty")
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            d.to_csv(f"{out}/{name}.csv")
            log.append((name, len(d), str(d.index[0]), str(d.index[-1]), "ok"))
            return True
        except Exception as e:
            time.sleep(3 * (attempt + 1))
            err = repr(e)[:120]
    log.append((name, 0, "", "", "FAIL " + err))
    return False

for t in ["SPY", "QQQ", "IWM"]:
    grab(t, "1m", "8d", f"{t}_1m")
    grab(t, "5m", "60d", f"{t}_5m")
    grab(t, "15m", "60d", f"{t}_15m")
    grab(t, "1h", "730d", f"{t}_1h")
for t in TICKERS:
    if t not in ("SPY", "QQQ", "IWM"):
        grab(t, "5m", "60d", f"{t}_5m")
    grab(t, "1d", "max", f"{t}_1d")
for sym, name in [("^VIX", "VIX_1d"), ("^VIX3M", "VIX3M_1d"), ("^VVIX", "VVIX_1d"), ("^VIX9D", "VIX9D_1d"),
                  ("^GSPC", "GSPC_1d"), ("^TNX", "TNX_1d")]:
    grab(sym, "1d", "max", name)
grab("^VIX", "5m", "60d", "VIX_5m")

# FRED series (no key needed for the csv endpoint)
for sid in ["VIXCLS", "VXVCLS", "BAA10Y", "DGS10", "DGS2", "T10Y2Y"]:
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=30)
        r.raise_for_status()
        open(f"{out}/FRED_{sid}.csv", "w").write(r.text)
        df = pd.read_csv(io.StringIO(r.text))
        log.append((f"FRED_{sid}", len(df), str(df.iloc[0, 0]), str(df.iloc[-1, 0]), "ok"))
    except Exception as e:
        log.append((f"FRED_{sid}", 0, "", "", "FAIL " + repr(e)[:100]))

for row in log:
    print(*row, sep=" | ")
