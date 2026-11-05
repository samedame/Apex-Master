import yfinance as yf, pandas as pd, os, time
TICKERS=["SPY","QQQ","IWM","NVDA","TSLA","META","AMD","AAPL","MSFT","AMZN","COIN","MSTR"]
os.makedirs("/home/user/Apex_Master/data", exist_ok=True)
for t in TICKERS+["^VIX"]:
    for interval,period in [("5m","60d"),("1d","5y")]:
        fn=f"/home/user/Apex_Master/data/{t.replace('^','')}_{interval}.csv"
        if os.path.exists(fn): continue
        d=yf.download(t, interval=interval, period=period, progress=False, auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns=d.columns.get_level_values(0)
        d.to_csv(fn); print(t,interval,d.shape)
    time.sleep(0.3)
# SPX daily long for regime
for t in ["^GSPC","^VIX"]:
    fn=f"/home/user/Apex_Master/data/{t.replace('^','')}_1d_long.csv"
    d=yf.download(t, interval="1d", period="max", progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex): d.columns=d.columns.get_level_values(0)
    d.to_csv(fn); print(t,"long",d.shape)
