import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

import MetaTrader5 as mt5

MAX_POSITION_SIZE_PCT = 0.20

MAX_MARGIN_USAGE_PCT = 0.10

MIN_POSITION_SIZE_PCT = 0.001

PORTFOLIO_RISK_TARGET = 0.12

ENTRY_THRESHOLD = 7.0

EXIT_THRESHOLD = 3.0

# ═══════════════════════════════════════════════════════════════════════════
# Timeframe definitions
# ═══════════════════════════════════════════════════════════════════════════

class TimeFrame:
    H1 = "H1"

TIMEFRAME_MAP = {
    TimeFrame.H1: mt5.TIMEFRAME_H1,
}

TIMEFRAME_META = {
    TimeFrame.H1: {
        "bars": 800,
        "candle_seconds": 3600,
        "cooldown": 300,
        "atr_scale": 1 / 24,
        "atr_multiplier": 24,
        "stop_multiplier": 4.0,
        "description": "1 Hour - Crypto trend following",
    },
}

MIN_BARS_FOR_ATR = 50
MIN_BARS_FOR_EWMAC = 300

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
        return 10.0 / math.sqrt(self.fast)

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
        EWMACSpeed(fast=8,  slow=32,  weight=0.25),
        EWMACSpeed(fast=16, slow=64,  weight=0.25),
        EWMACSpeed(fast=32, slow=128, weight=0.25),
        EWMACSpeed(fast=64, slow=256, weight=0.25),
    ])

    vol_lookback: int = 25
    cap_min: float = -20.0
    cap_max: float = +20.0
    fdm: float = 1.13
    entry_threshold: float = ENTRY_THRESHOLD
    exit_threshold: float = EXIT_THRESHOLD
    idm: float = 1.15
    atr_period: int = 14

# ═══════════════════════════════════════════════════════════════════════════
# Volatility Position Sizing Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class VolPositionSizingConfig:
    risk_target_pct: float = PORTFOLIO_RISK_TARGET
    expected_positions: int = 27
    MAX_IDM: float = 2.5
    MAX_RISK_TARGET: float = 0.25

# ═══════════════════════════════════════════════════════════════════════════
# ATR Trailing Stop Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ATRTrailingConfig:
    enabled:    bool  = True
    multiple:   Optional[float] = None
    atr_period: int   = 14
    use_timeframe_multiple: bool = True

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
    primary_tf:      str           = TimeFrame.H1
    max_positions:   int           = 1
    max_daily_trades: Optional[int] = None
    trading_days:    int           = 365

    min_volume: float = 0.01
    max_volume: float = 500.0
    volume_step: float = 0.01

    vol_target_pct: float = 0.0025

    broker_spec: Optional[BrokerSpec] = None

# ═══════════════════════════════════════════════════════════════════════════
# Default symbol list - ALL SYMBOLS WITH CORRECT VOLUME LIMITS
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_SYMBOLS: Dict[str, SymbolConfig] = {
    # Major coins
    "BTCUSD": SymbolConfig(symbol="BTCUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.01, max_volume=5.0, volume_step=0.01,
                          vol_target_pct=0.0015),
    
    "ETHUSD": SymbolConfig(symbol="ETHUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=100.0, volume_step=0.1,
                          vol_target_pct=0.0018),
    
    "SOLUSD": SymbolConfig(symbol="SOLUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=20.0, volume_step=0.1,
                          vol_target_pct=0.0025),
    
    "LTCUSD": SymbolConfig(symbol="LTCUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=200.0, volume_step=0.1,
                          vol_target_pct=0.0025),
    
    "BNBUSD": SymbolConfig(symbol="BNBUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=5.0, volume_step=0.1,
                          vol_target_pct=0.0022),
    
    "BCHUSD": SymbolConfig(symbol="BCHUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=200.0, volume_step=0.1,
                          vol_target_pct=0.0028),
    
    "LINKUSD": SymbolConfig(symbol="LINKUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=1.0, max_volume=50.0, volume_step=1.0,
                           vol_target_pct=0.0028),
    
    "AVAXUSD": SymbolConfig(symbol="AVAXUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=1.0, max_volume=50.0, volume_step=1.0,
                           vol_target_pct=0.0028),
    
    "TRUMPUSD": SymbolConfig(symbol="TRUMPUSD", enabled=True, primary_tf=TimeFrame.H1,
                            trading_days=365, min_volume=1.0, max_volume=50.0, volume_step=1.0,
                            vol_target_pct=0.0030),
    
    "XRPUSD": SymbolConfig(symbol="XRPUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=1.0,
                          vol_target_pct=0.0025),
    
    "ADAUSD": SymbolConfig(symbol="ADAUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=100.0,
                          vol_target_pct=0.0015),
    
    "DOTUSD": SymbolConfig(symbol="DOTUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=1.0,
                          vol_target_pct=0.0028),
    
    "XLMUSD": SymbolConfig(symbol="XLMUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=100.0,
                          vol_target_pct=0.0025),
    
    "DOGEUSD": SymbolConfig(symbol="DOGEUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=100.0,
                           vol_target_pct=0.0028),
    
    "UNIUSD": SymbolConfig(symbol="UNIUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=100.0,
                          vol_target_pct=0.0028),
    
    "ATOMUSD": SymbolConfig(symbol="ATOMUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=100.0, max_volume=1000.0, volume_step=100.0,
                           vol_target_pct=0.0028),
    
    "AAVEUSD": SymbolConfig(symbol="AAVEUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=1.0, max_volume=50.0, volume_step=1.0,
                           vol_target_pct=0.0028),
    
    "HBARUSD": SymbolConfig(symbol="HBARUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=0.1, max_volume=5.0, volume_step=0.1,
                           vol_target_pct=0.0030),
    
    "HYPEUSD": SymbolConfig(symbol="HYPEUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=0.1, max_volume=5.0, volume_step=0.1,
                           vol_target_pct=0.0030),
    
    "ICPUSD": SymbolConfig(symbol="ICPUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=5.0, volume_step=0.1,
                          vol_target_pct=0.0030),
    
    "NEARUSD": SymbolConfig(symbol="NEARUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.1,
                           vol_target_pct=0.0028),
    
    "SUIUSD": SymbolConfig(symbol="SUIUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.1,
                          vol_target_pct=0.0030),
    
    "TAOUSD": SymbolConfig(symbol="TAOUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.1,
                          vol_target_pct=0.0030),
    
    "TONUSD": SymbolConfig(symbol="TONUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=5.0, volume_step=0.1,
                          vol_target_pct=0.0028),
    
    "TRXUSD": SymbolConfig(symbol="TRXUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.1,
                          vol_target_pct=0.0025),
    
    "WLFIUSD": SymbolConfig(symbol="WLFIUSD", enabled=True, primary_tf=TimeFrame.H1,
                           trading_days=365, min_volume=0.1, max_volume=50.0, volume_step=0.1,
                           vol_target_pct=0.0030),
    
    "XMRUSD": SymbolConfig(symbol="XMRUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=1.0, max_volume=5.0, volume_step=1.0,
                          vol_target_pct=0.0025),
    
    "ZECUSD": SymbolConfig(symbol="ZECUSD", enabled=True, primary_tf=TimeFrame.H1,
                          trading_days=365, min_volume=1.0, max_volume=5.0, volume_step=1.0,
                          vol_target_pct=0.0028),
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
    poll_interval:       int   = 60
    magic_number:        int   = 654321
    enable_dashboard:    bool  = True
    log_to_file:         bool  = True
    max_retries:         int   = 3
    retry_delay:         float = 1.5
    max_concurrent_positions: int = 9999

# ═══════════════════════════════════════════════════════════════════════════
# IDM table
# ═══════════════════════════════════════════════════════════════════════════

def get_idm_for_instrument_count(num_instruments: int) -> float:
    """Crypto-only IDM table (single-asset-class values)."""
    if num_instruments >= 30:
        return 1.40
    elif num_instruments >= 25:
        return 1.38
    elif num_instruments >= 15:
        return 1.36
    elif num_instruments >= 8:
        return 1.34
    elif num_instruments >= 7:
        return 1.32
    elif num_instruments >= 6:
        return 1.31
    elif num_instruments >= 5:
        return 1.29
    elif num_instruments >= 4:
        return 1.27
    elif num_instruments >= 3:
        return 1.22
    elif num_instruments >= 2:
        return 1.15
    else:
        return 1.00

def get_recommended_risk_target(num_instruments: int) -> float:
    """Crypto-only recommended annual risk target."""
    if num_instruments >= 16:
        return 0.18
    elif num_instruments >= 12:
        return 0.17
    elif num_instruments >= 8:
        return 0.16
    elif num_instruments >= 5:
        return 0.15
    elif num_instruments >= 3:
        return 0.14
    elif num_instruments >= 2:
        return 0.13
    else:
        return 0.12

def load_config(custom_symbols: Optional[Dict[str, SymbolConfig]] = None) -> SystemConfig:
    """Load configuration."""
    symbols = custom_symbols or DEFAULT_SYMBOLS
    
    enabled_symbols = [sym for sym, cfg in symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)
    
    idm = get_idm_for_instrument_count(active_count)
    
    strategy_config = StrategyConfig()
    strategy_config.idm = idm
    
    return SystemConfig(
        symbols=symbols,
        strategy=strategy_config,
        atr_trailing=ATRTrailingConfig(enabled=True, multiple=None, use_timeframe_multiple=True),
        vol_position_sizing=VolPositionSizingConfig(
            risk_target_pct=PORTFOLIO_RISK_TARGET,
            expected_positions=active_count,
        ),
        poll_interval=60,
        magic_number=654321,
        enable_dashboard=True,
        log_to_file=True,
        max_retries=3,
        retry_delay=1.5,
        max_concurrent_positions=9999,
    )