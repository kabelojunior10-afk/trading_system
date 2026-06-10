import os
from datetime import datetime
from typing import Dict, List, Optional

from colorama import Fore, Style, init

from symbol_state import SymbolState

init(autoreset=True)

COL = {"symbol":   10, "price":    12, "forecast":  7, "trend":     8,
       "signal":    6, "position": 6, "atr":       8, "stop":     10,
       "dist":      6, "speed":    7}

SEP  = Fore.WHITE + Style.DIM + "─" * 130 + Style.RESET_ALL
DSEP = Fore.WHITE + Style.DIM + "═" * 130 + Style.RESET_ALL

class ProfessionalDashboard:

    def clear_screen(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    @staticmethod
    def _forecast_color(v: float) -> str:
        if v >= 10:  return Fore.LIGHTGREEN_EX
        if v >= 5:   return Fore.GREEN
        if v > 0:    return Fore.LIGHTGREEN_EX + Style.DIM
        if v <= -10: return Fore.LIGHTRED_EX
        if v <= -5:  return Fore.RED
        if v < 0:    return Fore.LIGHTRED_EX + Style.DIM
        return Fore.YELLOW

    @staticmethod
    def _trend_color(t: str) -> str:
        if t == "BULLISH":
            return Fore.GREEN
        elif t == "BEARISH":
            return Fore.RED
        return Fore.YELLOW

    @staticmethod
    def _signal_color(s: str) -> str:
        if s == "BUY":
            return Fore.GREEN
        elif s == "SELL":
            return Fore.RED
        return Fore.YELLOW

    @staticmethod
    def _position_color(p: str) -> str:
        if p == "LONG":
            return Fore.GREEN
        elif p == "SHORT":
            return Fore.RED
        return Fore.WHITE

    @staticmethod
    def _price_color(price_change: float) -> str:
        return Fore.GREEN if price_change >= 0 else Fore.RED

    @staticmethod
    def _fmt_price(value: float, digits: int = 2) -> str:
        if value <= 0:
            return "—"
        try:
            return f"{value:.{digits}f}"
        except:
            return f"{value:.2f}"

    @staticmethod
    def _format_forecast(forecast: float, decimals: int = 2) -> str:
        if forecast == 0:
            return "0.00"
        try:
            return f"+{forecast:.{decimals}f}" if forecast > 0 else f"{forecast:.{decimals}f}"
        except:
            return f"{forecast:.2f}"

    def _build_header(self) -> str:
        lines = [
            DSEP,
            f"{Style.DIM}{Fore.WHITE}{'VOLATILITY-BASED TREND FOLLOWING SYSTEM':^130}{Style.RESET_ALL}",
            SEP,
        ]
        return "\n".join(lines)

    def _build_table_header(self) -> str:
        header = (
            f"  {Fore.WHITE + Style.BRIGHT}{'SYMBOL':<{COL['symbol']}}{Style.RESET_ALL}"
            f"{Fore.WHITE + Style.BRIGHT}{'PRICE':>{COL['price']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'FCST':>{COL['forecast']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'TREND':<{COL['trend']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'SIG':<{COL['signal']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'POS':<{COL['position']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'ATR':>{COL['atr']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'TRAIL STOP':>{COL['stop']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'DIST%':>{COL['dist']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'8/32':>{COL['speed']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'16/64':>{COL['speed']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'32/128':>{COL['speed']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'64/256':>{COL['speed']}}{Style.RESET_ALL}"
        )
        return f"{header}\n{SEP}"

    def _build_symbol_row(self, symbol: str, state: SymbolState) -> str:
        try:
            digits = getattr(state, "digits", 2)
            price = state.current_price
            price_change = state.price_change_pct
            forecast = state.current_forecast
            trend = state.current_trend
            signal = state.current_signal.value
            
            has_position = state.position_state.has_position
            
            if has_position:
                
                symbol_color = Fore.LIGHTYELLOW_EX + Style.BRIGHT
            else:
                symbol_color = Fore.CYAN

            forecast_str = self._format_forecast(forecast, 2)

            if state.position_state.has_position and state.position_state.position_type:
                pos = state.position_state.position_type.value
                pos_color = self._position_color(pos)
            else:
                pos = "—"
                pos_color = Fore.WHITE

            atr = state.atr
            atr_str = self._fmt_price(atr, digits) if atr > 0 else "—"

            stop = state.position_state.trailing_stop_price
            if stop and state.position_state.has_position:
                stop_str = self._fmt_price(stop, digits)
            else:
                stop_str = "—"

            dist_pct = state.get_distance_to_stop_percent()
            if dist_pct is not None:
                dist_str = f"{dist_pct:.1f}%"
                if dist_pct > 5:
                    dist_color = Fore.GREEN
                elif dist_pct > 2:
                    dist_color = Fore.YELLOW
                else:
                    dist_color = Fore.RED
            else:
                dist_str = "—"
                dist_color = Fore.WHITE

            speed_order = [
                ("ewmac_8_32",   "8/32"),
                ("ewmac_16_64",  "16/64"),
                ("ewmac_32_128", "32/128"),
                ("ewmac_64_256", "64/256"),
            ]
            speed_values = []
            for key, _ in speed_order:
                val = state.speed_forecasts.get(key, 0.0)
                val_str = self._format_forecast(val, 1)
                color = self._forecast_color(val)
                speed_values.append(f"{color}{val_str:>{COL['speed']}}{Style.RESET_ALL}")

            try:
                price_str = self._fmt_price(price, digits)
            except:
                price_str = f"{price:.2f}"

            position_indicator = " " * 2  

            return (
                f"  {symbol_color}{position_indicator}{symbol:<{COL['symbol']-2}}{Style.RESET_ALL}"
                f"{self._price_color(price_change)}{price_str:>{COL['price']}}{Style.RESET_ALL}  "
                f"{self._forecast_color(forecast)}{forecast_str:>{COL['forecast']}}{Style.RESET_ALL}  "
                f"{self._trend_color(trend)}{trend:<{COL['trend']}}{Style.RESET_ALL}  "
                f"{self._signal_color(signal)}{signal:<{COL['signal']}}{Style.RESET_ALL}  "
                f"{pos_color}{pos:<{COL['position']}}{Style.RESET_ALL}  "
                f"{Fore.CYAN}{atr_str:>{COL['atr']}}{Style.RESET_ALL}  "
                f"{Fore.MAGENTA}{stop_str:>{COL['stop']}}{Style.RESET_ALL}  "
                f"{dist_color}{dist_str:>{COL['dist']}}{Style.RESET_ALL}  "
                f"{' '.join(speed_values)}"
            )
        except Exception as e:
            return f"  {Fore.RED}{symbol:<{COL['symbol']}} {'ERROR':>{COL['price']}}{Style.RESET_ALL}"

    def _build_dashboard(self, symbol_states: Dict[str, SymbolState]) -> str:
        lines = [self._build_header(), self._build_table_header()]
    
        sorted_symbols = sorted(
            symbol_states.items(),
            key=lambda x: (not x[1].position_state.has_position, x[0])
        )
        
        for symbol, state in sorted_symbols:
            lines.append(self._build_symbol_row(symbol, state))
            lines.append(SEP)
        
        positions_count = sum(1 for s in symbol_states.values() if s.position_state.has_position)
        
        lines.append(
            f"{Style.DIM}{Fore.WHITE}"
            f"  Positions: {positions_count}  |  "
            f"Last Updated: {datetime.now().strftime('%H:%M:%S')}  |  "
            f"Ctrl+C to stop"
            f"{Style.RESET_ALL}"
        )
        return "\n".join(lines)

    def update(self, account_info, symbol_states: Dict[str, SymbolState]) -> None:
        self.clear_screen()
        print(self._build_dashboard(symbol_states))