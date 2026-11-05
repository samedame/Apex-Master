"""Bar sources. CsvProvider reads the same files the backtest used; YahooProvider is the live feed
(the backtest also used Yahoo 5-minute bars)."""
import os
import pandas as pd
from .config import TZ


def _clean_5m(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d.index = pd.to_datetime(d.index, utc=True).tz_convert(TZ)
    d = d[~d.index.duplicated(keep="last")].sort_index()
    d = d[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    return d.between_time("09:30", "15:55")          # engine.load


class CsvProvider:
    def __init__(self, data_dir: str):
        self.dir = data_dir

    def bars(self, ticker: str) -> pd.DataFrame:
        d = pd.read_csv(os.path.join(self.dir, f"{ticker}_5m.csv"), index_col=0, parse_dates=True)
        return _clean_5m(d)

    def vix_daily(self) -> pd.Series:
        d = pd.read_csv(os.path.join(self.dir, "VIX_1d.csv"), index_col=0, parse_dates=True)
        s = d["Close"].astype(float)
        s.index = pd.to_datetime(s.index, utc=True).tz_localize(None).normalize() if s.index.tz else pd.to_datetime(s.index).normalize()
        return s.dropna()


class YahooProvider:
    """Needs `pip install yfinance`. Yahoo 5m history is limited to ~60 days (same limit as the backtest)."""

    def __init__(self, period: str = "60d"):
        import yfinance as yf  # lazy so replay works without it
        self.yf = yf
        self.period = period

    def bars(self, ticker: str) -> pd.DataFrame:
        d = self.yf.Ticker(ticker).history(period=self.period, interval="5m", prepost=False, auto_adjust=False)
        if d is None or d.empty:
            raise RuntimeError(f"no 5m bars returned for {ticker}")
        return _clean_5m(d)

    def vix_daily(self) -> pd.Series:
        d = self.yf.Ticker("^VIX").history(period="1mo", interval="1d", auto_adjust=False)
        s = d["Close"].astype(float)
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        return s.dropna()


def vix_prior_close(vix: pd.Series, session_date) -> float:
    """Last VIX close strictly before the session date (backtest: vix_prior = VIX close shifted by one day)."""
    prior = vix[vix.index < pd.Timestamp(session_date)]
    return float(prior.iloc[-1]) if len(prior) else float("nan")
