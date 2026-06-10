import logging
import os
import sys
import time

from colorama import Fore, Style, init

init(autoreset=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (load_config, get_idm_for_instrument_count, get_recommended_risk_target,
                    TIMEFRAME_META)
from bot import TradingBot
import MetaTrader5 as mt5

def setup_logging(log_to_file: bool = True) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        handlers.append(logging.FileHandler("trading_bot.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

BANNER = f"""{Fore.CYAN}{'═' * 100}
{'VOLATILITY-BASED TREND FOLLOWING SYSTEM':^100}
{'═' * 100}{Style.RESET_ALL}

{Fore.WHITE}Strategy{Style.RESET_ALL}      : Systematic Trend Following (EWMAC 8/16/32/64)
{Fore.WHITE}Position Sizing{Style.RESET_ALL}: Volatility-based: (1/N) × Capital × (T/V) × (F/10) × IDM
{Fore.WHITE}Risk Target{Style.RESET_ALL}   : Portfolio-level annual volatility targeting
{Fore.WHITE}Exit Logic{Style.RESET_ALL}    : Forecast Fade (±3) + ATR Trailing Stop (4× ATR)
{Fore.WHITE}Mode{Style.RESET_ALL}          : Bidirectional – LONG and SHORT
{Fore.WHITE}Timeframe{Style.RESET_ALL}     : H1 only  (ATR daily multiplier ×24)
{Fore.WHITE}Concurrent Pos{Style.RESET_ALL}: Unlimited (full portfolio)

"""

def validate_currency_setup():
    account = mt5.account_info()
    if not account:
        print("Cannot get account info")
        return False

    print(f"\n{Fore.YELLOW}Account Information:{Style.RESET_ALL}")
    print(f"  Account Currency: {account.currency}")
    print(f"  Balance: {account.balance:,.2f} {account.currency}")
    print(f"  Leverage: 1:{account.leverage}")

    if account.currency == "ZAR":
        print(f"\n{Fore.YELLOW}Currency Conversion Check:{Style.RESET_ALL}")
        usd_zar = mt5.symbol_info("USDZAR")
        if usd_zar is None:
            print(f"  {Fore.RED}WARNING: USDZAR not found! Currency conversion will use defaults.{Style.RESET_ALL}")
        else:
            tick = mt5.symbol_info_tick("USDZAR")
            if tick and tick.bid > 0:
                print(f" USD/ZAR rate: {tick.bid:.4f}")
            else:
                print(f"  {Fore.YELLOW} WARNING: Cannot get USD/ZAR tick data, using default{Style.RESET_ALL}")

    return True

def print_config_summary(config) -> None:
    print(f"{Fore.CYAN}{'─' * 80}")
    print(f"  VOLATILITY POSITION SIZING CONFIGURATION")
    print(f"{'─' * 80}{Style.RESET_ALL}")

    enabled_symbols = [sym for sym, cfg in config.symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)

    idm = get_idm_for_instrument_count(active_count)
    recommended_risk = get_recommended_risk_target(active_count)

    print(f"\n{Fore.YELLOW}  PORTFOLIO CONFIGURATION{Style.RESET_ALL}")
    print(f"  Active instruments      : {active_count}")
    print(f"  Asset class             : CRYPTO-ONLY")
    print(f"  Expected positions (N)  : {config.vol_position_sizing.expected_positions}")
    print(f"  IDM (diversification)   : {idm:.2f}")
    print(f"  Risk target (T)         : {config.vol_position_sizing.risk_target_pct*100:.1f}% annual vol")
    print(f"  Recommended risk target : {recommended_risk*100:.1f}% (for {active_count} instruments)")

    print(f"\n{Fore.YELLOW}  POSITION SIZING FORMULA{Style.RESET_ALL}")
    print(f"  notional = (1/N) × Capital × (T/V) × (F/10) × IDM")
    print(f"  where:")
    print(f"    N   = expected positions = {config.vol_position_sizing.expected_positions}")
    print(f"    T   = risk target = {config.vol_position_sizing.risk_target_pct*100:.1f}%")
    print(f"    V   = instrument annual volatility (from daily ATR × √252)")
    print(f"    F   = EWMAC forecast [-20, +20]")
    print(f"    IDM = {idm:.2f}")
    print(f"  Hard cap: max 20% of balance notional per instrument")

    print(f"\n{Fore.YELLOW}  TIMEFRAME & ATR CONFIGURATION{Style.RESET_ALL}")
    print(f"  Primary timeframe      : H1 (all symbols)")
    print(f"  ATR period             : {config.strategy.atr_period} candles")
    tf_meta = TIMEFRAME_META["H1"]
    print(f"  ATR daily multiplier   : {tf_meta['atr_multiplier']}×  (H1 candle ATR → daily)")
    print(f"  Stop multiplier        : {tf_meta['stop_multiplier']}×  (H1 ATR candle stop distance)")
    print(f"  Minimum bars required  : 50 for ATR, 300 for EWMAC")

    print(f"\n{Fore.YELLOW}  INSTRUMENT CONFIGURATION{Style.RESET_ALL}")
    print(f"  {'SYMBOL':<12} {'STATUS':<10} {'TF':<6} "
          f"{'VOL TARGET':<12} {'MIN LOT':<10} {'MAX LOT':<10}")
    print(f"  {'─' * 65}")
    for sym, cfg in config.symbols.items():
        if cfg.enabled:
            print(
                f"  {sym:<12} {Fore.GREEN}ENABLED{Style.RESET_ALL}    "
                f"{cfg.primary_tf:<6} "
                f"{cfg.vol_target_pct*100:.2f}%{'':<6} "
                f"{cfg.min_volume:<10.4f} {cfg.max_volume:<10.1f}"
            )
        else:
            print(f"  {sym:<12} {Fore.RED}DISABLED{Style.RESET_ALL}")

    strat = config.strategy
    print(f"\n{Fore.YELLOW}  EWMAC PARAMETERS{Style.RESET_ALL}")
    print(f"  Speeds               : 8/32, 16/64, 32/128, 64/256")
    print(f"  Entry threshold      : ±{strat.entry_threshold}")
    print(f"  Exit threshold       : ±{strat.exit_threshold}")
    print(f"  FDM (forecast adj)   : {strat.fdm}")
    print(f"  Forecast cap         : ±{strat.cap_max}")

    atr_trail = config.atr_trailing
    print(f"\n{Fore.YELLOW}  ATR TRAILING STOP{Style.RESET_ALL}")
    print(f"  Enabled              : {atr_trail.enabled}")
    print(f"  Multiple             : {tf_meta['stop_multiplier']}× candle ATR (H1 timeframe)")
    print(f"  ATR Period           : {atr_trail.atr_period}")

    print(f"\n{Fore.YELLOW}  RISK MANAGEMENT{Style.RESET_ALL}")
    print(f"  Max concurrent pos   : Unlimited (full portfolio)")
    print(f"  Max notional/trade   : 20% of account balance (configurable)")
    print(f"  Max margin/trade     : 10% of free margin (configurable)")
    print(f"  Portfolio volatility : {config.vol_position_sizing.risk_target_pct*100:.1f}% target")

    print(f"{Fore.CYAN}{'─' * 80}{Style.RESET_ALL}\n")

def main() -> None:
    print(BANNER)

    if not mt5.initialize():
        print("Failed to initialize MT5")
        sys.exit(1)

    try:
        if not validate_currency_setup():
            print("Currency validation failed")
            sys.exit(1)
    finally:
        mt5.shutdown()

    mt5.initialize()
    config = load_config()
    setup_logging(config.log_to_file)
    logger = logging.getLogger(__name__)

    print_config_summary(config)
    time.sleep(2)

    bot = None
    try:
        bot = TradingBot(config)
        bot.run()
    except ConnectionError as exc:
        logger.critical(f"Connection failed: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Keyboard interrupt received{Style.RESET_ALL}")
    except Exception as exc:
        logger.critical(f"Fatal error: {exc}", exc_info=True)
    finally:
        if bot:
            bot.shutdown()
        mt5.shutdown()

    print(f"\n{Fore.GREEN}Bot stopped cleanly.{Style.RESET_ALL}")

if __name__ == "__main__":
    main()