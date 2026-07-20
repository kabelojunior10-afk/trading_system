import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import MetaTrader5 as mt5
import pandas as pd

from apex_config import SystemConfig
from models import Trade
from signal import SignalType, PositionType

logger = logging.getLogger(__name__)

_MAX_MARGIN_REDUCTION_STEPS = 3


class ApexOrderManager:

    def __init__(self, config: SystemConfig):
        self.config = config
        self.open_positions: Dict[str, Optional[Trade]] = {}
        self.trade_history: List[Trade] = []
        self._usd_zar_rate_cache = None
        self._last_rate_time = 0
        self._last_stop_price: Dict[int, float] = {}
        self.symbol_states = None

    def set_symbol_states(self, symbol_states):
        self.symbol_states = symbol_states

    def initialize(self) -> bool:
        if not mt5.initialize():
            logger.error(f"MT5 init failed: {mt5.last_error()}")
            return False

        info = mt5.account_info()
        if info:
            logger.info(f"APEX MT5 | Account: {info.login} | Balance: {info.balance:.2f} {info.currency} | Leverage: 1:{info.leverage}")
        return True

    def shutdown(self) -> None:
        mt5.shutdown()
        logger.info("MT5 closed")

    def get_account_info(self):
        return mt5.account_info()

    def get_current_price(self, symbol: str) -> float:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return 0.0
        return (tick.bid + tick.ask) / 2.0

    def _get_usd_zar_rate(self) -> float:
        current_time = time.time()

        if self._usd_zar_rate_cache is not None and (current_time - self._last_rate_time) < 5:
            return self._usd_zar_rate_cache

        try:
            usd_zar_info = mt5.symbol_info("USDZAR")
            if usd_zar_info:
                tick = mt5.symbol_info_tick("USDZAR")
                if tick and tick.bid > 0:
                    self._usd_zar_rate_cache = tick.bid
                    self._last_rate_time = current_time
                    return self._usd_zar_rate_cache

            eurusd = mt5.symbol_info_tick("EURUSD")
            eurzar = mt5.symbol_info_tick("EURZAR")
            if eurusd and eurzar and eurusd.bid > 0 and eurzar.bid > 0:
                self._usd_zar_rate_cache = eurzar.bid / eurusd.bid
                self._last_rate_time = current_time
                return self._usd_zar_rate_cache

            self._usd_zar_rate_cache = 18.5
            return 18.5
        except Exception:
            return 18.5

    def _is_close_only(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            return True
        return info.trade_mode == mt5.SYMBOL_TRADE_MODE_CLOSEONLY

    def update_stop_loss(self, symbol: str, ticket: int, new_stop: float) -> bool:
        if ticket in self._last_stop_price:
            if abs(self._last_stop_price[ticket] - new_stop) < 0.000001:
                return True

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False

        position = positions[0]
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return False

        digits = symbol_info.digits
        rounded_stop = round(new_stop, digits)
        current_price = self.get_current_price(symbol)
        is_long = position.type == mt5.ORDER_TYPE_BUY

        if is_long and rounded_stop >= current_price:
            return False
        if not is_long and rounded_stop <= current_price:
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": rounded_stop,
            "tp": 0.0,
        }

        for attempt in range(1, self.config.max_retries + 1):
            try:
                result = mt5.order_send(request)

                if result is None:
                    time.sleep(0.5)
                    continue

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._last_stop_price[ticket] = rounded_stop
                    trade = self.open_positions.get(symbol)
                    if trade and trade.ticket == ticket:
                        trade.initial_stop = rounded_stop
                    logger.info(f"APEX STOP | {symbol} | {rounded_stop:.{digits}f}")
                    return True

                if result.retcode == 0:
                    self._last_stop_price[ticket] = rounded_stop
                    return True

                time.sleep(self.config.retry_delay)

            except Exception as e:
                logger.error(f"Stop update error: {e}")
                time.sleep(self.config.retry_delay)

        return False

    def place_order(self, symbol: str, signal: SignalType, volume: float, strategy_name: str,
                    stop_loss: Optional[float] = None, take_profit: Optional[float] = None,
                    entry_atr: Optional[float] = None, _reduction_step: int = 0) -> Optional[int]:

        if self._is_close_only(symbol):
            return None

        if not self._ensure_symbol_visible(symbol):
            return None

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return None

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None

        is_buy = signal == SignalType.BUY
        order_t = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        digits = symbol_info.digits
      
        price = round(tick.ask if is_buy else tick.bid, digits)

      
        sl_price = None
        if entry_atr is not None and entry_atr > 0 and stop_loss is not None and stop_loss > 0:
          
            original_distance = abs(price - stop_loss)
            stop_distance = max(original_distance, entry_atr)
            if is_buy:
                sl_price = round(price - stop_distance, digits)
            else:
                sl_price = round(price + stop_distance, digits)
        elif stop_loss is not None and stop_loss > 0:
            sl_price = round(stop_loss, digits)

        account = mt5.account_info()
        if not account:
            return None

        required_margin = self._calculate_margin_required(symbol, volume, price)

        if required_margin > account.margin_free * 0.7:
            logger.warning(f"{symbol}: Margin tight - required: {required_margin:.2f}")
            if _reduction_step < _MAX_MARGIN_REDUCTION_STEPS:
                reduction_factor = (account.margin_free * 0.7) / required_margin
                reduced_volume = volume * reduction_factor
                if symbol_info.volume_step > 0:
                    reduced_volume = round(reduced_volume / symbol_info.volume_step) * symbol_info.volume_step
                reduced_volume = max(symbol_info.volume_min, min(symbol_info.volume_max, reduced_volume))
                return self.place_order(symbol, signal, reduced_volume, strategy_name,
                                        stop_loss, take_profit, entry_atr, _reduction_step + 1)
            return None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_t,
            "price": price,
            "deviation": 10,
            "magic": self.config.magic_number,
            "comment": f"APEX|{self.config.magic_number}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        if sl_price:
            request["sl"] = sl_price

        for attempt in range(1, self.config.max_retries + 1):
            try:
                result = mt5.order_send(request)

                if result is None:
                    time.sleep(self.config.retry_delay)
                    continue

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    trade = Trade(
                        ticket=result.order,
                        symbol=symbol,
                        signal_type=signal,
                        position_type=PositionType.LONG if is_buy else PositionType.SHORT,
                        entry_price=price,
                        entry_time=datetime.utcnow(),
                        volume=volume,
                        strategy=strategy_name,
                        entry_atr=entry_atr if sl_price else None,
                        initial_stop=sl_price,
                    )
                    self.open_positions[symbol] = trade
                    self.trade_history.append(trade)

                    if sl_price:
                        self._last_stop_price[result.order] = sl_price

                    logger.info(f" APEX OPEN | {symbol} {volume:.4f} @ {price:.{digits}f} | ticket={result.order}")
                    return result.order

                time.sleep(self.config.retry_delay)

            except Exception as e:
                logger.error(f"Order error: {e}")
                time.sleep(self.config.retry_delay)

        return None

    def close_position(self, symbol: str) -> bool:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            self.open_positions[symbol] = None
            return True

        all_closed = True
        for pos in positions:
            if not self._close_one_position(symbol, pos):
                all_closed = False
            else:
                self._last_stop_price.pop(pos.ticket, None)

        if all_closed:
            self.open_positions[symbol] = None
        return all_closed

    def _close_one_position(self, symbol: str, pos) -> bool:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False

        is_long = pos.type == mt5.ORDER_TYPE_BUY
        close_t = mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY
        price = tick.bid if is_long else tick.ask

        symbol_info = mt5.symbol_info(symbol)
        digits = symbol_info.digits if symbol_info else 5
        price = round(price, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": close_t,
            "position": pos.ticket,
            "price": price,
            "deviation": 30,
            "magic": self.config.magic_number,
            "comment": f"APEX_CLOSE|{self.config.magic_number}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            trade = self.open_positions.get(symbol)
            profit = 0.0
            if trade:
                trade.exit_price = price
                trade.exit_time = datetime.utcnow()
                profit = ((price - trade.entry_price) * trade.volume if trade.position_type == PositionType.LONG
                          else (trade.entry_price - price) * trade.volume)
                trade.profit = profit
            logger.info(f"APEX CLOSE | {symbol} @ {price:.{digits}f} | P&L={profit:.2f}")
            return True

        return False

    def sync_positions(self, symbols: List[str]) -> None:
        for symbol in symbols:
            mt5_positions = mt5.positions_get(symbol=symbol)
            tracked = self.open_positions.get(symbol)

            if not mt5_positions:
                if tracked is not None:
                    if tracked.initial_stop:
                        # Fetch a fresh tick rather than relying on potentially stale state.current_price
                        current_price = self.get_current_price(symbol)
                        if tracked.position_type == PositionType.LONG:
                            stop_reached = current_price <= tracked.initial_stop
                        else:
                            stop_reached = current_price >= tracked.initial_stop

                        if stop_reached and self.symbol_states and symbol in self.symbol_states:
                            state = self.symbol_states[symbol]
                            if hasattr(state, 'record_stop_loss'):
                                state.record_stop_loss(tracked.initial_stop, getattr(state, 'current_forecast', 0),
                                                       getattr(state, 'atr_candle', 0))

                    self._last_stop_price.pop(tracked.ticket, None)
                    self.open_positions[symbol] = None
            else:
                if tracked is None:
                    pos = mt5_positions[0]
                    trade = Trade(
                        ticket=pos.ticket,
                        symbol=symbol,
                        signal_type=SignalType.BUY if pos.type == 0 else SignalType.SELL,
                        position_type=PositionType.LONG if pos.type == 0 else PositionType.SHORT,
                        entry_price=pos.price_open,
                        entry_time=datetime.utcfromtimestamp(pos.time),
                        volume=pos.volume,
                        strategy="APEX_ADOPTED",
                        initial_stop=pos.sl if pos.sl != 0 else None,
                    )
                    self.open_positions[symbol] = trade
                    if pos.sl != 0:
                        self._last_stop_price[pos.ticket] = pos.sl

    def _calculate_margin_required(self, symbol: str, volume: float, price: float) -> float:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            return 0.0

        account = mt5.account_info()
        if not account:
            return 0.0

        usd_zar = 1.0
        if "USD" in symbol and account.currency == "ZAR":
            usd_zar = self._get_usd_zar_rate()

        if symbol_info.margin_initial > 0:
            return volume * symbol_info.margin_initial * usd_zar

        if account.leverage > 0 and symbol_info.trade_contract_size > 0 and price > 0:
            return (symbol_info.trade_contract_size * volume * price) / account.leverage * usd_zar

        return volume * price * 0.02 * usd_zar

    def _ensure_symbol_visible(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                return False
        return True