import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

import MetaTrader5 as mt5

# ═══════════════════════════════════════════════════════════════════════════
# AGGRESSIVE R250 CONFIGURATION - HIGH RISK / HIGH REWARD
# ═══════════════════════════════════════════════════════════════════════════

MAX_POSITION_SIZE_PCT = 0.50
MAX_MARGIN_USAGE_PCT = 0.25
MIN_POSITION_SIZE_PCT = 0.005
PORTFOLIO_RISK_TARGET = 0.35
ENTRY_THRESHOLD = 3.0

# ═══════════════════════════════════════════════════════════════════════════
# Timeframe definitions
# ═══════════════════════════════════════════════════════════════════════════

class TimeFrame:
    H1 = "H1"
    H4 = "H4"
    M15 = "M15"

TIMEFRAME_MAP = {
    TimeFrame.H1: mt5.TIMEFRAME_H1,
    TimeFrame.H4: mt5.TIMEFRAME_H4,
    TimeFrame.M15: mt5.TIMEFRAME_M15,
}

TIMEFRAME_META = {
    TimeFrame.H1: {
        "bars": 800,
        "candle_seconds": 3600,
        "cooldown": 300,
        "atr_scale": 1 / 24,
        "atr_multiplier": 24,
        "stop_multiplier": 2.5,
        "description": "1 Hour - Trend following",
    },
    TimeFrame.H4: {
        "bars": 400,
        "candle_seconds": 14400,
        "cooldown": 600,
        "atr_scale": 1 / 6,
        "atr_multiplier": 6,
        "stop_multiplier": 3.0,
        "description": "4 Hour - Swing trades",
    },
    TimeFrame.M15: {
        "bars": 1000,
        "candle_seconds": 900,
        "cooldown": 150,
        "atr_scale": 1 / 96,
        "atr_multiplier": 96,
        "stop_multiplier": 2.0,
        "description": "15 Min - Aggressive trend following",
    },
}

MIN_BARS_FOR_ATR = 30
MIN_BARS_FOR_EWMAC = 200

# ═══════════════════════════════════════════════════════════════════════════
# EWMAC speed definition
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EWMACSpeed:
    fast:   int
    slow:   int
    weight: float = 0.25

    @property
    def scalar(self) -> float:
        return 15.0 / math.sqrt(self.fast)

    @property
    def name(self) -> str:
        return f"ewmac_{self.fast}_{self.slow}"

# ═══════════════════════════════════════════════════════════════════════════
# Strategy configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyConfig:
    ewmac_enabled: bool = True

    speeds: List[EWMACSpeed] = field(default_factory=lambda: [
        EWMACSpeed(fast=4,  slow=16,  weight=0.30),
        EWMACSpeed(fast=8,  slow=32,  weight=0.25),
        EWMACSpeed(fast=16, slow=64,  weight=0.25),
        EWMACSpeed(fast=32, slow=128, weight=0.20),
    ])

    vol_lookback: int = 15
    cap_min: float = -30.0
    cap_max: float = +30.0
    fdm: float = 1.5
    entry_threshold: float = ENTRY_THRESHOLD
    idm: float = 2.0
    atr_period: int = 10

# ═══════════════════════════════════════════════════════════════════════════
# Smart Re-entry Configuration (NEW)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SmartReentryConfig:
    enabled: bool = True
    cooldown_minutes: int = 30  # Wait 30 min after stop before re-entering
    forecast_strength_required: float = 1.2  # Need 20% stronger forecast
    max_consecutive_stops: int = 3  # Max stops before pausing
    size_reduction_enabled: bool = True
    size_reduction_factors: tuple = (0.3, 0.5, 0.7, 1.0)  # Per time window
    require_price_confirmation: bool = True
    price_confirmation_pct: float = 0.005  # 0.5% beyond stop
    atr_explosion_threshold: float = 2.0  # Don't re-enter if ATR > 2x

# ═══════════════════════════════════════════════════════════════════════════
# Volatility Position Sizing Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VolPositionSizingConfig:
    risk_target_pct: float = PORTFOLIO_RISK_TARGET
    expected_positions: int = 3
    MAX_IDM: float = 3.0
    MAX_RISK_TARGET: float = 0.45

# ═══════════════════════════════════════════════════════════════════════════
# ATR Trailing Stop Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ATRTrailingConfig:
    enabled:    bool  = True
    multiple:   Optional[float] = 2.5
    atr_period: int   = 10
    use_timeframe_multiple: bool = False

# ═══════════════════════════════════════════════════════════════════════════
# Broker spec – populated at runtime from MT5 symbol info
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BrokerSpec:
    symbol:         str
    min_volume:     float = 0.01
    max_volume:     float = 500.0
    volume_step:    float = 0.01
    contract_size:  float = 1.0
    tick_size:      float = 0.00001
    digits:         int   = 5
    margin_initial: float = 0.0
    tradeable:      bool  = True
    visible:        bool  = True

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

# ═══════════════════════════════════════════════════════════════════════════
# Per-symbol configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SymbolConfig:
    symbol:          str
    enabled:         bool          = True
    primary_tf:      str           = TimeFrame.M15
    max_positions:   int           = 1
    max_daily_trades: Optional[int] = 5
    trading_days:    int           = 365

    min_volume: float = 0.01
    max_volume: float = 500.0
    volume_step: float = 0.01

    vol_target_pct: float = 0.0040

    broker_spec: Optional[BrokerSpec] = None

# ═══════════════════════════════════════════════════════════════════════════
# AGGRESSIVE SYMBOL LIST
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_SYMBOLS: Dict[str, SymbolConfig] = {
    "BTCUSD": SymbolConfig(
        symbol="BTCUSD", enabled=True, primary_tf=TimeFrame.M15,
        trading_days=365, min_volume=0.01, max_volume=1.0, volume_step=0.01,
        vol_target_pct=0.0045, max_daily_trades=5
    ),
    
    "ETHUSD": SymbolConfig(
        symbol="ETHUSD", enabled=True, primary_tf=TimeFrame.M15,
        trading_days=365, min_volume=0.01, max_volume=3.0, volume_step=0.01,
        vol_target_pct=0.0050, max_daily_trades=5
    ),
    
    "SOLUSD": SymbolConfig(
        symbol="SOLUSD", enabled=True, primary_tf=TimeFrame.M15,
        trading_days=365, min_volume=0.01, max_volume=2.0, volume_step=0.01,
        vol_target_pct=0.0055, max_daily_trades=5
    ),
    
    "LTCUSD": SymbolConfig(symbol="LTCUSD", enabled=False),
    "BNBUSD": SymbolConfig(symbol="BNBUSD", enabled=False),
    "BCHUSD": SymbolConfig(symbol="BCHUSD", enabled=False),
    "LINKUSD": SymbolConfig(symbol="LINKUSD", enabled=False),
    "AVAXUSD": SymbolConfig(symbol="AVAXUSD", enabled=False),
    "TRUMPUSD": SymbolConfig(symbol="TRUMPUSD", enabled=False),
    "XRPUSD": SymbolConfig(symbol="XRPUSD", enabled=False),
    "ADAUSD": SymbolConfig(symbol="ADAUSD", enabled=False),
    "DOTUSD": SymbolConfig(symbol="DOTUSD", enabled=False),
    "XLMUSD": SymbolConfig(symbol="XLMUSD", enabled=False),
    "DOGEUSD": SymbolConfig(symbol="DOGEUSD", enabled=False),
    "UNIUSD": SymbolConfig(symbol="UNIUSD", enabled=False),
    "ATOMUSD": SymbolConfig(symbol="ATOMUSD", enabled=False),
    "AAVEUSD": SymbolConfig(symbol="AAVEUSD", enabled=False),
    "HBARUSD": SymbolConfig(symbol="HBARUSD", enabled=False),
    "HYPEUSD": SymbolConfig(symbol="HYPEUSD", enabled=False),
    "ICPUSD": SymbolConfig(symbol="ICPUSD", enabled=False),
    "NEARUSD": SymbolConfig(symbol="NEARUSD", enabled=False),
    "SUIUSD": SymbolConfig(symbol="SUIUSD", enabled=False),
    "TAOUSD": SymbolConfig(symbol="TAOUSD", enabled=False),
    "TONUSD": SymbolConfig(symbol="TONUSD", enabled=False),
    "TRXUSD": SymbolConfig(symbol="TRXUSD", enabled=False),
    "WLFIUSD": SymbolConfig(symbol="WLFIUSD", enabled=False),
    "XMRUSD": SymbolConfig(symbol="XMRUSD", enabled=False),
    "ZECUSD": SymbolConfig(symbol="ZECUSD", enabled=False),
}

# ═══════════════════════════════════════════════════════════════════════════
# Top-level system configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SystemConfig:
    symbols:             Dict[str, SymbolConfig]
    strategy:            StrategyConfig
    atr_trailing:        ATRTrailingConfig
    vol_position_sizing: VolPositionSizingConfig
    smart_reentry:       SmartReentryConfig = field(default_factory=SmartReentryConfig)  # NEW
    poll_interval:       int   = 30
    magic_number:        int   = 654321
    enable_dashboard:    bool  = True
    log_to_file:         bool  = True
    max_retries:         int   = 3
    retry_delay:         float = 1.0
    max_concurrent_positions: int = 3

# ═══════════════════════════════════════════════════════════════════════════
# IDM table
# ═══════════════════════════════════════════════════════════════════════════

def get_idm_for_instrument_count(num_instruments: int) -> float:
    if num_instruments >= 30:
        return 1.80
    elif num_instruments >= 25:
        return 1.85
    elif num_instruments >= 15:
        return 1.90
    elif num_instruments >= 8:
        return 1.95
    elif num_instruments >= 7:
        return 1.96
    elif num_instruments >= 6:
        return 1.97
    elif num_instruments >= 5:
        return 1.98
    elif num_instruments >= 4:
        return 1.99
    elif num_instruments >= 3:
        return 2.00
    elif num_instruments >= 2:
        return 2.00
    else:
        return 1.50

def get_recommended_risk_target(num_instruments: int) -> float:
    if num_instruments >= 16:
        return 0.25
    elif num_instruments >= 12:
        return 0.28
    elif num_instruments >= 8:
        return 0.30
    elif num_instruments >= 5:
        return 0.32
    elif num_instruments >= 3:
        return 0.35
    elif num_instruments >= 2:
        return 0.38
    else:
        return 0.40

def load_config(custom_symbols: Optional[Dict[str, SymbolConfig]] = None) -> SystemConfig:
    symbols = custom_symbols or DEFAULT_SYMBOLS
    
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
            multiple=2.5,
            atr_period=10,
            use_timeframe_multiple=False
        ),
        vol_position_sizing=VolPositionSizingConfig(
            risk_target_pct=PORTFOLIO_RISK_TARGET,
            expected_positions=active_count,
        ),
        smart_reentry=SmartReentryConfig(),  # NEW
        poll_interval=30,
        magic_number=654321,
        enable_dashboard=True,
        log_to_file=True,
        max_retries=3,
        retry_delay=1.0,
        max_concurrent_positions=3,
    )