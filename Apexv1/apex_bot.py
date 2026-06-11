# apex_bot.py
import logging
import time
from datetime import datetime
from typing import Dict, Optional

import MetaTrader5 as mt5

from apex_config import SystemConfig, TIMEFRAME_META, BrokerSpec, get_idm_for_instrument_count
from apex_ewmac_strategy import MultiSpeedEWMAC, ForecastResult
from apex_volatility_sizer import ApexVolatilitySizer
from apex_order_manager import ApexOrderManager
from apex_data_provider import ApexDataProvider
from apex_dashboard import ApexDashboard
from apex_symbol_state import ApexSymbolState
from models import PositionState, SignalData
from signal import SignalType, PositionType

logger = logging.getLogger(__name__)


class ApexTradingBot:

    def __init__(self, config: SystemConfig):
        self.cfg = config
        self.strategies: Dict[str, MultiSpeedEWMAC] = {}

        self.order_mgr = ApexOrderManager(config)
        self.data_prov = ApexDataProvider()
        self.dashboard = ApexDashboard() if config.enable_dashboard else None

        if not self.order_mgr.initialize():
            raise ConnectionError("Failed to connect to MetaTrader 5")

        self.symbol_states: Dict[str, ApexSymbolState] = {}
        self._validate_and_init_symbols()
        
        self.order_mgr.set_symbol_states(self.symbol_states)

        for sym, state in self.symbol_states.items():
            self.strategies[sym] = MultiSpeedEWMAC(
                config.strategy, timeframe=state.config.primary_tf
            )

        active_count = len(self.symbol_states)
        dynamic_idm = get_idm_for_instrument_count(active_count)
        self.cfg.strategy.idm = dynamic_idm
        self.cfg.vol_position_sizing.expected_positions = active_count

        self.sizer = ApexVolatilitySizer(
            config.strategy, config.vol_position_sizing, active_count, self.symbol_states
        )

        logger.info(f"APEX SYSTEM ACTIVE | IDM={dynamic_idm:.2f} | N={active_count}")
        logger.info(f"Trading: BTCUSD, ETHUSD only")
        logger.info(f"Timeframe: M5 (5 minute) ultra aggressive")
        logger.info(f"Exit: Trailing stop (1.5× ATR) + Stop and Reverse")
        logger.info(f"Smart re-entry: ENABLED (15 min cooldown)")

    def _validate_and_init_symbols(self) -> None:
        print("\n" + "═" * 80)
        print(f"  APEX SYSTEM - SYMBOL VALIDATION")
        print("═" * 80)
        print(f"  {'SYMBOL':<12} {'STATUS':<10} {'MIN':<10} {'MAX':<10} "
              f"{'STEP':<8} {'DIGITS':<8} {'VOL TARGET':<12} {'TIMEFRAME':<10} {'STOP MULT':<10}")
        print("─" * 80)

        for sym, sym_cfg in self.cfg.symbols.items():
            if not sym_cfg.enabled:
                print(f"  {sym:<12} {'DISABLED':<10}")
                continue

            spec = BrokerSpec.from_mt5(sym)
            if spec is None:
                print(f"  {sym:<12} {'NOT FOUND':<10}")
                continue

            if not spec.visible:
                if not mt5.symbol_select(sym, True):
                    print(f"  {sym:<12} {'NO DATA':<10}")
                    continue
                spec = BrokerSpec.from_mt5(sym)

            tick = mt5.symbol_info_tick(sym)
            if tick is None or tick.bid == 0:
                print(f"  {sym:<12} {'NO TICK':<10}")
                continue

            if not spec.tradeable:
                print(f"  {sym:<12} {'DISABLED':<10}")
                continue

            sym_cfg.broker_spec = spec
            sym_cfg.min_volume = spec.min_volume
            sym_cfg.max_volume = spec.max_volume
            sym_cfg.volume_step = spec.volume_step

            self.symbol_states[sym] = ApexSymbolState(
                sym_cfg, self.cfg.strategy, self.cfg.atr_trailing.enabled, self.cfg.smart_reentry
            )

            stop_mult = self.cfg.atr_trailing.multiple
            print(
                f"  {sym:<12} {'✓ APEX':<10} "
                f"{spec.min_volume:<10.4f} {spec.max_volume:<10.1f} "
                f"{spec.volume_step:<8.4f} {spec.digits:<8d} "
                f"{sym_cfg.vol_target_pct*100:>5.2f}%      "
                f"{sym_cfg.primary_tf:<10} {stop_mult:>5.1f}x"
            )

        print("═" * 80)
        print(f"  Active symbols: {len(self.symbol_states)} (BTCUSD + ETHUSD)")
        print(f"  ULTRA AGGRESSIVE MODE ACTIVE")
        print()

        if not self.symbol_states:
            raise RuntimeError("No symbols passed validation")

    def run(self) -> None:
        logger.info(" APEX main loop started (ULTRA AGGRESSIVE MODE)")
        while True:
            try:
                t0 = time.time()
                account = self.order_mgr.get_account_info()
                if not account:
                    time.sleep(5)
                    continue

                self._sync_and_process()

                if self.dashboard:
                    self.dashboard.update(account, self.symbol_states)

                elapsed = time.time() - t0
                time.sleep(max(1.0, self.cfg.poll_interval - elapsed))

            except KeyboardInterrupt:
                break
            except Exception as exc:
                logger.error(f"Main loop error: {exc}", exc_info=True)
                time.sleep(5)

        self.shutdown()

    def _sync_and_process(self) -> None:
        enabled_symbols = list(self.symbol_states.keys())
        self.order_mgr.sync_positions(enabled_symbols)

        for sym in enabled_symbols:
            state = self.symbol_states[sym]
            trade = self.order_mgr.open_positions.get(sym)

            currently_has_position = state.position_state.has_position

            if trade is None:
                if currently_has_position:
                    logger.debug(f"{sym}: position gone – resetting")
                    state.position_state = PositionState.empty()
                    state.trailing_stop_state = None
            else:
                if not currently_has_position:
                    logger.debug(f"{sym}: new position detected")
                    state.position_state = PositionState.from_trade(
                        trade, self.cfg.atr_trailing.enabled
                    )
                    if trade.position_type:
                        state.position_state.position_type = trade.position_type
                    state.trailing_stop_state = None
                else:
                    if state.position_state.ticket != trade.ticket:
                        state.position_state.ticket = trade.ticket
                    if state.position_state.entry_price != trade.entry_price:
                        state.position_state.entry_price = trade.entry_price
                    if state.position_state.volume != trade.volume:
                        state.position_state.volume = trade.volume
                    if trade.position_type and state.position_state.position_type != trade.position_type:
                        state.position_state.position_type = trade.position_type

        for sym in enabled_symbols:
            try:
                self._process_symbol(sym, self.symbol_states[sym])
            except Exception as exc:
                logger.error(f"Error processing {sym}: {exc}", exc_info=True)

    def _process_symbol(self, symbol: str, state: ApexSymbolState) -> None:
        price = self.order_mgr.get_current_price(symbol)
        if price == 0:
            return

        if state.last_price > 0:
            state.price_change_pct = (price - state.last_price) / state.last_price * 100
        state.current_price = price
        state.last_price = price
        state.reset_daily_counter()

        # ── Trailing stop monitoring runs every poll cycle, not just on new candles ──
        if state.position_state.has_position:
            stop_moved = state.update_trailing_stop(
                price, state.atr_candle, state.current_stop_multiplier
            )

            if stop_moved and state.position_state.trailing_stop_price:
                logger.info(f"{symbol}: APEX TRAIL UPDATE | stop={state.position_state.trailing_stop_price:.{state.digits}f}")

                if state.position_state.ticket:
                    success = self.order_mgr.update_stop_loss(
                        symbol, state.position_state.ticket, state.position_state.trailing_stop_price
                    )
                    if not success:
                        logger.warning(f"{symbol}: Failed to update stop")

            if state.check_trailing_stop_exit(price):
                logger.warning(f"{symbol}: APEX STOP TRIGGERED | price={price:.{state.digits}f}")
                self._close_position(symbol, state, exit_reason="ATR_STOP", force=True)
                return

        # ── Strategy recalculation is gated to one execution per new candle ──
        bars = TIMEFRAME_META[state.config.primary_tf]["bars"]
        df = self.data_prov.get_historical_data(symbol, state.config.primary_tf, bars)
        if df.empty:
            return

        current_candle_time = df.index[-1]
        if current_candle_time == state.last_candle_time:
            return
        state.last_candle_time = current_candle_time

        strategy = self.strategies[symbol]
        result: ForecastResult = strategy.calculate(df)

        state.vol_daily = result.vol_daily
        state.atr_candle = result.atr_candle
        state.atr = result.atr_daily
        state.current_stop_multiplier = result.stop_multiplier
        state.speed_forecasts = result.speed_forecasts
        state.ewmac_forecast = result.combined_forecast
        state.current_forecast = result.combined_forecast

        state.update_signal(SignalData(
            signal=result.signal,
            forecast=result.combined_forecast,
            trend=result.trend,
            timestamp=datetime.utcnow(),
        ))

        self._execute_decisions(symbol, state, result)

    def _execute_decisions(self, symbol: str, state: ApexSymbolState, result: ForecastResult) -> None:
        if state.should_reverse_to_short() and state.can_close_position():
            logger.info(f"{symbol}: SIGNAL REVERSAL - closing long, opening short")
            self._close_position(symbol, state, exit_reason="SIGNAL_REVERSAL")
            # Only proceed if the close was confirmed (state cleared by _close_position)
            if not state.position_state.has_position:
                self._open_position(symbol, state, SignalType.SELL, result)
            return

        if state.should_reverse_to_long() and state.can_close_position():
            logger.info(f"{symbol}: SIGNAL REVERSAL - closing short, opening long")
            self._close_position(symbol, state, exit_reason="SIGNAL_REVERSAL")
            # Only proceed if the close was confirmed (state cleared by _close_position)
            if not state.position_state.has_position:
                self._open_position(symbol, state, SignalType.BUY, result)
            return

        if state.should_enter_long() and state.can_open_position():
            self._open_position(symbol, state, SignalType.BUY, result)
        elif state.should_enter_short() and state.can_open_position():
            self._open_position(symbol, state, SignalType.SELL, result)

    def _open_position(self, symbol: str, state: ApexSymbolState, signal: SignalType, result: ForecastResult) -> None:
        account = mt5.account_info()
        if not account:
            logger.warning(f"{symbol}: Cannot get account info")
            return

        if account.balance < 50:
            logger.warning(f"{symbol}: Balance {account.balance:.2f} ZAR - very low")

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.error(f"{symbol}: Cannot get symbol info")
            return

        lots = self.sizer.calculate_lots(
            symbol=symbol,
            forecast=state.current_forecast,
            atr_daily=result.atr_daily,
            sym_cfg=state.config,
        )

        if lots <= 0:
            logger.warning(f"{symbol}: Sizer returned 0 lots")
            return

        min_lot = state.config.min_volume
        max_lot = state.config.max_volume

        if lots < min_lot:
            if "ETH" in symbol:
                lots = min_lot
                logger.info(f"{symbol}: Using minimum lots {min_lot}")
            else:
                logger.warning(f"{symbol}: Lots {lots:.4f} below minimum {min_lot:.4f}")
                return

        lots = max(min_lot, min(lots, max_lot))
        digits = symbol_info.digits

        initial_stop = None
        stop_distance = 0.0
        if self.cfg.atr_trailing.enabled and result.atr_candle > 0:
            stop_distance = result.atr_candle * result.stop_multiplier
            if signal == SignalType.BUY:
                initial_stop = round(state.current_price - stop_distance, digits)
                if initial_stop >= state.current_price:
                    initial_stop = None
            else:
                initial_stop = round(state.current_price + stop_distance, digits)
                if initial_stop <= state.current_price:
                    initial_stop = None

        # size_multiplier (post-stop cooldown reduction) is applied inside calculate_lots();
        # log only what the sizer actually returned so the entry log is truthful.
        size_multiplier = state.get_position_size_multiplier()
        if size_multiplier < 1.0:
            logger.info(f"{symbol}: Post-stop size reduction active ({size_multiplier:.2f}x) – already applied by sizer")

        logger.info(
            f"{symbol}: APEX ENTRY | lots={lots:.4f} | "
            f"candle ATR={result.atr_candle:.{digits}f} | "
            f"stop_mult={result.stop_multiplier}x | "
            f"price={state.current_price:.{digits}f}"
        )

        ticket = self.order_mgr.place_order(
            symbol, signal, lots, "APEX_SYSTEM",
            stop_loss=initial_stop,
            take_profit=None,
            entry_atr=result.atr_candle,
        )

        if ticket:
            state.last_open_attempt = time.time()
            state.daily_trades += 1
            state.position_state.ticket = ticket
            state.position_state.position_type = PositionType.LONG if signal == SignalType.BUY else PositionType.SHORT
            state.position_state.has_position = True
            state.position_state.entry_price = state.current_price
            state.position_state.volume = lots

            if initial_stop:
                state.position_state.trailing_stop_enabled = True
                state.position_state.trailing_stop_price = initial_stop
                state.position_state.entry_atr = result.atr_candle
                state.position_state.stop_multiplier = result.stop_multiplier
                state.position_state.initial_stop = initial_stop
                
            if signal == SignalType.BUY:
                state.position_state.highest_price_since_entry = state.current_price
            else:
                state.position_state.lowest_price_since_entry = state.current_price
            state.trailing_stop_state = None

            logger.info(f"{symbol}: APEX OPENED {signal.value} | lots={lots:.4f} | ticket={ticket} | NO TP")

    def _close_position(self, symbol: str, state: ApexSymbolState, exit_reason: str = "MANUAL", force: bool = False) -> None:
        if not force and not state.can_close_position():
            return
        state.last_close_attempt = time.time()
        if self.order_mgr.close_position(symbol):
            logger.info(f"{symbol}: position closed | reason={exit_reason}")
            state.position_state.ticket = None
            state.position_state.has_position = False

    def shutdown(self) -> None:
        logger.info("Shutting down APEX TradingBot…")
        self.order_mgr.shutdown()