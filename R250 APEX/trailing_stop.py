import logging
from dataclasses import dataclass
from typing import Optional

from signal import PositionType

logger = logging.getLogger(__name__)

@dataclass
class TrailingStopState:
    enabled:         bool  = False
    stop_price:      Optional[float] = None
    entry_atr:       Optional[float] = None
    stop_multiplier: float = 2.5
    timeframe:       str   = "M15"
    highest_price:   Optional[float] = None
    lowest_price:    Optional[float] = None
    initial_stop:    Optional[float] = None


class ATRTrailingStop:

    def __init__(self, multiple: float, atr_period: int = 10):
        self.multiple   = multiple
        self.atr_period = atr_period

    def update_stop(
        self,
        current_price: float,
        current_state: TrailingStopState,
        position_type: PositionType,
        digits:        int = 5,
        symbol:        str = "",
    ) -> TrailingStopState:
        if not current_state.enabled:
            return current_state

        new_state = TrailingStopState(
            enabled=True,
            stop_price=current_state.stop_price,
            entry_atr=current_state.entry_atr,
            stop_multiplier=current_state.stop_multiplier,
            timeframe=current_state.timeframe,
            highest_price=current_state.highest_price,
            lowest_price=current_state.lowest_price,
            initial_stop=current_state.initial_stop,
        )

        if new_state.entry_atr is None or new_state.entry_atr <= 0:
            return new_state

        if position_type == PositionType.LONG:
            if new_state.highest_price is None or current_price > new_state.highest_price:
                new_state.highest_price = current_price

            new_stop = round(
                new_state.highest_price
                - (new_state.entry_atr * new_state.stop_multiplier),
                digits,
            )

            if new_state.stop_price is None or new_stop > new_state.stop_price:
                old = new_state.stop_price
                new_state.stop_price = new_stop
                if old is not None:
                    logger.info(
                        f"TRAIL UPDATE {symbol} [{new_state.timeframe}]: "
                        f"LONG stop {old:.{digits}f} → {new_stop:.{digits}f} "
                        f"(mult={new_state.stop_multiplier}x)"
                    )

        else:  # SHORT
            if new_state.lowest_price is None or current_price < new_state.lowest_price:
                new_state.lowest_price = current_price

            new_stop = round(
                new_state.lowest_price
                + (new_state.entry_atr * new_state.stop_multiplier),
                digits,
            )

            if new_state.stop_price is None or new_stop < new_state.stop_price:
                old = new_state.stop_price
                new_state.stop_price = new_stop
                if old is not None:
                    logger.info(
                        f"TRAIL UPDATE {symbol} [{new_state.timeframe}]: "
                        f"SHORT stop {old:.{digits}f} → {new_stop:.{digits}f} "
                        f"(mult={new_state.stop_multiplier}x)"
                    )

        return new_state

    def check_stop_triggered(
        self,
        current_price: float,
        state:         TrailingStopState,
        position_type: PositionType,
    ) -> bool:
        if not state.enabled or state.stop_price is None:
            return False
        if position_type == PositionType.LONG:
            return current_price <= state.stop_price
        return current_price >= state.stop_price

    def distance_to_stop_percent(
        self,
        current_price: float,
        state:         TrailingStopState,
        position_type: PositionType,
    ) -> Optional[float]:
        if not state.enabled or state.stop_price is None or current_price <= 0:
            return None
        if position_type == PositionType.LONG:
            distance = (current_price - state.stop_price) / current_price * 100
        else:
            distance = (state.stop_price - current_price) / current_price * 100
        return max(0.0, distance)