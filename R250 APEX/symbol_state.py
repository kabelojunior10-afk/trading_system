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
DEFAULT_DAILY_TRADE_LIMIT = 5


class SymbolState:

    def __init__(
        self,
        sym_cfg:              SymbolConfig,
        strat_cfg:            StrategyConfig,
        atr_trailing_enabled: bool = True,
        smart_reentry_cfg=None,
    ):
        self.config    = sym_cfg
        self.strat_cfg = strat_cfg
        self.symbol    = sym_cfg.symbol
        self.smart_reentry_cfg = smart_reentry_cfg

        self.ewmac_enabled        = strat_cfg.ewmac_enabled
        self.atr_trailing_enabled = atr_trailing_enabled

        stop_mult = sym_cfg.vol_target_pct * 1000
        if hasattr(strat_cfg, 'atr_trailing') and strat_cfg.atr_trailing and strat_cfg.atr_trailing.multiple:
            stop_mult = strat_cfg.atr_trailing.multiple
            
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
        
        # Stop loss tracking for smart re-entry
        self.last_stop_time: Optional[float] = None
        self.last_stop_price: Optional[float] = None
        self.forecast_at_stop: Optional[float] = None
        self.atr_at_stop: Optional[float] = None
        self.consecutive_stops: int = 0
        self.last_stop_symbol: Optional[str] = None

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

    def record_stop_loss(self, stop_price: float, forecast: float, atr_value: float) -> None:
        """Record a stop loss event for smart re-entry logic"""
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.enabled:
            return
            
        self.last_stop_time = time.time()
        self.last_stop_price = stop_price
        self.forecast_at_stop = forecast
        self.atr_at_stop = atr_value
        self.consecutive_stops += 1
        self.last_stop_symbol = self.symbol
        
        logger.warning(
            f"{self.symbol}: STOP LOSS RECORDED | "
            f"stop_price={stop_price:.{self.digits}f} | "
            f"forecast={forecast:.2f} | "
            f"consecutive_stops={self.consecutive_stops}"
        )

    def reset_stop_tracking(self) -> None:
        """Reset stop tracking after a successful trade or timeout"""
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.enabled:
            return
            
        if self.last_stop_time and (time.time() - self.last_stop_time) > 3600:
            self.consecutive_stops = 0
            logger.debug(f"{self.symbol}: Stop tracking reset after 1 hour")

    def should_reenter_after_stop(self) -> tuple[bool, str]:
        """
        Smart re-entry logic after stop loss.
        Returns: (should_enter, reason)
        """
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.enabled:
            return True, "smart_reentry_disabled"
            
        # No stop recorded - can enter normally
        if self.last_stop_time is None:
            return True, "no_prior_stop"
        
        # Calculate time since stop
        minutes_since_stop = (time.time() - self.last_stop_time) / 60
        
        # RECENT STOP - Apply smart logic
        if minutes_since_stop < self.smart_reentry_cfg.cooldown_minutes:
            # Check 1: Forecast must be STRONGER than at stop
            required_strength = self.smart_reentry_cfg.forecast_strength_required
            if abs(self.current_forecast) <= abs(self.forecast_at_stop) * required_strength:
                return False, f"forecast_not_stronger (current={self.current_forecast:.2f} vs stop={self.forecast_at_stop:.2f})"
            
            # Check 2: Price must confirm reversal
            if self.smart_reentry_cfg.require_price_confirmation and self.last_stop_price:
                confirmation_pct = self.smart_reentry_cfg.price_confirmation_pct
                if self.current_price > self.last_stop_price * (1 + confirmation_pct):
                    return False, f"price_above_stop (price={self.current_price:.2f} > stop={self.last_stop_price:.2f})"
            
            # Check 3: ATR shouldn't be exploding
            if self.atr_candle > self.atr_at_stop * self.smart_reentry_cfg.atr_explosion_threshold:
                return False, f"atr_exploded (current_atr={self.atr_candle:.2f} vs stop_atr={self.atr_at_stop:.2f})"
            
            # Check 4: Consecutive stops limit
            if self.consecutive_stops >= self.smart_reentry_cfg.max_consecutive_stops:
                return False, f"too_many_consecutive_stops ({self.consecutive_stops})"
            
            return True, f"smart_reentry_approved (time={minutes_since_stop:.0f}min)"
        
        # Old stop (> cooldown) - can enter but check consecutive stops
        elif minutes_since_stop < 60:
            if self.consecutive_stops >= self.smart_reentry_cfg.max_consecutive_stops + 1:
                return False, f"excessive_stops ({self.consecutive_stops} in last hour)"
            return True, f"old_stop_allowed ({minutes_since_stop:.0f}min ago)"
        
        # Very old stop (>1 hour) - full reset
        else:
            self.consecutive_stops = 0
            return True, "stop_tracking_reset"

    def get_position_size_multiplier(self) -> float:
        """Dynamic position sizing based on stop loss history"""
        if not self.smart_reentry_cfg or not self.smart_reentry_cfg.size_reduction_enabled:
            return 1.0
            
        if self.last_stop_time is None:
            return 1.0
        
        minutes_since_stop = (time.time() - self.last_stop_time) / 60
        
        # Reduce size based on recency
        if minutes_since_stop < 15:
            return self.smart_reentry_cfg.size_reduction_factors[0]  # 0.3
        elif minutes_since_stop < 30:
            return self.smart_reentry_cfg.size_reduction_factors[1]  # 0.5
        elif minutes_since_stop < 60:
            return self.smart_reentry_cfg.size_reduction_factors[2]  # 0.7
        elif self.consecutive_stops >= 3:
            return 0.5  # Half size after multiple stops
        
        return self.smart_reentry_cfg.size_reduction_factors[3]  # 1.0

    def can_open_position(self) -> bool:
        if self.position_state.has_position:
            return False
            
        # Check daily limit
        daily_limit = (
            self.config.max_daily_trades
            if self.config.max_daily_trades is not None
            else DEFAULT_DAILY_TRADE_LIMIT
        )
        if self.daily_trades >= daily_limit:
            return False
            
        # Check cooldown
        cooldown = min(TIMEFRAME_META[self.config.primary_tf]["cooldown"], 60)
        if time.time() - self.last_open_attempt < cooldown:
            return False
        
        # Smart re-entry check
        can_reenter, reason = self.should_reenter_after_stop()
        if not can_reenter:
            logger.debug(f"{self.symbol}: Re-entry blocked - {reason}")
            return False
            
        return True

    def should_enter_long(self) -> bool:
        if not self.can_open_position():
            return False
        return self.current_forecast >= self.strat_cfg.entry_threshold

    def should_enter_short(self) -> bool:
        if not self.can_open_position():
            return False
        return self.current_forecast <= -self.strat_cfg.entry_threshold

    def should_exit_long(self) -> bool:
        """NEVER exit based on forecast fade - only trailing stop loss handles exits"""
        return False

    def should_exit_short(self) -> bool:
        """NEVER exit based on forecast fade - only trailing stop loss handles exits"""
        return False

    def should_reverse_to_short(self) -> bool:
        """Close long and go short when forecast reaches opposite entry threshold"""
        return (
            self.position_state.has_position
            and self.position_state.position_type == PositionType.LONG
            and self.current_forecast <= -self.strat_cfg.entry_threshold
        )

    def should_reverse_to_long(self) -> bool:
        """Close short and go long when forecast reaches opposite entry threshold"""
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

        self.position_state.trailing_stop_price = self.trailing_stop_state.stop_price
        self.position_state.highest_price_since_entry = self.trailing_stop_state.highest_price
        self.position_state.lowest_price_since_entry = self.trailing_stop_state.lowest_price

        return old_stop != self.trailing_stop_state.stop_price

    def check_trailing_stop_exit(self, current_price: float) -> bool:
        if (
            not self.atr_trailing_enabled
            or not self.position_state.has_position
            or self.trailing_stop_state is None
        ):
            return False
            
        triggered = self.trailing_stop.check_stop_triggered(
            current_price, self.trailing_stop_state, self.position_state.position_type
        )
        
        # Record stop loss if triggered
        if triggered and self.trailing_stop_state.stop_price:
            self.record_stop_loss(
                self.trailing_stop_state.stop_price,
                self.current_forecast,
                self.atr_candle
            )
            
        return triggered

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