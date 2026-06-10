# apex_ewmac_strategy.py
import logging
from dataclasses import dataclass
from typing import Dict
import math

import numpy as np
import pandas as pd

from apex_config import EWMACSpeed, StrategyConfig, TIMEFRAME_META, MIN_BARS_FOR_ATR
from signal import SignalType

logger = logging.getLogger(__name__)


@dataclass
class ForecastResult:
    combined_forecast: float
    speed_forecasts: Dict[str, float]
    signal: SignalType
    trend: str
    vol_daily: float
    atr_candle: float
    atr_daily: float
    atr_annualized: float
    stop_multiplier: float
    timeframe: str


class MultiSpeedEWMAC:

    def __init__(self, cfg: StrategyConfig, timeframe: str = "M5"):
        self.cfg = cfg
        self.timeframe = timeframe
        self.timeframe_meta = TIMEFRAME_META.get(timeframe, TIMEFRAME_META["M5"])

        candles_per_day = self.timeframe_meta["atr_multiplier"]
        self.atr_to_daily_multiplier = math.sqrt(candles_per_day)
        self.stop_multiplier = self.timeframe_meta["stop_multiplier"]

        logger.info(
            f"APEX EWMAC (ULTRA) | tf={timeframe} | "
            f"daily_mult={self.atr_to_daily_multiplier:.2f}x | "
            f"stop_mult={self.stop_multiplier}x | ATR={cfg.atr_period}"
        )

    def calculate(self, df: pd.DataFrame) -> ForecastResult:
        _empty = ForecastResult(
            combined_forecast=0.0,
            speed_forecasts={s.name: 0.0 for s in self.cfg.speeds},
            signal=SignalType.NEUTRAL,
            trend="NEUTRAL",
            vol_daily=0.0,
            atr_candle=0.0,
            atr_daily=0.0,
            atr_annualized=0.0,
            stop_multiplier=self.stop_multiplier,
            timeframe=self.timeframe,
        )

        if not self.cfg.ewmac_enabled:
            return _empty

        if len(df) < MIN_BARS_FOR_ATR:
            return _empty

        df = df.copy()
        df = self._add_volatility(df)
        df = self._add_atr(df)

        confirmed_df = df.iloc[:-1]

        speed_forecasts: Dict[str, float] = {}
        for speed in self.cfg.speeds:
            df = self._add_ewmac_forecast(df, speed)
            val = float(df[speed.name].iloc[-2])
            speed_forecasts[speed.name] = 0.0 if np.isnan(val) else val

        raw_combined = sum(speed.weight * speed_forecasts[speed.name] for speed in self.cfg.speeds)
        combined = float(np.clip(raw_combined * self.cfg.fdm, self.cfg.cap_min, self.cfg.cap_max))

        vol_daily = float(df["vol_daily"].iloc[-2])
        if np.isnan(vol_daily) or vol_daily <= 0:
            vol_daily = float(df["close"].iloc[-2]) * 0.01

        atr_candle = self._extract_atr(confirmed_df)
        atr_daily = atr_candle * self.atr_to_daily_multiplier
        atr_annualized = max(0.50, min(5.0, atr_daily * math.sqrt(252)))

        return ForecastResult(
            combined_forecast=combined,
            speed_forecasts=speed_forecasts,
            signal=self._to_signal(combined),
            trend=self._to_trend(combined),
            vol_daily=vol_daily,
            atr_candle=atr_candle,
            atr_daily=atr_daily,
            atr_annualized=atr_annualized,
            stop_multiplier=self.stop_multiplier,
            timeframe=self.timeframe,
        )

    def _add_volatility(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ret"] = df["close"].pct_change()
        df["abs_ret"] = df["ret"].abs()
        df["vol_pct"] = df["abs_ret"].ewm(span=self.cfg.vol_lookback, adjust=False).mean()
        df["vol_daily"] = df["vol_pct"] * df["close"]
        df["vol_daily"] = df["vol_daily"].replace(0.0, np.nan).ffill().bfill()
        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(span=self.cfg.atr_period, adjust=False, min_periods=self.cfg.atr_period).mean()

        if len(atr) < self.cfg.atr_period:
            atr.iloc[:self.cfg.atr_period] = tr.iloc[:self.cfg.atr_period].expanding().mean()

        df["atr_raw"] = atr.ffill().bfill()
        min_atr = df["close"] * 0.0001
        df["atr_raw"] = df["atr_raw"].clip(lower=min_atr)
        return df

    def _extract_atr(self, df: pd.DataFrame) -> float:
        if "atr_raw" in df.columns:
            atr_value = float(df["atr_raw"].iloc[-1])
            if not np.isnan(atr_value) and atr_value > 0:
                return atr_value

        high = df["high"].values[-10:]
        low = df["low"].values[-10:]
        close = df["close"].values[-11:-1]

        if len(high) >= 8:
            trs = []
            for i in range(1, len(high)):
                tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
                trs.append(tr)
            if trs:
                atr_value = sum(trs) / len(trs)
                alpha = 2.0 / (self.cfg.atr_period + 1)
                smoothed = atr_value
                for tr in trs[-self.cfg.atr_period:]:
                    smoothed = tr * alpha + smoothed * (1 - alpha)
                if smoothed > 0:
                    return smoothed

        current_price = float(df["close"].iloc[-1])
        return max(current_price * 0.001, current_price * 0.003)

    def _add_ewmac_forecast(self, df: pd.DataFrame, speed: EWMACSpeed) -> pd.DataFrame:
        fast_ewma = df["close"].ewm(span=speed.fast, adjust=False).mean()
        slow_ewma = df["close"].ewm(span=speed.slow, adjust=False).mean()
        raw = fast_ewma - slow_ewma

        safe_vol = df["vol_daily"].replace(0.0, np.nan).ffill().bfill()
        norm = raw / safe_vol
        scaled = norm * speed.scalar
        df[speed.name] = scaled.clip(self.cfg.cap_min, self.cfg.cap_max)
        return df

    def _to_signal(self, forecast: float) -> SignalType:
        if forecast >= self.cfg.entry_threshold:
            return SignalType.BUY
        if forecast <= -self.cfg.entry_threshold:
            return SignalType.SELL
        return SignalType.NEUTRAL

    @staticmethod
    def _to_trend(forecast: float) -> str:
        if forecast > 0.3:
            return "BULLISH"
        if forecast < -0.3:
            return "BEARISH"
        return "NEUTRAL"