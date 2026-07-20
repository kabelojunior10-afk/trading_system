# apex_breakout_strategy.py
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

from signal import SignalType

logger = logging.getLogger(__name__)


@dataclass
class BreakoutSpeed:
    """Breakout configuration with different lookback periods."""
    n: int  
    weight: float = 0.25
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = f"breakout_{self.n}"


class MultiSpeedBreakout:
    """
    Multi-speed breakout strategy using multiple lookback periods.
    Similar to EWMAC but using breakout signals instead of moving average crossovers.
    """

    def __init__(self, speeds: list, forecast_cap: float = 20.0, forecast_scale: float = 2.0, 
                 multiplier: float = 20.0):
        """
        Initialize breakout strategy with multiple speeds.

        Args:
            speeds: List of BreakoutSpeed objects
            forecast_cap: Maximum absolute forecast value (capped at ±20)
            forecast_scale: Scaling factor for breakout signal
            multiplier: Base multiplier to scale breakout signals to match EWMAC range
        """
        self.speeds = speeds
        self.forecast_cap = forecast_cap
        self.forecast_scale = forecast_scale
        self.multiplier = multiplier

        logger.info(f"APEX BREAKOUT STRATEGY | Speeds: {[s.name for s in speeds]} | Cap: ±{forecast_cap} | Multiplier: {multiplier}")

    def calculate(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Calculate breakout signals for all speeds and return combined forecast.

        Args:
            df: DataFrame with OHLC data

        Returns:
            Dictionary with speed forecasts and combined forecast
        """
        if len(df) < max([s.n for s in self.speeds]):
            return {"combined": 0.0, **{s.name: 0.0 for s in self.speeds}}

        speed_forecasts = {}
        for speed in self.speeds:
            forecast = self._calculate_single_breakout(df, speed.n)
            speed_forecasts[speed.name] = forecast

        # Weighted combination
        raw_combined = sum(s.weight * speed_forecasts[s.name] for s in self.speeds)
        combined = float(np.clip(raw_combined, -self.forecast_cap, self.forecast_cap))

        speed_forecasts["combined"] = combined
        return speed_forecasts

    def _calculate_single_breakout(self, df: pd.DataFrame, n: int) -> float:
        """
        Calculate breakout signal for a single lookback period.

        Args:
            df: DataFrame with OHLC data
            n: Lookback period in bars

        Returns:
            Scaled and capped forecast value (±20)
        """
        if len(df) < n:
            return 0.0

        price = df["close"].iloc[-1]

        # Rolling max and min over last N periods
        rmax_n = df["close"].iloc[-n:].max()
        rmin_n = df["close"].iloc[-n:].min()
        ravgn = (rmax_n + rmin_n) / 2.0

        # Avoid division by zero
        range_width = rmax_n - rmin_n
        if range_width == 0:
            return 0.0

        # Scaled price: ranges from -0.5 to +0.5
        scaled_price = (price - ravgn) / range_width

        # Scale to match EWMAC forecast magnitude (±20)
        # Using multiplier=20.0 to keep forecasts in ±20 range
        forecast = scaled_price * self.forecast_scale * self.multiplier

        # Cap the forecast at ±20
        forecast = float(np.clip(forecast, -self.forecast_cap, self.forecast_cap))

        return forecast

    def to_signal(self, forecast: float, threshold: float = 0.3) -> SignalType:
        """Convert forecast to signal type."""
        if forecast >= threshold:
            return SignalType.BUY
        if forecast <= -threshold:
            return SignalType.SELL
        return SignalType.NEUTRAL

    def to_trend(self, forecast: float) -> str:
        """Convert forecast to trend description."""
        if forecast > 0.3:
            return "BULLISH"
        if forecast < -0.3:
            return "BEARISH"
        return "NEUTRAL"


def get_default_breakout_speeds(timeframe: str = "H1") -> list:
    """
    Get default breakout speeds based on timeframe.

    For H1: Using 160, 320, 640, 1280 bars
    These correspond to approximately 7, 14, 27, 53 days of H1 data.

    For M15: Using 160, 320, 640, 1280 bars
    These correspond to approximately 1.7, 3.3, 6.7, 13.3 days.
    """
    if timeframe == "H1":
        # H1: ~7 days, ~14 days, ~27 days, ~53 days
        return [
            BreakoutSpeed(n=160, weight=0.35),
            BreakoutSpeed(n=320, weight=0.30),
            BreakoutSpeed(n=640, weight=0.20),
            BreakoutSpeed(n=1280, weight=0.15),
        ]
    elif timeframe == "H4":
        return [
            BreakoutSpeed(n=40, weight=0.35),
            BreakoutSpeed(n=80, weight=0.30),
            BreakoutSpeed(n=160, weight=0.20),
            BreakoutSpeed(n=320, weight=0.15),
        ]
    else:  
        return [
            BreakoutSpeed(n=160, weight=0.35),
            BreakoutSpeed(n=320, weight=0.30),
            BreakoutSpeed(n=640, weight=0.20),
            BreakoutSpeed(n=1280, weight=0.15),
        ]