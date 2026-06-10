import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import MetaTrader5 as mt5
import pandas as pd

from config import SystemConfig
from models import Trade
from signal import SignalType, PositionType

logger = logging.getLogger(__name__)

# Maximum number of recursive volume-reduction steps before giving up
_MAX_MARGIN_REDUCTION_STEPS = 3


class OrderManager:

    def __init__(self, config: SystemConfig):
        self.config         = config
        self.open_positions: Dict[str, Optional[Trade]] = {}
        self.trade_history:  List[Trade]                = []
        self._usd_zar_rate_cache = None
        self._last_rate_time = 0
        # Track stop loss prices per position ticket to avoid redundant updates
        self._last_stop_price: Dict[int, float] = {}
        # Track symbol states reference (set by bot)
        self.symbol_states = None

    def set_symbol_states(self, symbol_states):
        """Set reference to symbol states for stop tracking"""
        self.symbol_states = symbol_states

    def initialize(self) -> bool:
        if not mt5.initialize():
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False

        info = mt5.account_info()
        if info:
            logger.info(
                f"MT5 connected | Account: {info.login} | "
                f"Balance: {info.balance:,.2f} {info.currency} | "
                f"Leverage: 1:{info.leverage}"
            )
        return True

    def shutdown(self) -> None:
        mt5.shutdown()
        logger.info("MT5 connection closed")

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
                    logger.debug(f"USD/ZAR live rate: {self._usd_zar_rate_cache:.4f}")
                    return self._usd_zar_rate_cache

            eurusd = mt5.symbol_info_tick("EURUSD")
            eurzar = mt5.symbol_info_tick("EURZAR")
            if eurusd and eurzar and eurusd.bid > 0 and eurzar.bid > 0:
                self._usd_zar_rate_cache = eurzar.bid / eurusd.bid
                self._last_rate_time = current_time
                logger.debug(f"USD/ZAR derived rate: {self._usd_zar_rate_cache:.4f}")
                return self._usd_zar_rate_cache

            self._usd_zar_rate_cache = 18.5
            self._last_rate_time = current_time
            logger.warning("Using default USD/ZAR rate 18.5")
            return 18.5
        except Exception as e:
            logger.error(f"Error getting USD/ZAR rate: {e}")
            return 18.5

    def _is_close_only(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            return True
        return info.trade_mode == mt5.SYMBOL_TRADE_MODE_CLOSEONLY

    def _calculate_margin_required(
        self,
        symbol: str,
        volume: float,
        price: float,
    ) -> float:
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
            margin_usd = volume * symbol_info.margin_initial
            return margin_usd * usd_zar

        if account.leverage > 0 and symbol_info.trade_contract_size > 0 and price > 0:
            margin_usd = (symbol_info.trade_contract_size * volume * price) / account.leverage
            return margin_usd * usd_zar

        margin_usd = volume * price * 0.02
        return margin_usd * usd_zar

    def update_stop_loss(self, symbol: str, ticket: int, new_stop: float) -> bool:
        """
        Update stop loss for an existing position on the broker side.
        
        Returns:
            bool: True if stop was updated successfully, False otherwise
        """
        # Check if this is a duplicate update (same stop price)
        if ticket in self._last_stop_price:
            if abs(self._last_stop_price[ticket] - new_stop) < 0.000001:
                logger.debug(f"{symbol}: Stop price unchanged at {new_stop}, skipping update")
                return True
        
        # Get current position
        positions = mt5.positions_get(ticket=ticket)
        if not positions or len(positions) == 0:
            logger.warning(f"{symbol}: Position ticket {ticket} not found for stop update")
            return False
        
        position = positions[0]
        
        # Get symbol info for proper rounding
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"{symbol}: Cannot get symbol info for stop update")
            return False
        
        digits = symbol_info.digits
        rounded_stop = round(new_stop, digits)
        
        # Validate stop price is reasonable
        current_price = self.get_current_price(symbol)
        is_long = position.type == mt5.ORDER_TYPE_BUY
        
        if is_long and rounded_stop >= current_price:
            logger.warning(
                f"{symbol}: LONG stop {rounded_stop} >= current price {current_price:.{digits}f} - rejecting"
            )
            return False
        
        if not is_long and rounded_stop <= current_price:
            logger.warning(
                f"{symbol}: SHORT stop {rounded_stop} <= current price {current_price:.{digits}f} - rejecting"
            )
            return False
        
        # Use TRADE_ACTION_SLTP to modify stop loss
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": rounded_stop,
            "tp": position.tp if position.tp != 0 else 0.0,
        }
        
        # Send modification request with retries
        for attempt in range(1, self.config.max_retries + 1):
            try:
                result = mt5.order_send(request)
                
                if result is None:
                    logger.warning(f"{symbol}: order_send returned None (attempt {attempt}), refreshing position data")
                    time.sleep(0.5)
                    positions = mt5.positions_get(ticket=ticket)
                    if positions and len(positions) > 0:
                        position = positions[0]
                        request["tp"] = position.tp if position.tp != 0 else 0.0
                    continue
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._last_stop_price[ticket] = rounded_stop
                    
                    # Update the Trade object if it exists
                    trade = self.open_positions.get(symbol)
                    if trade and trade.ticket == ticket:
                        trade.initial_stop = rounded_stop
                    
                    logger.info(
                        f"✓ STOP UPDATE {symbol} | ticket={ticket} | "
                        f"new_stop={rounded_stop:.{digits}f} | "
                        f"price={current_price:.{digits}f}"
                    )
                    return True
                
                # Handle specific error codes
                if result.retcode == 0:  # Success but not DONE
                    self._last_stop_price[ticket] = rounded_stop
                    logger.info(f"✓ STOP UPDATE {symbol} (retcode 0) | stop={rounded_stop:.{digits}f}")
                    return True
                
                # Invalid stops - try without TP
                if result.retcode in (10025, mt5.TRADE_RETCODE_INVALID_STOPS, 10027):
                    logger.warning(
                        f"{symbol}: Invalid stop - retcode={result.retcode}, attempt {attempt}"
                    )
                    # Try without TP parameter
                    request_no_tp = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "symbol": symbol,
                        "sl": rounded_stop,
                        "tp": 0.0,
                    }
                    result2 = mt5.order_send(request_no_tp)
                    if result2 and result2.retcode == mt5.TRADE_RETCODE_DONE:
                        self._last_stop_price[ticket] = rounded_stop
                        logger.info(f"✓ STOP UPDATE {symbol} (no TP) | stop={rounded_stop:.{digits}f}")
                        return True
                    return False
                
                if result.retcode == mt5.TRADE_RETCODE_PRICE_OFF:
                    logger.warning(f"{symbol}: Price changed, will retry (attempt {attempt})")
                    time.sleep(self.config.retry_delay)
                    current_price = self.get_current_price(symbol)
                    continue
                
                logger.error(
                    f"{symbol}: Stop update attempt {attempt} failed - "
                    f"retcode={result.retcode}, comment='{result.comment}'"
                )
                time.sleep(self.config.retry_delay)
                
            except Exception as e:
                logger.error(f"{symbol}: Exception in stop update: {e}")
                time.sleep(self.config.retry_delay)
        
        logger.error(f"{symbol}: Failed to update stop after {self.config.max_retries} attempts")
        return False

    def place_order(
        self,
        symbol:        str,
        signal:        SignalType,
        volume:        float,
        strategy_name: str,
        stop_loss:     Optional[float] = None,
        take_profit:   Optional[float] = None,
        entry_atr:     Optional[float] = None,
        _reduction_step: int = 0,
    ) -> Optional[int]:
        """Place a market order with optional stop loss (NO take profit for trend following)."""

        if self._is_close_only(symbol):
            logger.warning(f"{symbol}: trade_mode=CLOSEONLY – skipping new entry")
            return None

        if not self._ensure_symbol_visible(symbol):
            return None

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"Cannot get info for {symbol}")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            logger.error(f"place_order: no tick for {symbol}")
            return None

        is_buy  = signal == SignalType.BUY
        order_t = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        digits  = symbol_info.digits
        price   = round(tick.ask if is_buy else tick.bid, digits)

        sl_price = None
        use_stop = stop_loss is not None and stop_loss > 0

        if use_stop:
            sl_price = round(stop_loss, digits)
            stop_dist_pct = (
                (price - sl_price) / price * 100 if is_buy
                else (sl_price - price) / price * 100
            )

            if stop_dist_pct < 0.1:
                logger.warning(
                    f"{symbol}: stop too close ({stop_dist_pct:.3f}%) – adjusting to 0.1%"
                )
                sl_price = round(
                    price - price * 0.001 if is_buy else price + price * 0.001,
                    digits,
                )

            if is_buy and sl_price >= price:
                logger.warning(
                    f"{symbol}: BUY stop {sl_price} ≥ price {price} – removing stop"
                )
                sl_price = None
                use_stop  = False
            elif not is_buy and sl_price <= price:
                logger.warning(
                    f"{symbol}: SELL stop {sl_price} ≤ price {price} – removing stop"
                )
                sl_price = None
                use_stop  = False

        direction = "BUY" if is_buy else "SELL"
        logger.info(
            f"{symbol}: {direction} price={price:.{digits}f} "
            + (f"SL={sl_price:.{digits}f}" if sl_price else "(NO STOP LOSS)")
            + " (NO TAKE PROFIT - letting trend run)"
        )

        account = mt5.account_info()
        if not account:
            logger.error(f"{symbol}: cannot get account info")
            return None

        required_margin = self._calculate_margin_required(symbol, volume, price)

        if account.balance < 10000:
            margin_buffer = 1.5
        elif account.balance < 50000:
            margin_buffer = 1.3
        else:
            margin_buffer = 1.2

        if required_margin > 0:
            available_margin = account.margin_free
            required_with_buffer = required_margin * margin_buffer

            if required_with_buffer > available_margin:
                logger.warning(
                    f"{symbol}: Margin tight - Required: {required_margin:.2f} {account.currency}, "
                    f"Available: {available_margin:.2f} {account.currency}, "
                    f"Buffer: {margin_buffer:.1f}x, Volume: {volume:.4f} "
                    f"(reduction step {_reduction_step}/{_MAX_MARGIN_REDUCTION_STEPS})"
                )

                if _reduction_step >= _MAX_MARGIN_REDUCTION_STEPS:
                    logger.error(
                        f"{symbol}: reached max margin-reduction steps "
                        f"({_MAX_MARGIN_REDUCTION_STEPS}) – aborting"
                    )
                    return None

                reduction_factor = (available_margin / margin_buffer) / required_margin
                if reduction_factor > 0.5:
                    reduced_volume = volume * reduction_factor
                    if symbol_info.volume_step > 0:
                        reduced_volume = (
                            round(reduced_volume / symbol_info.volume_step)
                            * symbol_info.volume_step
                        )
                    reduced_volume = max(
                        symbol_info.volume_min,
                        min(symbol_info.volume_max, reduced_volume),
                    )

                    logger.info(
                        f"{symbol}: Retrying with reduced volume: "
                        f"{volume:.4f} → {reduced_volume:.4f}"
                    )
                    return self.place_order(
                        symbol, signal, reduced_volume, strategy_name,
                        stop_loss, take_profit, entry_atr,
                        _reduction_step=_reduction_step + 1,
                    )

                return None

        for stop_attempt in range(2):
            current_sl = sl_price if stop_attempt == 0 and use_stop else None

            if stop_attempt == 1:
                if not use_stop:
                    break
                logger.warning(f"{symbol}: retrying WITHOUT stop loss")

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       volume,
                "type":         order_t,
                "price":        price,
                "deviation":    100,
                "magic":        self.config.magic_number,
                "comment":      f"{strategy_name}|{self.config.magic_number}",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            if current_sl:
                request["sl"] = current_sl
            # DO NOT set take_profit - let trends run

            for attempt in range(1, self.config.max_retries + 1):
                try:
                    result = mt5.order_send(request)

                    if result is None:
                        logger.error(
                            f"{symbol}: order_send returned None "
                            f"(attempt {attempt}) – {mt5.last_error()}"
                        )
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
                            entry_atr=entry_atr if current_sl else None,
                            initial_stop=current_sl,
                        )
                        self.open_positions[symbol] = trade
                        self.trade_history.append(trade)
                        
                        # Track initial stop price
                        if current_sl:
                            self._last_stop_price[result.order] = current_sl
                        
                        stop_str = f"SL={current_sl:.{digits}f}" if current_sl else "NO STOP"
                        logger.info(
                            f"OPEN | {direction} {volume:.4f} {symbol} "
                            f"@ {price:.{digits}f} | {stop_str} | NO TP (let trend run) | ticket={result.order}"
                        )
                        return result.order

                    retcode_name = self._get_error_name(result.retcode)

                    if result.retcode in (10017,):
                        logger.warning(
                            f"{symbol}: broker rejected – close-only/disabled "
                            f"({retcode_name}) – aborting"
                        )
                        return None

                    if result.retcode == mt5.TRADE_RETCODE_NO_MONEY or result.retcode == 10016:
                        logger.error(
                            f"{symbol}: MARGIN_INSUFFICIENT ({retcode_name}) – aborting "
                            "without retry"
                        )
                        return None

                    if current_sl and result.retcode in (
                        mt5.TRADE_RETCODE_INVALID_STOPS, 10025,
                    ):
                        logger.warning(
                            f"{symbol}: stop rejected ({retcode_name}, "
                            f"comment='{result.comment}') – retrying without stop"
                        )
                        break

                    if result.retcode == mt5.TRADE_RETCODE_PRICE_OFF:
                        tick = mt5.symbol_info_tick(symbol)
                        if tick:
                            price = round(tick.ask if is_buy else tick.bid, digits)
                            request["price"] = price

                    logger.error(
                        f"{symbol}: attempt {attempt} – "
                        f"retcode={result.retcode} ({retcode_name}), "
                        f"comment='{result.comment}'"
                    )
                    time.sleep(self.config.retry_delay)
                    
                except Exception as e:
                    logger.error(f"{symbol}: Exception in place_order: {e}")
                    time.sleep(self.config.retry_delay)

            else:
                if stop_attempt == 0 and use_stop:
                    break

        logger.error(f"{symbol}: all order attempts failed")
        return None

    def close_position(self, symbol: str) -> bool:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            self.open_positions[symbol] = None
            # Clean up stop tracking
            trade = self.open_positions.get(symbol)
            if trade:
                self._last_stop_price.pop(trade.ticket, None)
            return True

        all_closed = True
        for pos in positions:
            if not self._close_one_position(symbol, pos):
                all_closed = False
            else:
                # Clean up stop tracking
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
        price   = tick.bid if is_long else tick.ask

        symbol_info = mt5.symbol_info(symbol)
        digits = symbol_info.digits if symbol_info else 5
        price  = round(price, digits)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         close_t,
            "position":     pos.ticket,
            "price":        price,
            "deviation":    100,
            "magic":        self.config.magic_number,
            "comment":      f"close|{self.config.magic_number}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            trade  = self.open_positions.get(symbol)
            profit = 0.0
            if trade:
                trade.exit_price = price
                trade.exit_time  = datetime.utcnow()
                profit = (
                    (price - trade.entry_price) * trade.volume
                    if trade.position_type == PositionType.LONG
                    else (trade.entry_price - price) * trade.volume
                )
                trade.profit = profit
            logger.info(
                f" CLOSE | {symbol} @ {price:.{digits}f} | "
                f"profit={profit:.2f} | ticket={pos.ticket}"
            )
            return True

        logger.error(
            f" {symbol}: close failed – "
            f"retcode={result.retcode if result else 'None'}"
        )
        return False

    def get_position_by_ticket(self, ticket: int) -> Optional[Trade]:
        """Get tracked trade by ticket number."""
        for trade in self.trade_history:
            if trade.ticket == ticket:
                return trade
        for trade in self.open_positions.values():
            if trade and trade.ticket == ticket:
                return trade
        return None

    def get_all_open_positions(self) -> List[Trade]:
        """Get all currently open positions as Trade objects."""
        return [trade for trade in self.open_positions.values() if trade is not None]

    def sync_positions(self, symbols: List[str]) -> None:
        """Reconcile MT5 positions against our internal tracking."""
        for symbol in symbols:
            mt5_positions = mt5.positions_get(symbol=symbol)
            tracked       = self.open_positions.get(symbol)

            if not mt5_positions:
                if tracked is not None:
                    # Check if this was likely a stop loss trigger
                    stop_reached = False
                    stop_reason = "unknown"
                    
                    if tracked.initial_stop:
                        current_price = self.get_current_price(symbol)
                        
                        # Determine if price crossed the stop
                        if tracked.position_type == PositionType.LONG:
                            stop_reached = current_price <= tracked.initial_stop
                            stop_reason = f"LONG stop {tracked.initial_stop} >= price {current_price}"
                        else:
                            stop_reached = current_price >= tracked.initial_stop
                            stop_reason = f"SHORT stop {tracked.initial_stop} <= price {current_price}"
                        
                        if stop_reached:
                            logger.warning(
                                f"Sync: {symbol} closed - STOP LOSS TRIGGERED | "
                                f"{stop_reason} | ticket={tracked.ticket}"
                            )
                            
                            # Record stop loss in symbol state if available
                            if self.symbol_states and symbol in self.symbol_states:
                                state = self.symbol_states[symbol]
                                # Get the forecast and ATR at stop time (approximate)
                                forecast_at_stop = getattr(state, 'current_forecast', 0)
                                atr_at_stop = getattr(state, 'atr_candle', 0)
                                state.record_stop_loss(tracked.initial_stop, forecast_at_stop, atr_at_stop)
                        else:
                            logger.info(
                                f"Sync: {symbol} closed externally (SL={tracked.initial_stop} not hit) | "
                                f"ticket={tracked.ticket}"
                            )
                    else:
                        logger.info(f"Sync: {symbol} closed externally (no stop set) | ticket={tracked.ticket}")
                    
                    self._last_stop_price.pop(tracked.ticket, None)
                    self.open_positions[symbol] = None
            else:
                if tracked is None:
                    pos = mt5_positions[0]
                    estimated_atr = self._estimate_atr_for_symbol(symbol)

                    trade = Trade(
                        ticket=pos.ticket,
                        symbol=symbol,
                        signal_type=SignalType.BUY if pos.type == 0 else SignalType.SELL,
                        position_type=PositionType.LONG if pos.type == 0 else PositionType.SHORT,
                        entry_price=pos.price_open,
                        entry_time=datetime.utcfromtimestamp(pos.time),
                        volume=pos.volume,
                        strategy="Adopted",
                        initial_stop=pos.sl if pos.sl != 0 else None,
                        entry_atr=estimated_atr,
                        stop_multiplier=None,
                    )
                    self.open_positions[symbol] = trade
                    
                    # Track existing stop price
                    if pos.sl != 0:
                        self._last_stop_price[pos.ticket] = pos.sl
                    
                    logger.info(
                        f"Sync: adopted {symbol} | ticket={pos.ticket} | "
                        f"SL={pos.sl} | estimated_atr={estimated_atr}"
                    )
                else:
                    # Update tracked stop price if it changed externally
                    pos = mt5_positions[0]
                    if tracked and pos.sl != tracked.initial_stop:
                        logger.info(
                            f"Sync: {symbol} stop changed externally from "
                            f"{tracked.initial_stop} to {pos.sl}"
                        )
                        tracked.initial_stop = pos.sl
                        if pos.sl != 0:
                            self._last_stop_price[pos.ticket] = pos.sl

    def _estimate_atr_for_symbol(self, symbol: str, period: int = 14) -> Optional[float]:
        """Return a rough ATR(14) on H1 bars for an adopted position."""
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 5)
            if rates is None or len(rates) < period:
                return None
            df = pd.DataFrame(rates)
            high  = df["high"]
            low   = df["low"]
            close = df["close"]
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
            return atr if atr > 0 else None
        except Exception as exc:
            logger.warning(f"_estimate_atr_for_symbol({symbol}): {exc}")
            return None

    def _ensure_symbol_visible(self, symbol: str) -> bool:
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error(f"Symbol '{symbol}' not found on this broker")
            return False
        if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            logger.error(
                f"Symbol '{symbol}' is disabled for trading "
                f"(trade_mode={info.trade_mode})"
            )
            return False
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                logger.error(f"Cannot select symbol '{symbol}' in Market Watch")
                return False
        return True

    def _get_error_name(self, retcode: int) -> str:
        errors = {
            mt5.TRADE_RETCODE_REQUOTE:        "REQUOTE",
            mt5.TRADE_RETCODE_REJECT:         "REJECT",
            mt5.TRADE_RETCODE_CANCEL:         "CANCEL",
            mt5.TRADE_RETCODE_PRICE_OFF:      "PRICE_OFF",
            mt5.TRADE_RETCODE_INVALID_STOPS:  "INVALID_STOPS",
            mt5.TRADE_RETCODE_NO_CHANGES:     "NO_CHANGES",
            mt5.TRADE_RETCODE_MARKET_CLOSED:  "MARKET_CLOSED",
            mt5.TRADE_RETCODE_NO_MONEY:       "NO_MONEY",
            10006:  "REJECTED",
            10014:  "INVALID_VOLUME",
            10016:  "MARGIN_INSUFFICIENT",
            10017:  "TRADE_DISABLED",
            10025:  "INVALID_STOPS",
            10027:  "AUTOTRADING_DISABLED",
        }
        return errors.get(retcode, f"UNKNOWN_{retcode}")