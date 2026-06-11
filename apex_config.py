import math
from dataclasses import dataclass, field
from typing import Dict, Optional

import MetaTrader5 as mt5

# ═══════════════════════════════════════════════════════════════════════════
# ULTRA AGGRESSIVE CONFIGURATION 
# ═══════════════════════════════════════════════════════════════════════════

MAX_POSITION_SIZE_PCT = 0.85
MAX_MARGIN_USAGE_PCT = 0.60
MIN_POSITION_SIZE_PCT = 0.02
PORTFOLIO_RISK_TARGET = 0.75
ENTRY_THRESHOLD = 1.5


class TimeFrame:
    H1 = "H1"
    H4 = "H4"
    M15 = "M15"
    M5 = "M5"
    M1 = "M1"


TIMEFRAME_MAP = {
    TimeFrame.H1: mt5.TIMEFRAME_H1,
    TimeFrame.H4: mt5.TIMEFRAME_H4,
    TimeFrame.M15: mt5.TIMEFRAME_M15,
    TimeFrame.M5: mt5.TIMEFRAME_M5,
    TimeFrame.M1: mt5.TIMEFRAME_M1,
}

TIMEFRAME_META = {
    TimeFrame.H1: {
        "bars": 800,
        "candle_seconds": 3600,
        "cooldown": 300,
        "atr_scale": 1 / 24,
        "atr_multiplier": 24,
        "stop_multiplier": 1.8,
        "description": "1 Hour - Trend following",
    },
    TimeFrame.H4: {
        "bars": 400,
        "candle_seconds": 14400,
        "cooldown": 600,
        "atr_scale": 1 / 6,
        "atr_multiplier": 6,
        "stop_multiplier": 2.2,
        "description": "4 Hour - Swing trades",
    },
    TimeFrame.M15: {
        "bars": 1000,
        "candle_seconds": 900,
        "cooldown": 90,
        "atr_scale": 1 / 96,
        "atr_multiplier": 96,
        "stop_multiplier": 1.5,
        "description": "15 Min - Aggressive trend following",
    },
    TimeFrame.M5: {
        "bars": 1500,
        "candle_seconds": 300,
        "cooldown": 45,
        "atr_scale": 1 / 288,
        "atr_multiplier": 288,
        "stop_multiplier": 2.5,
        "description": "5 Min - Aggressive",
    },
    TimeFrame.M1: {
        "bars": 2000,
        "candle_seconds": 60,
        "cooldown": 15,
        "atr_scale": 1 / 1440,
        "atr_multiplier": 1440,
        "stop_multiplier": 4.0,
        "description": "1 Min - Ultra aggressive entries",
    },
}

MIN_BARS_FOR_ATR = 20
MIN_BARS_FOR_EWMAC = 100


@dataclass
class EWMACSpeed:
    fast: int
    slow: int
    weight: float = 0.25

    @property
    def scalar(self) -> float:
        return 20.0 / math.sqrt(self.fast)

    @property
    def name(self) -> str:
        return f"ewmac_{self.fast}_{self.slow}"


@dataclass
class StrategyConfig:
    ewmac_enabled: bool = True

    speeds: list = field(default_factory=lambda: [
        EWMACSpeed(fast=2, slow=8, weight=0.35),
        EWMACSpeed(fast=4, slow=16, weight=0.30),
        EWMACSpeed(fast=8, slow=32, weight=0.20),
        EWMACSpeed(fast=16, slow=64, weight=0.15),
    ])

    vol_lookback: int = 10
    cap_min: float = -50.0
    cap_max: float = +50.0
    fdm: float = 2.0
    entry_threshold: float = ENTRY_THRESHOLD
    idm: float = 3.5
    atr_period: int = 8


@dataclass
class SmartReentryConfig:
    enabled: bool = True
    cooldown_minutes: int = 15
    forecast_strength_required: float = 1.0
    max_consecutive_stops: int = 5
    size_reduction_enabled: bool = True
    size_reduction_factors: tuple = (0.5, 0.7, 0.85, 1.0)
    require_price_confirmation: bool = False
    price_confirmation_pct: float = 0.003
    atr_explosion_threshold: float = 3.0


@dataclass
class VolPositionSizingConfig:
    risk_target_pct: float = PORTFOLIO_RISK_TARGET
    expected_positions: int = 2
    MAX_IDM: float = 4.0
    MAX_RISK_TARGET: float = 0.85


@dataclass
class ATRTrailingConfig:
    enabled: bool = True
    multiple: Optional[float] = 4.0  
    atr_period: int = 8
    use_timeframe_multiple: bool = False


@dataclass
class BrokerSpec:
    symbol: str
    min_volume: float = 0.01
    max_volume: float = 500.0
    volume_step: float = 0.01
    contract_size: float = 1.0
    tick_size: float = 0.00001
    digits: int = 5
    margin_initial: float = 0.0
    tradeable: bool = True
    visible: bool = True

    @classmethod
    def from_mt5(cls, symbol: str) -> Optional["BrokerSpec"]:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return cls(
            symbol=symbol,
            min_volume=info.volume_min,
            max_volume=info.volume_max,
            volume_step=info.volume_step if info.volume_step > 0 else 0.01,
            contract_size=info.trade_contract_size,
            tick_size=info.point,
            digits=info.digits,
            margin_initial=info.margin_initial,
            tradeable=bool(info.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED),
            visible=bool(info.visible),
        )


@dataclass
class SymbolConfig:
    symbol: str
    enabled: bool = True
    primary_tf: str = TimeFrame.M1  
    max_positions: int = 1
    max_daily_trades: Optional[int] = 25 
    trading_days: int = 365

    min_volume: float = 0.01
    max_volume: float = 5.0
    volume_step: float = 0.01

    vol_target_pct: float = 0.0080

    broker_spec: Optional[BrokerSpec] = None


APEX_SYMBOLS: Dict[str, SymbolConfig] = {
    "BTCUSD": SymbolConfig(
        symbol="BTCUSD", enabled=True, primary_tf=TimeFrame.M1,
        trading_days=365, min_volume=0.01, max_volume=5.0, volume_step=0.01,
        vol_target_pct=0.0080, max_daily_trades=25
    ),
    "ETHUSD": SymbolConfig(
        symbol="ETHUSD", enabled=True, primary_tf=TimeFrame.M1,
        trading_days=365, min_volume=0.01, max_volume=10.0, volume_step=0.01,
        vol_target_pct=0.0080, max_daily_trades=25
    ),
}


@dataclass
class SystemConfig:
    symbols: Dict[str, SymbolConfig]
    strategy: StrategyConfig
    atr_trailing: ATRTrailingConfig
    vol_position_sizing: VolPositionSizingConfig
    smart_reentry: SmartReentryConfig = field(default_factory=SmartReentryConfig)
    poll_interval: int = 15
    magic_number: int = 999999
    enable_dashboard: bool = True
    log_to_file: bool = True
    max_retries: int = 3
    retry_delay: float = 0.5
    max_concurrent_positions: int = 2


def get_idm_for_instrument_count(num_instruments: int) -> float:
    if num_instruments >= 5:
        return 2.5
    elif num_instruments >= 3:
        return 3.0
    elif num_instruments == 2:
        return 3.5
    else:
        return 4.0


def get_recommended_risk_target(num_instruments: int) -> float:
    if num_instruments >= 8:
        return 0.45
    elif num_instruments >= 5:
        return 0.55
    elif num_instruments >= 3:
        return 0.65
    elif num_instruments == 2:
        return 0.75
    else:
        return 0.85


def load_apex_config() -> SystemConfig:
    symbols = APEX_SYMBOLS
    
    enabled_symbols = [sym for sym, cfg in symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)
    
    idm = get_idm_for_instrument_count(active_count)
    
    strategy_config = StrategyConfig()
    strategy_config.idm = idm
    strategy_config.entry_threshold = ENTRY_THRESHOLD
    
    return SystemConfig(
        symbols=symbols,
        strategy=strategy_config,
        atr_trailing=ATRTrailingConfig(
            enabled=True, 
            multiple=4.0,  
            atr_period=8,
            use_timeframe_multiple=False
        ),
        vol_position_sizing=VolPositionSizingConfig(
            risk_target_pct=PORTFOLIO_RISK_TARGET,
            expected_positions=active_count,
        ),
        smart_reentry=SmartReentryConfig(
            enabled=True,
            cooldown_minutes=15,
            forecast_strength_required=1.0,
            max_consecutive_stops=5,
            size_reduction_enabled=True,
            size_reduction_factors=(0.5, 0.7, 0.85, 1.0),
            require_price_confirmation=False,
        ),
        poll_interval=15,
        magic_number=999999,
        enable_dashboard=True,
        log_to_file=True,
        max_retries=3,
        retry_delay=0.5,
        max_concurrent_positions=2,
    )