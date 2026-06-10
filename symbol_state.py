import logging
import time
from datetime import datetime
from typing import Dict, Optional

import MetaTrader5 as mt5

from config import SymbolConfig, StrategyConfig, TIMEFRAME_META
from signal import SignalType, PositionType
from models import PositionState, SignalData
from trailing_stop import ATRTrailingStop, TrailingStopState

logger = logging.getLogger(__name__)
DEFAULT_DAILY_TRADE_LIMIT = 10


class SymbolState:

    def __init__(
        self,
        sym_cfg:              SymbolConfig,
        strat_cfg:            StrategyConfig,
        atr_trailing_enabled: bool = True,
    ):
        self.config    = sym_cfg
        self.strat_cfg = strat_cfg
        self.symbol    = sym_cfg.symbol

        self.ewmac_enabled        = strat_cfg.ewmac_enabled
        self.atr_trailing_enabled = atr_trailing_enabled

        stop_mult = TIMEFRAME_META[sym_cfg.primary_tf]["stop_multiplier"]
        self.trailing_stop = ATRTrailingStop(
            multiple=stop_mult, atr_period=strat_cfg.atr_period
        )
        self.trailing_stop_state: Optional[TrailingStopState] = None

        self.current_signal:          SignalType = SignalType.NEUTRAL
        self.current_forecast:        float      = 0.0
        self.current_trend:           str        = "NEUTRAL"
        self.current_stop_multiplier: float      = stop_mult
        self.last_signal_time:        Optional[datetime] = None

        self.ewmac_forecast:  float            = 0.0
        self.speed_forecasts: Dict[str, float] = {}

        self.position_state: PositionState = PositionState.empty()

        self.last_candle_time:   Optional[datetime] = None
        self.last_open_attempt:  float = 0.0
        self.last_close_attempt: float = 0.0
        self.daily_trades:       int   = 0
        self.last_reset_day:     int   = datetime.now().day

        self.current_price:    float = 0.0
        self.last_price:       float = 0.0
        self.price_change_pct: float = 0.0
        self.vol_daily:        float = 0.0
        self.atr:              float = 0.0
        self.atr_candle:       float = 0.0

        self._digits: Optional[int] = None

    @property
    def digits(self) -> int:
        if self._digits is None:
            info = mt5.symbol_info(self.symbol)
            self._digits = info.digits if info else 5
        return self._digits

    def update_signal(self, data: SignalData) -> None:
        self.current_signal   = data.signal
        self.current_forecast = data.forecast
        self.current_trend    = data.trend
        self.last_signal_time = data.timestamp
        self.ewmac_forecast   = data.forecast

    def reset_daily_counter(self) -> None:
        today = datetime.now().day
        if today != self.last_reset_day:
            self.daily_trades   = 0
            self.last_reset_day = today

    def can_open_position(self) -> bool:
        if self.position_state.has_position:
            return False
        daily_limit = (
            self.config.max_daily_trades
            if self.config.max_daily_trades is not None
            else DEFAULT_DAILY_TRADE_LIMIT
        )
        if self.daily_trades >= daily_limit:
            return False
        cooldown = TIMEFRAME_META[self.config.primary_tf]["cooldown"]
        if time.time() - self.last_open_attempt < cooldown:
            return False
        return True

    def can_close_position(self) -> bool:
        cooldown = TIMEFRAME_META[self.config.primary_tf]["cooldown"]
        return time.time() - self.last_close_attempt >= cooldown

    def should_enter_long(self) -> bool:
        return (
            not self.position_state.has_position
            and self.current_forecast >= self.strat_cfg.entry_threshold
        )

    def should_enter_short(self) -> bool:
        return (
            not self.position_state.has_position
            and self.current_forecast <= -self.strat_cfg.entry_threshold
        )

    def should_exit_long(self) -> bool:
        return (
            self.position_state.has_position
            and self.position_state.position_type == PositionType.LONG
            and self.current_forecast < self.strat_cfg.exit_threshold
        )

    def should_exit_short(self) -> bool:
        return (
            self.position_state.has_position
            and self.position_state.position_type == PositionType.SHORT
            and self.current_forecast > -self.strat_cfg.exit_threshold
        )

    def should_reverse_to_short(self) -> bool:
        return (
            self.position_state.has_position
            and self.position_state.position_type == PositionType.LONG
            and self.current_forecast <= -self.strat_cfg.entry_threshold
        )

    def should_reverse_to_long(self) -> bool:
        return (
            self.position_state.has_position
            and self.position_state.position_type == PositionType.SHORT
            and self.current_forecast >= self.strat_cfg.entry_threshold
        )

    def update_trailing_stop(
        self,
        current_price:      float,
        current_atr_candle: float = None,
        stop_multiplier:    float = None,
    ) -> bool:
        if not self.atr_trailing_enabled or not self.position_state.has_position:
            return False

        atr_to_use  = current_atr_candle if current_atr_candle is not None else self.atr_candle
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
            current_price,
            self.trailing_stop_state,
            self.position_state.position_type,
            digits=self.digits,
            symbol=self.symbol,
        )

        self.position_state.trailing_stop_price       = self.trailing_stop_state.stop_price
        self.position_state.highest_price_since_entry = self.trailing_stop_state.highest_price
        self.position_state.lowest_price_since_entry  = self.trailing_stop_state.lowest_price

        return old_stop != self.trailing_stop_state.stop_price

    def check_trailing_stop_exit(self, current_price: float) -> bool:
        if (
            not self.atr_trailing_enabled
            or not self.position_state.has_position
            or self.trailing_stop_state is None
        ):
            return False
        return self.trailing_stop.check_stop_triggered(
            current_price, self.trailing_stop_state, self.position_state.position_type
        )

    def get_distance_to_stop_percent(self) -> Optional[float]:
        if (
            not self.atr_trailing_enabled
            or not self.position_state.has_position
            or self.trailing_stop_state is None
        ):
            return None
        return self.trailing_stop.distance_to_stop_percent(
            self.current_price, self.trailing_stop_state, self.position_state.position_type
        )