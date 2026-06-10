from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from signal import SignalType, PositionType

@dataclass
class Trade:
    ticket:         int
    symbol:         str
    signal_type:    SignalType
    position_type:  PositionType
    entry_price:    float
    entry_time:     datetime
    volume:         float
    exit_price:     Optional[float] = None
    exit_time:      Optional[datetime] = None
    profit:         Optional[float] = None
    strategy:       str = "MultiEWMAC_VolSizer"
    entry_atr:      Optional[float] = None
    initial_stop:   Optional[float] = None
    stop_multiplier: Optional[float] = None
    timeframe:      Optional[str] = None

@dataclass
class SignalData:
    signal:    SignalType
    forecast:  float
    trend:     str
    timestamp: datetime

@dataclass
class PositionState:
    has_position:    bool
    position_type:   Optional[PositionType]
    ticket:          Optional[int]
    entry_price:     Optional[float]
    volume:          Optional[float]
    unrealized_pnl:  float = 0.0
    trailing_stop_enabled: bool = False
    trailing_stop_price:   Optional[float] = None
    entry_atr:       Optional[float] = None
    stop_multiplier: Optional[float] = None
    timeframe:       Optional[str] = None
    highest_price_since_entry: Optional[float] = None
    lowest_price_since_entry:  Optional[float] = None
    initial_stop:    Optional[float] = None

    @classmethod
    def empty(cls) -> "PositionState":
        return cls(
            has_position=False, position_type=None, ticket=None,
            entry_price=None, volume=None, unrealized_pnl=0.0,
            trailing_stop_enabled=False, trailing_stop_price=None,
            entry_atr=None, stop_multiplier=None, timeframe=None,
            highest_price_since_entry=None, lowest_price_since_entry=None,
            initial_stop=None,
        )

    @classmethod
    def from_trade(cls, trade: "Trade", atr_enabled: bool = True) -> "PositionState":
        return cls(
            has_position=True,
            position_type=trade.position_type,
            ticket=trade.ticket,
            entry_price=trade.entry_price,
            volume=trade.volume,
            unrealized_pnl=0.0,
            trailing_stop_enabled=atr_enabled,
            trailing_stop_price=trade.initial_stop if atr_enabled else None,
            entry_atr=trade.entry_atr,
            stop_multiplier=trade.stop_multiplier,
            timeframe=trade.timeframe,
            highest_price_since_entry=(
                trade.entry_price
                if trade.position_type == PositionType.LONG
                else None
            ),
            lowest_price_since_entry=(
                trade.entry_price
                if trade.position_type == PositionType.SHORT
                else None
            ),
            initial_stop=trade.initial_stop,
        )