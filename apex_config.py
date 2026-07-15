# apex_config.py
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

import MetaTrader5 as mt5

# ═══════════════════════════════════════════════════════════════════════════
# ULTRA AGGRESSIVE CONFIGURATION - H1 TIMEFRAME - HIGHER RISK
# ═══════════════════════════════════════════════════════════════════════════

MAX_POSITION_SIZE_PCT = 0.95
MAX_MARGIN_USAGE_PCT = 0.75
MIN_POSITION_SIZE_PCT = 0.02
PORTFOLIO_RISK_TARGET = 0.90
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
        "bars": 1500,  # Increased to support breakout 1280 periods
        "candle_seconds": 3600,
        "cooldown": 300,
        "atr_scale": 1 / 24,
        "atr_multiplier": 24,
        "stop_multiplier": 2.2,
        "description": "1 Hour - Trend following + Breakout",
    },
    TimeFrame.H4: {
        "bars": 800,
        "candle_seconds": 14400,
        "cooldown": 600,
        "atr_scale": 1 / 6,
        "atr_multiplier": 6,
        "stop_multiplier": 2.2,
        "description": "4 Hour - Swing trades",
    },
    TimeFrame.M15: {
        "bars": 1500,
        "candle_seconds": 900,
        "cooldown": 90,
        "atr_scale": 1 / 96,
        "atr_multiplier": 96,
        "stop_multiplier": 2.5,     
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
    breakout_enabled: bool = True

    # EWMAC speeds for H1
    speeds: list = field(default_factory=lambda: [
        EWMACSpeed(fast=8,  slow=32,  weight=0.35),
        EWMACSpeed(fast=16, slow=64,  weight=0.30),
        EWMACSpeed(fast=32, slow=128, weight=0.20),
        EWMACSpeed(fast=64, slow=256, weight=0.15),
    ])

    # Breakout configuration
    breakout_weight: float = 0.40
    ewmac_weight: float = 0.60

    vol_lookback: int = 20
    cap_min: float = -50.0
    cap_max: float = +50.0
    fdm: float = 2.0
    entry_threshold: float = ENTRY_THRESHOLD
    idm: float = 4.5
    atr_period: int = 14


@dataclass
class SmartReentryConfig:
    enabled: bool = True
    cooldown_minutes: int = 30
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
    MAX_IDM: float = 5.0
    MAX_RISK_TARGET: float = 0.95


@dataclass
class ATRTrailingConfig:
    enabled: bool = True
    multiple: Optional[float] = 2.2
    atr_period: int = 14
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
    primary_tf: str = TimeFrame.H1
    max_positions: int = 1
    max_daily_trades: Optional[int] = 8
    trading_days: int = 365

    min_volume: float = 0.01
    max_volume: float = 10.0
    volume_step: float = 0.01

    vol_target_pct: float = 0.0100

    broker_spec: Optional[BrokerSpec] = None


# ═══════════════════════════════════════════════════════════════════════════
# SYMBOL CONFIGURATION - ONLY BTCUSD AND ETHUSD ENABLED
# ═══════════════════════════════════════════════════════════════════════════

APEX_SYMBOLS: Dict[str, SymbolConfig] = {
    # ═══ PRIMARY SYMBOLS - ENABLED ═══
    "BTCUSD": SymbolConfig(
        symbol="BTCUSD", enabled=True, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.01, max_volume=10.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "ETHUSD": SymbolConfig(
        symbol="ETHUSD", enabled=True, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.01, max_volume=20.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    
    # ═══ ALL OTHER SYMBOLS - DISABLED ═══
    "SOLUSD": SymbolConfig(
        symbol="SOLUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "LTCUSD": SymbolConfig(
        symbol="LTCUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=500.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "BCHUSD": SymbolConfig(
        symbol="BCHUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=500.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "BNBUSD": SymbolConfig(
        symbol="BNBUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=10.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "AVAXUSD": SymbolConfig(
        symbol="AVAXUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=1.0, max_volume=100.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "LINKUSD": SymbolConfig(
        symbol="LINKUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=1.0, max_volume=100.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "DOTUSD": SymbolConfig(
        symbol="DOTUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "ATOMUSD": SymbolConfig(
        symbol="ATOMUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "UNIUSD": SymbolConfig(
        symbol="UNIUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "XRPUSD": SymbolConfig(
        symbol="XRPUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "ADAUSD": SymbolConfig(
        symbol="ADAUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "XLMUSD": SymbolConfig(
        symbol="XLMUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "DOGEUSD": SymbolConfig(
        symbol="DOGEUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "XTZUSD": SymbolConfig(
        symbol="XTZUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=100.0, max_volume=2000.0, volume_step=1.0,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "AAVEUSD": SymbolConfig(
        symbol="AAVEUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=1.0, max_volume=100.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "HBARUSD": SymbolConfig(
        symbol="HBARUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=10.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "NEARUSD": SymbolConfig(
        symbol="NEARUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=100.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
    "SUIUSD": SymbolConfig(
        symbol="SUIUSD", enabled=False, primary_tf=TimeFrame.H1,
        trading_days=365, min_volume=0.1, max_volume=100.0, volume_step=0.01,
        vol_target_pct=0.0100, max_daily_trades=8
    ),
}


@dataclass
class SystemConfig:
    symbols: Dict[str, SymbolConfig]
    strategy: StrategyConfig
    atr_trailing: ATRTrailingConfig
    vol_position_sizing: VolPositionSizingConfig
    smart_reentry: SmartReentryConfig = field(default_factory=SmartReentryConfig)
    poll_interval: int = 30
    magic_number: int = 999999
    enable_dashboard: bool = True
    log_to_file: bool = True
    max_retries: int = 3
    retry_delay: float = 0.5
    max_concurrent_positions: int = 30


def get_idm_for_instrument_count(num_instruments: int) -> float:
    """Higher IDM for H1 to increase risk."""
    if num_instruments >= 15:
        return 2.0
    elif num_instruments >= 10:
        return 2.75
    elif num_instruments >= 7:
        return 3.5
    elif num_instruments >= 5:
        return 4.25
    elif num_instruments >= 3:
        return 4.75
    elif num_instruments >= 2:
        return 5.0
    else:
        return 5.0


def get_recommended_risk_target(num_instruments: int) -> float:
    """Higher risk targets for H1."""
    if num_instruments >= 15:
        return 0.45
    elif num_instruments >= 10:
        return 0.55
    elif num_instruments >= 7:
        return 0.65
    elif num_instruments >= 5:
        return 0.75
    elif num_instruments >= 3:
        return 0.85
    elif num_instruments == 2:
        return 0.90
    else:
        return 0.95


def load_apex_config() -> SystemConfig:
    symbols = APEX_SYMBOLS

    enabled_symbols = [sym for sym, cfg in symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)

    idm = get_idm_for_instrument_count(active_count)

    strategy_config = StrategyConfig()
    strategy_config.idm = idm
    strategy_config.entry_threshold = ENTRY_THRESHOLD
    strategy_config.breakout_enabled = True
    strategy_config.breakout_weight = 0.40
    strategy_config.ewmac_weight = 0.60

    return SystemConfig(
        symbols=symbols,
        strategy=strategy_config,
        atr_trailing=ATRTrailingConfig(
            enabled=True,
            multiple=2.2,
            atr_period=14,
            use_timeframe_multiple=False
        ),
        vol_position_sizing=VolPositionSizingConfig(
            risk_target_pct=PORTFOLIO_RISK_TARGET,
            expected_positions=active_count,
        ),
        smart_reentry=SmartReentryConfig(
            enabled=True,
            cooldown_minutes=30,
            forecast_strength_required=1.0,
            max_consecutive_stops=5,
            size_reduction_enabled=True,
            size_reduction_factors=(0.5, 0.7, 0.85, 1.0),
            require_price_confirmation=False,
        ),
        poll_interval=30,
        magic_number=999999,
        enable_dashboard=True,
        log_to_file=True,
        max_retries=3,
        retry_delay=0.5,
        max_concurrent_positions=30,
    )