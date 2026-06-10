import logging
import math
import time
from typing import Optional

import MetaTrader5 as mt5

from config import SymbolConfig, StrategyConfig, get_idm_for_instrument_count

logger = logging.getLogger(__name__)

MAX_MARGIN_FRACTION   = 0.10   
MAX_NOTIONAL_FRACTION = 0.20   
MIN_VOLUME_FRACTION   = 0.001  

MAX_ANNUAL_VOL = 2.5  
MIN_ANNUAL_VOL = 0.30  


class VolatilityPositionSizer:

    def __init__(self, strat_cfg: StrategyConfig, vol_sizing_cfg, active_symbols_count: int):
        self.strat_cfg        = strat_cfg
        self.vol_sizing_cfg   = vol_sizing_cfg
        self.expected_positions = vol_sizing_cfg.expected_positions
        self.idm              = get_idm_for_instrument_count(active_symbols_count)
        self._usd_zar_rate    = None
        self._last_rate_time  = 0

        logger.info(
            f"VolatilityPositionSizer | N={self.expected_positions} | IDM={self.idm:.2f}"
        )

    def get_usd_to_zar_rate(self) -> float:
        current_time = time.time()

        if self._usd_zar_rate is not None and (current_time - self._last_rate_time) < 5:
            return self._usd_zar_rate

        try:
            usd_zar_info = mt5.symbol_info("USDZAR")
            if usd_zar_info:
                tick = mt5.symbol_info_tick("USDZAR")
                if tick and tick.bid > 0:
                    self._usd_zar_rate  = tick.bid
                    self._last_rate_time = current_time
                    logger.debug(f"USD/ZAR live rate: {self._usd_zar_rate:.4f}")
                    return self._usd_zar_rate

            eurusd = mt5.symbol_info_tick("EURUSD")
            eurzar = mt5.symbol_info_tick("EURZAR")
            if eurusd and eurzar and eurusd.bid > 0 and eurzar.bid > 0:
                self._usd_zar_rate  = eurzar.bid / eurusd.bid
                self._last_rate_time = current_time
                logger.debug(f"USD/ZAR derived rate: {self._usd_zar_rate:.4f}")
                return self._usd_zar_rate

            self._usd_zar_rate  = 18.5
            self._last_rate_time = current_time
            logger.warning("Using default USD/ZAR rate 18.5")
            return 18.5
        except Exception as e:
            logger.error(f"Error getting USD/ZAR rate: {e}")
            return 18.5

    def calculate_notional_exposure(
        self, balance_zar: float, annual_vol: float, forecast: float
    ) -> float:
        N       = max(self.expected_positions, 1)
        Capital = balance_zar
        T       = self.vol_sizing_cfg.risk_target_pct
        V       = annual_vol if annual_vol > 0 else 0.01
        F       = min(abs(forecast), 20.0)
        IDM     = self.idm

        notional_zar = (1.0 / N) * Capital * (T / V) * (F / 10.0) * IDM

        max_notional_zar = Capital * MAX_NOTIONAL_FRACTION
        min_notional_zar = Capital * MIN_VOLUME_FRACTION

        notional_zar = min(notional_zar, max_notional_zar)
        notional_zar = max(notional_zar, min_notional_zar)
        return notional_zar

    def annual_vol_from_atr(
        self,
        atr_daily:    float,
        price_usd:    float,
        symbol:       str = "",
        trading_days: int = 365,
    ) -> float:
        if price_usd <= 0 or atr_daily <= 0:
            logger.warning(
                f"{symbol}: Invalid inputs - price={price_usd}, atr_daily={atr_daily}"
            )
            return MIN_ANNUAL_VOL

        daily_vol_pct = atr_daily / price_usd
        annual_vol    = daily_vol_pct * math.sqrt(252)

        logger.debug(
            f"{symbol}: price={price_usd:.6f}, daily_ATR={atr_daily:.6f}, "
            f"daily_vol={daily_vol_pct*100:.2f}%, annual_vol={annual_vol*100:.1f}%"
        )

        annual_vol = max(annual_vol, MIN_ANNUAL_VOL)

        if annual_vol > MAX_ANNUAL_VOL:
            logger.warning(
                f"{symbol}: Capping extreme volatility "
                f"{annual_vol*100:.1f}% → {MAX_ANNUAL_VOL*100:.0f}%"
            )
            annual_vol = MAX_ANNUAL_VOL

        return annual_vol

    def calculate_lots(
        self,
        symbol:    str,
        forecast:  float,
        atr_daily: float,
        sym_cfg:   SymbolConfig,
    ) -> float:
        account = mt5.account_info()
        if not account:
            logger.error(f"{symbol}: Cannot get account info")
            return 0.0

        balance_zar     = account.balance
        free_margin_zar = account.margin_free

        if balance_zar < 250:
            logger.warning(f"Account balance {balance_zar:.2f} ZAR below minimum")
            return 0.0

        if free_margin_zar < 10:
            logger.warning(f"{symbol}: Free margin too low: {free_margin_zar:.2f} ZAR")
            return 0.0

        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick or (tick.bid == 0 and tick.ask == 0):
            logger.error(f"{symbol}: Cannot get price info")
            return 0.0

        price_usd    = (tick.bid + tick.ask) / 2.0
        usd_zar_rate = self.get_usd_to_zar_rate()

        annual_vol   = self.annual_vol_from_atr(
            atr_daily, price_usd, symbol, sym_cfg.trading_days
        )
        notional_zar = self.calculate_notional_exposure(balance_zar, annual_vol, forecast)
        notional_usd = notional_zar / usd_zar_rate

        contract_size = info.trade_contract_size if info.trade_contract_size > 0 else 1.0
        raw_lots      = notional_usd / (price_usd * contract_size)

        min_lot  = sym_cfg.min_volume
        max_lot  = sym_cfg.max_volume
        lot_step = info.volume_step if info.volume_step > 0 else sym_cfg.volume_step

        if lot_step > 0:
            lots = math.floor(raw_lots / lot_step) * lot_step
        else:
            lots = raw_lots

        lots = max(min_lot, min(lots, max_lot))

        if lots < min_lot:
            logger.warning(
                f"{symbol}: Calculated lots {lots:.6f} below minimum {min_lot:.4f}"
            )
            return 0.0

        margin_per_lot_usd = self._get_margin_per_lot_usd(info, account, price_usd)
        margin_per_lot_zar = margin_per_lot_usd * usd_zar_rate
        total_margin_zar   = lots * margin_per_lot_zar
        max_margin_zar     = free_margin_zar * MAX_MARGIN_FRACTION

        if total_margin_zar > max_margin_zar and lot_step > 0 and margin_per_lot_zar > 0:
            max_lots_by_margin = (
                math.floor(max_margin_zar / margin_per_lot_zar / lot_step) * lot_step
            )
            max_lots_by_margin = max(min_lot, max_lots_by_margin)

            if max_lots_by_margin >= min_lot:
                lots = min(lots, max_lots_by_margin)
                lots = math.floor(lots / lot_step) * lot_step
                lots = max(min_lot, lots)
                logger.info(f"{symbol}: Reduced lots to {lots:.4f} due to margin limit")

        lots = round(lots, 6)
        risk_percent = (notional_zar / balance_zar) * 100

        logger.info(
            f"VolSizer {symbol}: "
            f"Balance={balance_zar:.0f} ZAR | "
            f"Forecast={forecast:+.1f} | "
            f"Volatility={annual_vol*100:.1f}% | "
            f"Risk={risk_percent:.2f}% of balance | "
            f"Lots={lots:.4f}"
        )
        return lots

    def _get_margin_per_lot_usd(self, info, account, price_usd: float) -> float:
        if info.margin_initial > 0:
            return info.margin_initial

        if account.leverage > 0 and info.trade_contract_size > 0 and price_usd > 0:
            return (info.trade_contract_size * price_usd) / account.leverage

        if price_usd > 0:
            return info.trade_contract_size * price_usd * 0.01

        return 0.0