import logging
from typing import Tuple

import MetaTrader5 as mt5
import pandas as pd

from config import TIMEFRAME_MAP

logger = logging.getLogger(__name__)

MIN_BARS_REQUIRED = 300

class DataProvider:

    def validate_symbol(self, symbol: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False, f"Symbol '{symbol}' not found on broker"

        if not info.visible:
            logger.info(f"DataProvider: selecting {symbol} in Market Watch")
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
        symbol:    str,
        timeframe: str,
        bars:      int,
    ) -> pd.DataFrame:
        mt5_tf = TIMEFRAME_MAP.get(timeframe)
        if mt5_tf is None:
            logger.error(
                f"DataProvider [{symbol}]: unknown timeframe '{timeframe}'. "
                f"Valid options: {list(TIMEFRAME_MAP.keys())}"
            )
            return pd.DataFrame()

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)

        if rates is None:
            err = mt5.last_error()
            logger.warning(
                f"DataProvider [{symbol}] {timeframe}: MT5 returned None. "
                f"MT5 error: {err}."
            )
            return pd.DataFrame()

        if len(rates) == 0:
            logger.warning(
                f"DataProvider [{symbol}] {timeframe}: 0 bars returned."
            )
            return pd.DataFrame()

        if len(rates) < MIN_BARS_REQUIRED:
            logger.warning(
                f"DataProvider [{symbol}] {timeframe}: only {len(rates)} bars "
                f"(need ≥{MIN_BARS_REQUIRED}). Results may be unreliable."
            )

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)

        required = {"open", "high", "low", "close", "volume"}
        missing  = required - set(df.columns)
        if missing:
            logger.error(
                f"DataProvider [{symbol}]: DataFrame missing columns: {missing}"
            )
            return pd.DataFrame()

        logger.debug(
            f"DataProvider [{symbol}] {timeframe}: {len(df)} bars loaded "
            f"({df.index[0]} → {df.index[-1]})"
        )
        return df