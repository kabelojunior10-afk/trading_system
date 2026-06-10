import os
from datetime import datetime
from typing import Dict, List, Optional, Any

from colorama import Fore, Style, init

from symbol_state import SymbolState

init(autoreset=True)

# Dynamic column widths - will be adjusted based on number of speeds
BASE_COL = {"symbol": 10, "price": 12, "forecast": 7, "trend": 8,
           "signal": 6, "position": 6, "atr": 8, "stop": 10,
           "dist": 6}

SEP  = Fore.WHITE + Style.DIM + "─" * 130 + Style.RESET_ALL
DSEP = Fore.WHITE + Style.DIM + "═" * 130 + Style.RESET_ALL

class ProfessionalDashboard:
    
    def __init__(self):
        """Initialize dashboard with dynamic speed detection."""
        self.speed_labels: List[str] = []
        self.speed_keys: List[str] = []
        self.column_widths = BASE_COL.copy()
        self._load_speed_configuration()

    def _load_speed_configuration(self) -> None:
        """Load speed configurations dynamically from config."""
        try:
            from config import StrategyConfig
            
            # Create a default config to get speeds
            cfg = StrategyConfig()
            self.speeds = cfg.speeds
            
            # Extract keys and labels
            self.speed_keys = []
            self.speed_labels = []
            
            for speed in self.speeds:
                self.speed_keys.append(speed.name)
                self.speed_labels.append(f"{speed.fast}/{speed.slow}")
            
            # Set speed column width (7 characters per speed)
            if self.speed_keys:
                self.column_widths["speed"] = 7
                
            print(f"[Dashboard] Loaded {len(self.speeds)} speeds: {self.speed_labels}")
            
        except Exception as e:
            print(f"[Dashboard] Warning: Could not load speeds from config: {e}")
            # Fallback defaults
            self.speed_keys = ["ewmac_8_32", "ewmac_16_64", "ewmac_32_128"]
            self.speed_labels = ["8/32", "16/64", "32/128"]
            self.column_widths["speed"] = 7

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
    
    def _get_dynamic_width(self) -> int:
        """Calculate total dashboard width dynamically."""
        total = sum(self.column_widths.values()) + 6  # +6 for spaces between columns
        # Add space for each speed column
        total += len(self.speed_keys) * (self.column_widths.get("speed", 7) + 1)
        return max(total, 130)

    def _build_header(self) -> str:
        lines = [
            DSEP,
            f"{Style.DIM}{Fore.WHITE}{'VOLATILITY-BASED TREND FOLLOWING SYSTEM':^{self._get_dynamic_width()}}{Style.RESET_ALL}",
            SEP,
        ]
        return "\n".join(lines)

    def _build_table_header(self) -> str:
        """Build table header with dynamic speed columns."""
        header = (
            f"  {Fore.WHITE + Style.BRIGHT}{'SYMBOL':<{self.column_widths['symbol']}}{Style.RESET_ALL}"
            f"{Fore.WHITE + Style.BRIGHT}{'PRICE':>{self.column_widths['price']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'FCST':>{self.column_widths['forecast']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'TREND':<{self.column_widths['trend']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'SIG':<{self.column_widths['signal']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'POS':<{self.column_widths['position']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'ATR':>{self.column_widths['atr']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'TRAIL STOP':>{self.column_widths['stop']}}{Style.RESET_ALL}  "
            f"{Fore.WHITE + Style.BRIGHT}{'DIST%':>{self.column_widths['dist']}}{Style.RESET_ALL}  "
        )
        
        # Add speed columns dynamically
        for label in self.speed_labels:
            header += f"{Fore.WHITE + Style.BRIGHT}{label:>{self.column_widths['speed']}}{Style.RESET_ALL}  "
        
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

            # Build speed values dynamically from state.speed_forecasts
            speed_values = []
            for key in self.speed_keys:
                val = state.speed_forecasts.get(key, 0.0)
                val_str = self._format_forecast(val, 1)
                color = self._forecast_color(val)
                speed_values.append(f"{color}{val_str:>{self.column_widths['speed']}}{Style.RESET_ALL}")

            try:
                price_str = self._fmt_price(price, digits)
            except:
                price_str = f"{price:.2f}"

            position_indicator = " " * 2  

            # Build the row
            row = (
                f"  {symbol_color}{position_indicator}{symbol:<{self.column_widths['symbol']-2}}{Style.RESET_ALL}"
                f"{self._price_color(price_change)}{price_str:>{self.column_widths['price']}}{Style.RESET_ALL}  "
                f"{self._forecast_color(forecast)}{forecast_str:>{self.column_widths['forecast']}}{Style.RESET_ALL}  "
                f"{self._trend_color(trend)}{trend:<{self.column_widths['trend']}}{Style.RESET_ALL}  "
                f"{self._signal_color(signal)}{signal:<{self.column_widths['signal']}}{Style.RESET_ALL}  "
                f"{pos_color}{pos:<{self.column_widths['position']}}{Style.RESET_ALL}  "
                f"{Fore.CYAN}{atr_str:>{self.column_widths['atr']}}{Style.RESET_ALL}  "
                f"{Fore.MAGENTA}{stop_str:>{self.column_widths['stop']}}{Style.RESET_ALL}  "
                f"{dist_color}{dist_str:>{self.column_widths['dist']}}{Style.RESET_ALL}  "
            )
            
            # Add speed values
            row += "".join(f"{val}  " for val in speed_values)
            
            return row
            
        except Exception as e:
            return f"  {Fore.RED}{symbol:<{self.column_widths['symbol']}} {'ERROR':>{self.column_widths['price']}}{Style.RESET_ALL}"

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
            f"Speeds: {' + '.join(self.speed_labels)}  |  "
            f"Last Updated: {datetime.now().strftime('%H:%M:%S')}  |  "
            f"Ctrl+C to stop"
            f"{Style.RESET_ALL}"
        )
        return "\n".join(lines)

    def update(self, account_info, symbol_states: Dict[str, SymbolState]) -> None:
        self.clear_screen()
        print(self._build_dashboard(symbol_states))