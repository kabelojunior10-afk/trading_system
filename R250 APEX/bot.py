import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

import MetaTrader5 as mt5

from config import SystemConfig, TIMEFRAME_META, BrokerSpec, get_idm_for_instrument_count
from ewmac_strategy import MultiSpeedEWMAC, ForecastResult
from volatility_position_sizer import VolatilityPositionSizer
from order_manager import OrderManager
from data_provider import DataProvider
from dashboard import ProfessionalDashboard
from symbol_state import SymbolState
from models import PositionState, SignalData
from signal import SignalType, PositionType

logger = logging.getLogger(__name__)

class TradingBot:

    def __init__(self, config: SystemConfig):
        self.cfg = config
        self.strategies: Dict[str, MultiSpeedEWMAC] = {}

        self.order_mgr = OrderManager(config)
        self.data_prov = DataProvider()
        self.dashboard = ProfessionalDashboard() if config.enable_dashboard else None

        if not self.order_mgr.initialize():
            raise ConnectionError("Failed to connect to MetaTrader 5")

        self.symbol_states: Dict[str, SymbolState] = {}
        self._validate_and_init_symbols()
        
        # Set reference to symbol_states in order_manager for stop tracking
        self.order_mgr.set_symbol_states(self.symbol_states)

        for sym, state in self.symbol_states.items():
            self.strategies[sym] = MultiSpeedEWMAC(
                config.strategy, timeframe=state.config.primary_tf
            )

        active_count = len(self.symbol_states)
        dynamic_idm = get_idm_for_instrument_count(active_count)
        self.cfg.strategy.idm = dynamic_idm
        self.cfg.vol_position_sizing.expected_positions = active_count

        # Pass symbol_states to sizer for dynamic sizing
        self.sizer = VolatilityPositionSizer(
            config.strategy, config.vol_position_sizing, active_count, self.symbol_states
        )

        logger.info(f"IDM set to {dynamic_idm:.2f} based on {active_count} active instruments")
        logger.info(f"Expected positions (N) set to {active_count}")
        logger.info(f"AGGRESSIVE MODE ACTIVE | R250 Configuration")
        logger.info(f"Exit Logic: Trailing Stop Loss + Stop and Reverse (NO take profit)")
        logger.info(f"Smart Re-entry: {'ENABLED' if config.smart_reentry.enabled else 'DISABLED'}")
        logger.info(f"Re-entry cooldown: {config.smart_reentry.cooldown_minutes} minutes")
        logger.info(f"Max consecutive stops: {config.smart_reentry.max_consecutive_stops}")
        logger.info(f"TradingBot ready | active symbols: {list(self.symbol_states.keys())}")

    def _validate_and_init_symbols(self) -> None:
        print("\n" + "═" * 80)
        print(f"  AGGRESSIVE TRADING SYSTEM - SYMBOL VALIDATION")
        print("═" * 80)
        print(
            f"  {'SYMBOL':<12} {'STATUS':<10} {'MIN':<10} {'MAX':<10} "
            f"{'STEP':<8} {'DIGITS':<8} {'VOL TARGET':<12} {'TIMEFRAME':<10} {'STOP MULT':<10}"
        )
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

            # Create SymbolState with smart re-entry config
            self.symbol_states[sym] = SymbolState(
                sym_cfg, self.cfg.strategy, self.cfg.atr_trailing.enabled, self.cfg.smart_reentry
            )

            stop_mult = self.cfg.atr_trailing.multiple if self.cfg.atr_trailing.multiple else TIMEFRAME_META[sym_cfg.primary_tf]["stop_multiplier"]
            print(
                f"  {sym:<12} {'✓ OK':<10} "
                f"{spec.min_volume:<10.4f} {spec.max_volume:<10.1f} "
                f"{spec.volume_step:<8.4f} {spec.digits:<8d} "
                f"{sym_cfg.vol_target_pct*100:>5.2f}%      "
                f"{sym_cfg.primary_tf:<10} {stop_mult:>5.1f}x"
            )

        print("═" * 80)
        print(f"  Active symbols: {len(self.symbol_states)} / {len(self.cfg.symbols)}")
        print(f"  EXIT LOGIC: Trailing stop loss only + Stop and Reverse (no take profit)")
        print(f"  SMART RE-ENTRY: {'ENABLED' if self.cfg.smart_reentry.enabled else 'DISABLED'}")
        print(f"  Re-entry cooldown: {self.cfg.smart_reentry.cooldown_minutes} minutes")
        print(f"  Max consecutive stops: {self.cfg.smart_reentry.max_consecutive_stops}\n")

        if not self.symbol_states:
            raise RuntimeError("No symbols passed validation")

    def run(self) -> None:
        logger.info("Main loop started (AGGRESSIVE MODE - Trailing Stop only)")
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
                    logger.debug(f"{sym}: position gone – resetting PositionState")
                    state.position_state = PositionState.empty()
                    state.trailing_stop_state = None
            else:
                if not currently_has_position:
                    
                    logger.debug(f"{sym}: new position detected – initialising PositionState")
                    state.position_state = PositionState.from_trade(
                        trade, self.cfg.atr_trailing.enabled
                    )
                    state.trailing_stop_state = None
                else:
                    
                    if state.position_state.ticket != trade.ticket:
                        state.position_state.ticket = trade.ticket
                    if state.position_state.entry_price != trade.entry_price:
                        state.position_state.entry_price = trade.entry_price
                    if state.position_state.volume != trade.volume:
                        state.position_state.volume = trade.volume

        for sym in enabled_symbols:
            try:
                self._process_symbol(sym, self.symbol_states[sym])
            except Exception as exc:
                logger.error(f"Error processing {sym}: {exc}", exc_info=True)

    def _process_symbol(self, symbol: str, state: SymbolState) -> None:
        price = self.order_mgr.get_current_price(symbol)
        if price == 0:
            return

        if state.last_price > 0:
            state.price_change_pct = (price - state.last_price) / state.last_price * 100
        state.current_price = price
        state.last_price = price
        state.reset_daily_counter()

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

        # ============ TRAILING STOP LOSS MANAGEMENT ============
        if state.position_state.has_position:
            stop_moved = state.update_trailing_stop(
                price, result.atr_candle, result.stop_multiplier
            )
            
            if stop_moved and state.position_state.trailing_stop_price:
                logger.info(
                    f"{symbol}: TRAIL UPDATE | "
                    f"stop={state.position_state.trailing_stop_price:.{state.digits}f}"
                )
                
                if state.position_state.ticket:
                    success = self.order_mgr.update_stop_loss(
                        symbol, 
                        state.position_state.ticket, 
                        state.position_state.trailing_stop_price
                    )
                    if success:
                        logger.debug(f"{symbol}: Stop successfully updated on broker")
                    else:
                        logger.warning(f"{symbol}: Failed to update stop on broker - will retry next cycle")
                else:
                    logger.warning(f"{symbol}: Cannot update stop - no ticket number")

            # PRIMARY EXIT: Trailing stop loss triggered
            if state.check_trailing_stop_exit(price):
                logger.warning(
                    f"{symbol}: ATR STOP TRIGGERED | price={price:.{state.digits}f}"
                )
                self._close_position(symbol, state, exit_reason="ATR_STOP", force=True)
                return

        self._execute_decisions(symbol, state, result)

    def _execute_decisions(
        self, symbol: str, state: SymbolState, result: ForecastResult
    ) -> None:
        # Check for Stop and Reverse FIRST (opposite signal)
        if state.should_reverse_to_short() and state.can_close_position():
            logger.info(f"{symbol}: SIGNAL REVERSAL - closing long, opening short")
            self._close_position(symbol, state, exit_reason="SIGNAL_REVERSAL")
            self._open_position(symbol, state, SignalType.SELL, result)
            return

        if state.should_reverse_to_long() and state.can_close_position():
            logger.info(f"{symbol}: SIGNAL REVERSAL - closing short, opening long")
            self._close_position(symbol, state, exit_reason="SIGNAL_REVERSAL")
            self._open_position(symbol, state, SignalType.BUY, result)
            return

        # NO forecast fade exits - trailing stop handles all exits
        # Only enter new positions if no position and signal strong
        if state.should_enter_long() and state.can_open_position():
            self._open_position(symbol, state, SignalType.BUY, result)
        elif state.should_enter_short() and state.can_open_position():
            self._open_position(symbol, state, SignalType.SELL, result)

    def _open_position(
        self,
        symbol: str,
        state: SymbolState,
        signal: SignalType,
        result: ForecastResult,
    ) -> None:
        account = mt5.account_info()
        if not account:
            logger.warning(f"{symbol}: Cannot get account info")
            return

        if account.balance < 50:
            logger.warning(
                f"{symbol}: Account balance {account.balance:.2f} ZAR is below R50. "
                "Aggressive mode active - attempting trade anyway if possible."
            )

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
            logger.warning(f"{symbol}: Volatility Position Sizer returned 0 lots")
            return

        min_lot = state.config.min_volume
        max_lot = state.config.max_volume

        if lots < min_lot:
            logger.warning(f"{symbol}: Lots {lots:.4f} below minimum {min_lot:.4f}")
            return

        lots = max(min_lot, min(lots, max_lot))

        digits = symbol_info.digits

        # Calculate stop loss only - NO take profit
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

        # Log size multiplier if reduced due to stop history
        size_multiplier = state.get_position_size_multiplier()
        if size_multiplier < 1.0:
            logger.info(
                f"{symbol}: Using reduced position size ({size_multiplier:.1f}x) due to "
                f"recent stop loss ({state.consecutive_stops} consecutive stops)"
            )

        logger.info(
            f"{symbol}: AGGRESSIVE ENTRY | tf={result.timeframe} | lots={lots:.4f} | "
            f"candle ATR={result.atr_candle:.{digits}f} | "
            f"stop_mult={result.stop_multiplier}x (stop={stop_distance:.{digits}f}) | "
            f"price={state.current_price:.{digits}f}"
        )

        # Place order with stop loss only - NO take profit
        ticket = self.order_mgr.place_order(
            symbol, signal, lots, "AGGRESSIVE_EWMAC",
            stop_loss=initial_stop,
            take_profit=None,  # NO take profit - let trend run
            entry_atr=result.atr_candle,
        )

        if ticket:
            state.last_open_attempt = time.time()
            state.daily_trades += 1

            state.position_state.ticket = ticket

            if initial_stop:
                state.position_state.trailing_stop_enabled = True
                state.position_state.trailing_stop_price = initial_stop
                state.position_state.entry_atr = result.atr_candle
                state.position_state.stop_multiplier = result.stop_multiplier
                state.position_state.timeframe = result.timeframe
                state.position_state.initial_stop = initial_stop
                
            if signal == SignalType.BUY:
                state.position_state.highest_price_since_entry = state.current_price
            else:
                state.position_state.lowest_price_since_entry = state.current_price
            state.trailing_stop_state = None

            logger.info(
                f"{symbol}: AGGRESSIVE OPENED {signal.value} | lots={lots:.4f} | "
                f"ticket={ticket} | SL={initial_stop:.{digits}f} | NO TP (let trend run)"
            )
        else:
            logger.error(f"{symbol}: Failed to open position")

    def _close_position(
        self,
        symbol: str,
        state: SymbolState,
        exit_reason: str = "MANUAL",
        force: bool = False,
    ) -> None:
        
        if not force and not state.can_close_position():
            return
        state.last_close_attempt = time.time()
        if self.order_mgr.close_position(symbol):
            logger.info(f"{symbol}: position closed | reason={exit_reason}")
            
            state.position_state.ticket = None

    def shutdown(self) -> None:
        logger.info("Shutting down TradingBot…")
        self.order_mgr.shutdown()