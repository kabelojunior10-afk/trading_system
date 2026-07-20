# apex_symbol_state.py
import logging
import time
from datetime import datetime
from typing import Dict, Optional

import MetaTrader5 as mt5

from apex_config import SymbolConfig, StrategyConfig, TIMEFRAME_META
from signal import SignalType, PositionType
from models import PositionState, SignalData
from trailing_stop import ATRTrailingStop, TrailingStopState

logger = logging.getLogger(__name__)
DEFAULT_DAILY_TRADE_LIMIT = 8  # H1: fewer daily trades


class ApexSymbolState:

    def __init__(self, sym_cfg: SymbolConfig, strat_cfg: StrategyConfig, atr_trailing_enabled: bool = True, smart_reentry_cfg=None):
        self.config = sym_cfg
        self.strat_cfg = strat_cfg
        self.symbol = sym_cfg.symbol
        self.smart_reentry_cfg = smart_reentry_cfg

        self.ewmac_enabled = strat_cfg.ewmac_enabled
        self.atr_trailing_enabled = atr_trailing_enabled
        
        stop_mult = 2.2 if sym_cfg.primary_tf == "H1" else 1.8  # H1: 2.2x ATR for crypto
        self.trailing_stop = ATRTrailingStop(multiple=stop_mult, atr_period=strat_cfg.atr_period)
        self.trailing_stop_state: Optional[TrailingStopState] = None

        self.current_signal: SignalType = SignalType.NEUTRAL
        self.current_forecast: float = 0.0
        self.current_trend: str = "NEUTRAL"
        self.current_stop_multiplier: float = stop_mult
        self.last_signal_time: Optional[datetime] = None

        self.ewmac_forecast: float = 0.0
        self.breakout_forecast: float = 0.0  # NEW
        self.speed_forecasts: Dict[str, float] = {}

        self.position_state: PositionState = PositionState.empty()

        self.last_candle_time: Optional[datetime] = None
        self.last_open_attempt: float = 0.0
        self.last_close_attempt: float = 0.0
        self.daily_trades: int = 0
        self.last_reset_day: int = datetime.now().day

        self.current_price: float = 0.0
        self.last_price: float = 0.0
        self.price_change_pct: float = 0.0
        self.vol_daily: float = 0.0
        self.atr: float = 0.0
        self.atr_candle: float = 0.0

        self._digits: Optional[int] = None

        self.last_stop_time: Optional[float] = None
        self.last_stop_price: Optional[float] = None
        self.forecast_at_stop: Optional[float] = None
        self.atr_at_stop: Optional[float] = None
        self.consecutive_stops: int = 0
        self.last_stop_symbol: Optional[str] = None

        # Post-exit cooldown: tracks the time and type of the most
        # recent exit so re-entry gates can be applied.
        self.last_exit_time: Optional[float] = None
        self.last_exit_reason: Optional[str] = None   # "ATR_STOP" | "SIGNAL_REVERSAL" | other

    @property
    def digits(self) -> int:
        if self._digits is None:
            info = mt5.symbol_info(self.symbol)
            self._digits = info.digits if info else 5
        return self._digits

    def update_signal(self, data: SignalData) -> None:
        self.current_signal = data.signal
        self.current_forecast = data.forecast
        self.current_trend = data.trend
        self.last_signal_time = data.timestamp
        # FIX: Don't overwrite ewmac_forecast with the combined forecast
        # self.ewmac_forecast is set separately in _process_symbol

    def reset_daily_counter(self) -> None:
        today = datetime.now().day
        if today != self.last_reset_day:
            self.daily_trades = 0
            self.last_reset_day = today

    def record_stop_loss(self, stop_price: float, forecast: float, atr_value: float) -> None:
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.enabled:
            return

        self.last_stop_time = time.time()
        self.last_stop_price = stop_price
        self.forecast_at_stop = forecast
        self.atr_at_stop = atr_value
        self.consecutive_stops += 1

        logger.warning(f"{self.symbol}: STOP RECORDED | price={stop_price:.{self.digits}f} | consecutive={self.consecutive_stops}")

    def get_position_size_multiplier(self) -> float:
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.size_reduction_enabled:
            return 1.0

        if self.last_stop_time is None:
            return 1.0

        minutes_since_stop = (time.time() - self.last_stop_time) / 60

        if minutes_since_stop < 10:     # H1: longer reduction periods
            return 0.5
        elif minutes_since_stop < 20:
            return 0.7
        elif minutes_since_stop < 40:
            return 0.85
        elif self.consecutive_stops >= 5:
            return 0.5

        return 1.0

    def can_open_position(self) -> bool:
        if self.position_state.has_position:
            return False

        daily_limit = self.config.max_daily_trades or DEFAULT_DAILY_TRADE_LIMIT
        if self.daily_trades >= daily_limit:
            return False

        cooldown = 180  # H1: 3-min cooldown
        if time.time() - self.last_open_attempt < cooldown:
            return False

        # Post-exit cooldown: enforce a minimum wait after any exit
        # before the bot can re-enter, regardless of signal strength.
        if self.last_exit_time is not None:
            if self.last_exit_reason == "ATR_STOP":
                required_wait = 1800   # H1: 30 min after a trailing-stop hit
            elif self.last_exit_reason == "SIGNAL_REVERSAL":
                required_wait = 900    # H1: 15 min after a signal reversal
            else:
                required_wait = 30
            elapsed = time.time() - self.last_exit_time
            if elapsed < required_wait:
                return False

        return True

    def _reentry_forecast_threshold(self) -> float:
        """Return a stronger forecast gate when re-entering shortly after an exit."""
        if self.last_exit_time is None:
            return self.strat_cfg.entry_threshold

        elapsed = time.time() - self.last_exit_time

        # Within 60 minutes of a stop-out, require a much stronger signal.
        if self.last_exit_reason == "ATR_STOP":
            if elapsed < 3600:   # H1: within 60 min of stop-out
                return self.strat_cfg.entry_threshold * 3.0   # e.g. 4.5 vs base 1.5
            if elapsed < 7200:   # H1: within 120 min
                return self.strat_cfg.entry_threshold * 2.0   # e.g. 3.0
        # After a signal reversal, apply a moderate boost.
        elif self.last_exit_reason == "SIGNAL_REVERSAL":
            if elapsed < 1800:   # H1: within 30 min of reversal
                return self.strat_cfg.entry_threshold * 2.0
        return self.strat_cfg.entry_threshold

    def can_close_position(self) -> bool:
        if not self.position_state.has_position:
            return False
        if time.time() - self.last_close_attempt < 30:  # H1: 30-second cooldown
            return False
        return True

    def should_enter_long(self) -> bool:
        if not self.can_open_position():
            return False
        return self.current_forecast >= self._reentry_forecast_threshold()

    def should_enter_short(self) -> bool:
        if not self.can_open_position():
            return False
        return self.current_forecast <= -self._reentry_forecast_threshold()

    def should_reverse_to_short(self) -> bool:
        return (self.position_state.has_position and
                self.position_state.position_type == PositionType.LONG and
                self.current_forecast <= -self.strat_cfg.entry_threshold)

    def should_reverse_to_long(self) -> bool:
        return (self.position_state.has_position and
                self.position_state.position_type == PositionType.SHORT and
                self.current_forecast >= self.strat_cfg.entry_threshold)

    def update_trailing_stop(self, current_price: float, current_atr_candle: float = None,
                            stop_multiplier: float = None) -> bool:
        if not self.atr_trailing_enabled or not self.position_state.has_position:
            return False

        atr_to_use = current_atr_candle if current_atr_candle is not None else self.atr_candle
        
        # H1 uses 2.2x multiplier for trailing (balanced for crypto)
        if self.config.primary_tf == "H1":
            mult_to_use = 2.2 if stop_multiplier is None else stop_multiplier
        else:
            mult_to_use = stop_multiplier if stop_multiplier is not None else self.current_stop_multiplier

        if self.trailing_stop_state is None and self.position_state.trailing_stop_enabled:
            self.trailing_stop_state = TrailingStopState(
                enabled=True,
                stop_price=self.position_state.trailing_stop_price,
                entry_atr=self.position_state.entry_atr or atr_to_use,
                stop_multiplier=self.position_state.stop_multiplier or mult_to_use,
                timeframe=self.position_state.timeframe or self.config.primary_tf,
                highest_price=self.position_state.highest_price_since_entry,
                lowest_price=self.position_state.lowest_price_since_entry,
                initial_stop=self.position_state.initial_stop,
            )

        if self.trailing_stop_state is None:
            return False

        old_stop = self.trailing_stop_state.stop_price
        self.trailing_stop_state = self.trailing_stop.update_stop(
            current_price, self.trailing_stop_state, self.position_state.position_type,
            digits=self.digits, symbol=self.symbol
        )

        self.position_state.trailing_stop_price = self.trailing_stop_state.stop_price
        self.position_state.highest_price_since_entry = self.trailing_stop_state.highest_price
        self.position_state.lowest_price_since_entry = self.trailing_stop_state.lowest_price

        return old_stop != self.trailing_stop_state.stop_price

    def check_trailing_stop_exit(self, current_price: float) -> bool:
        if not self.atr_trailing_enabled or not self.position_state.has_position or self.trailing_stop_state is None:
            return False

        triggered = self.trailing_stop.check_stop_triggered(current_price, self.trailing_stop_state, self.position_state.position_type)

        if triggered and self.trailing_stop_state.stop_price:
            self.record_stop_loss(self.trailing_stop_state.stop_price, self.current_forecast, self.atr_candle)

        return triggered

    def get_distance_to_stop_percent(self) -> Optional[float]:
        if not self.atr_trailing_enabled or not self.position_state.has_position or self.trailing_stop_state is None:
            return None
        return self.trailing_stop.distance_to_stop_percent(
            self.current_price, self.trailing_stop_state, self.position_state.position_type
        )