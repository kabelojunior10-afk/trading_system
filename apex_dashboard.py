# apex_dashboard.py 
import os
from datetime import datetime
from typing import Dict

from colorama import Fore, Style, init

from apex_symbol_state import ApexSymbolState
from signal import PositionType

init(autoreset=True)


class ApexDashboard:

    def __init__(self):
        # EWMAC speed keys
        self.speed_keys = ["ewmac_8_32", "ewmac_16_64", "ewmac_32_128", "ewmac_64_256"]
        self.speed_labels = ["8/32", "16/64", "32/128", "64/256"]

        # Breakout speed keys - FIXED to match actual keys from strategy
        self.breakout_keys = ["breakout_160", "breakout_320", "breakout_640", "breakout_1280"]
        self.breakout_labels = ["B160", "B320", "B640", "B1280"]

    def clear_screen(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    @staticmethod
    def _forecast_color(v: float) -> str:
        if v >= 20: return Fore.LIGHTGREEN_EX
        if v >= 10: return Fore.GREEN
        if v >= 5: return Fore.LIGHTGREEN_EX
        if v <= -20: return Fore.LIGHTRED_EX
        if v <= -10: return Fore.RED
        if v <= -5: return Fore.LIGHTRED_EX
        return Fore.YELLOW

    def update(self, account_info, symbol_states: Dict[str, ApexSymbolState]) -> None:
        self.clear_screen()

        print(f"{Fore.YELLOW} APEX SYSTEM {Style.RESET_ALL}")
        print(f"{Fore.WHITE}{'─' * 140}{Style.RESET_ALL}")
        
        if account_info:
            balance = account_info.balance
            print(f"  Balance: R{balance:,.2f}")
            
        print(f"{Fore.WHITE}{'─' * 140}{Style.RESET_ALL}")

        # Header with EWMAC and breakout columns
        header = (f"  {'SYMBOL':<8} {'PRICE':>12} {'FCST':>8} {'TREND':<8} "
                  f"{'POS':<6} {'ATR':>10} {'STOP':>10} {'DIST%':>6}  "
                  f"{'EWMAC':>8} {'BRKOUT':>8} ")
        for label in self.speed_labels:
            header += f"{label:>6}  "
        for label in self.breakout_labels:
            header += f"{label:>6}  "
        print(header)
        print(f"{Fore.WHITE}{'─' * 140}{Style.RESET_ALL}")

        for symbol, state in symbol_states.items():
            try:
                price = getattr(state, 'current_price', 0)
                forecast = getattr(state, 'current_forecast', 0)
                trend = getattr(state, 'current_trend', 'NEUTRAL')
                if trend and len(trend) > 7:
                    trend = trend[:7]
                elif not trend:
                    trend = "NEUTRAL"
                
                # Position display
                pos = "---"
                if hasattr(state, 'position_state') and state.position_state:
                    if state.position_state.has_position:
                        if state.position_state.position_type:
                            pos = "LONG" if state.position_state.position_type == PositionType.LONG else "SHORT"
                
                atr = getattr(state, 'atr_candle', 0)
                
                stop = 0
                if hasattr(state, 'position_state') and state.position_state:
                    stop = getattr(state.position_state, 'trailing_stop_price', 0) or 0
                
                dist_str = "---"
                if pos != "---" and stop > 0 and price > 0:
                    if pos == "LONG":
                        dist_pct = (price - stop) / price * 100
                    else:
                        dist_pct = (stop - price) / price * 100
                    if dist_pct > 0:
                        dist_str = f"{dist_pct:.1f}%"
                    else:
                        dist_str = f"{dist_pct:.1f}%"

                # EWMAC speed forecasts
                speed_forecasts = getattr(state, 'speed_forecasts', {})
                speed_values = []
                for key in self.speed_keys:
                    val = speed_forecasts.get(key, 0.0)
                    if val is None:
                        val = 0.0
                    color = self._forecast_color(val)
                    speed_values.append(f"{color}{val:>6.1f}{Style.RESET_ALL}")

                # Breakout speed forecasts - FIXED to use correct keys
                breakout_values = []
                for key in self.breakout_keys:
                    val = speed_forecasts.get(key, 0.0)
                    if val is None:
                        val = 0.0
                    color = self._forecast_color(val)
                    breakout_values.append(f"{color}{val:>6.1f}{Style.RESET_ALL}")

                # Individual component forecasts
                ewmac_fcst = getattr(state, 'ewmac_forecast', 0.0)
                breakout_fcst = getattr(state, 'breakout_forecast', 0.0)

                # Format price based on symbol
                if symbol in ["BTCUSD"]:
                    price_str = f"${price:>11,.0f}"
                elif symbol in ["ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD", "BNBUSD", "AVAXUSD", "LINKUSD", "AAVEUSD"]:
                    price_str = f"${price:>11,.2f}"
                else:
                    price_str = f"${price:>11,.4f}"

                row = (f"  {symbol:<8} {price_str} "
                       f"{self._forecast_color(forecast)}{forecast:>+8.1f}{Style.RESET_ALL} "
                       f"{trend:<8} {pos:<6} {atr:>10.4f} {stop:>10.4f} {dist_str:>6}  "
                       f"{self._forecast_color(ewmac_fcst)}{ewmac_fcst:>+8.1f}{Style.RESET_ALL} "
                       f"{self._forecast_color(breakout_fcst)}{breakout_fcst:>+8.1f}{Style.RESET_ALL} ")
                row += "".join([f"{v}  " for v in speed_values])
                row += "".join([f"{v}  " for v in breakout_values])
                
                # Highlight active positions
                if pos != "---":
                    print(f"{Fore.CYAN}{row}{Style.RESET_ALL}")
                else:
                    print(row)

            except Exception as e:
                print(f"  {Fore.RED}{symbol:<8} ERROR: {str(e)[:50]}{Style.RESET_ALL}")

        print(f"{Fore.WHITE}{'─' * 140}{Style.RESET_ALL}")
        
        # Count active (enabled) symbols and positions
        enabled_symbols = len(symbol_states)
        positions = sum(1 for s in symbol_states.values() 
                       if hasattr(s, 'position_state') and s.position_state and s.position_state.has_position)
        
        # Get max concurrent positions from config if available
        max_positions = 30
        try:
            from apex_config import load_apex_config
            config = load_apex_config()
            max_positions = config.max_concurrent_positions
        except:
            pass
        
        print(f"{Style.DIM}  Enabled: {enabled_symbols}  |  Positions: {positions}/{max_positions}  |  "
              f"Last Update: {datetime.now().strftime('%H:%M:%S')}  |  Ctrl+C to stop{Style.RESET_ALL}")