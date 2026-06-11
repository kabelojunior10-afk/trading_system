# apex_data_provider.py
import logging
from typing import Tuple

import MetaTrader5 as mt5
import pandas as pd

from apex_config import TIMEFRAME_MAP

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 100


class ApexDataProvider:

    def validate_symbol(self, symbol: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False, f"Symbol '{symbol}' not found on broker"

        if not info.visible:
            logger.info(f"ApexDataProvider: selecting {symbol} in Market Watch")
            if not mt5.symbol_select(symbol, True):
                return False, f"Cannot select '{symbol}' in Market Watch"

        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"'{symbol}' is disabled for trading on this broker"

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.bid == 0:
            return False, f"No market data (tick) available for '{symbol}'"

        return True, ""

    def get_historical_data(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
    ) -> pd.DataFrame:
        mt5_tf = TIMEFRAME_MAP.get(timeframe)
        if mt5_tf is None:
            logger.error(f"ApexDataProvider [{symbol}]: unknown timeframe '{timeframe}'")
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)

        if rates is None:
            err = mt5.last_error()
            logger.warning(f"ApexDataProvider [{symbol}] {timeframe}: MT5 returned None. Error: {err}")
            return pd.DataFrame()

        if len(rates) == 0:
            logger.warning(f"ApexDataProvider [{symbol}] {timeframe}: 0 bars returned")
            return pd.DataFrame()

        if len(rates) < MIN_BARS_REQUIRED:
            logger.warning(f"ApexDataProvider [{symbol}] {timeframe}: only {len(rates)} bars (need ≥{MIN_BARS_REQUIRED})")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            logger.error(f"ApexDataProvider [{symbol}]: DataFrame missing columns: {missing}")
            return pd.DataFrame()

        logger.debug(f"ApexDataProvider [{symbol}] {timeframe}: {len(df)} bars loaded")
        return df