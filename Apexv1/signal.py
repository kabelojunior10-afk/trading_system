from enum import Enum

class SignalType(Enum):
    BUY     = "BUY"
    SELL    = "SELL"
    NEUTRAL = "NEUTRAL"

    def __str__(self) -> str:
        return self.value

class PositionType(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    NONE  = "NONE"

    def __str__(self) -> str:
        return self.value