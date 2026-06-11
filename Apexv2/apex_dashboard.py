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
        self.speed_keys = ["ewmac_2_8", "ewmac_4_16", "ewmac_8_32", "ewmac_16_64"]
        self.speed_labels = ["2/8", "4/16", "8/32", "16/64"]

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

        print(f"{Fore.RED}{'═' * 100}")
        print(f"{Fore.YELLOW} AMARE CAPITAL MANAGEMENT {Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'═' * 100}{Style.RESET_ALL}")

        
        if account_info:
            balance = account_info.balance
            print(f"  Balance: R{balance:,.2f}")

        print(f"{Fore.WHITE}{'─' * 100}{Style.RESET_ALL}")

        header = (f"  {'SYMBOL':<8} {'PRICE':>12} {'FCST':>8} {'TREND':<8} "
                  f"{'POS':<6} {'ATR':>10} {'STOP':>10} {'DIST%':>6}  ")
        for label in self.speed_labels:
            header += f"{label:>6}  "
        print(header)
        print(f"{Fore.WHITE}{'─' * 100}{Style.RESET_ALL}")

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
                        else:
                            pos = "LONG" if getattr(state.position_state, 'position_type', None) == PositionType.LONG else "SHORT"
                
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

                speed_forecasts = getattr(state, 'speed_forecasts', {})
                speed_values = []
                for key in self.speed_keys:
                    val = speed_forecasts.get(key, 0.0)
                    if val is None:
                        val = 0.0
                    color = self._forecast_color(val)
                    speed_values.append(f"{color}{val:>6.1f}{Style.RESET_ALL}")

                if symbol == "BTCUSD":
                    price_str = f"${price:>11,.0f}"
                else:
                    price_str = f"${price:>11,.2f}"

                row = (f"  {symbol:<8} {price_str} "
                       f"{self._forecast_color(forecast)}{forecast:>+8.1f}{Style.RESET_ALL} "
                       f"{trend:<8} {pos:<6} {atr:>10.2f} {stop:>10.2f} {dist_str:>6}  ")
                row += "".join([f"{v}  " for v in speed_values])
                
                if pos != "---":
                    print(f"{Fore.CYAN}{row}{Style.RESET_ALL}")
                else:
                    print(row)

            except Exception as e:
                print(f"  {Fore.RED}{symbol:<8} ERROR: {str(e)[:50]}{Style.RESET_ALL}")

        print(f"{Fore.WHITE}{'─' * 100}{Style.RESET_ALL}")
        
        positions = 0
        for s in symbol_states.values():
            if hasattr(s, 'position_state') and s.position_state and s.position_state.has_position:
                positions += 1
        print(f"{Style.DIM}  Positions: {positions}/2  |  "
              f"Last Update: {datetime.now().strftime('%H:%M:%S')}  |  Ctrl+C to stop{Style.RESET_ALL}")
