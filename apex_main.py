# apex_main.py
import logging
import os
import sys
import time

from colorama import Fore, Style, init

init(autoreset=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apex_config import load_apex_config, get_idm_for_instrument_count, TIMEFRAME_META
from apex_bot import ApexTradingBot
import MetaTrader5 as mt5


def setup_logging(log_to_file: bool = True) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        handlers.append(logging.FileHandler("apex_trading_bot.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


APEX_BANNER = f"""
{Fore.RED}{'═' * 100}
{Fore.YELLOW} APEX SYSTEM - H1 TIMEFRAME - EWMAC + BREAKOUT {Style.RESET_ALL}
{Fore.CYAN}{'═' * 100}{Style.RESET_ALL}

{Fore.RED}{Style.BRIGHT}!!! ULTRA AGGRESSIVE MODE - H1 TIMEFRAME - HIGHEST RISK LEVEL !!!{Style.RESET_ALL}
{Fore.YELLOW}Expected drawdown: Only use risk capital! This is a high-risk strategy.{Style.RESET_ALL}

{Fore.WHITE}Strategy{Style.RESET_ALL}      : APEX Ultra Systematic Trend Following + Breakout
{Fore.WHITE}Assets{Style.RESET_ALL}        : {Fore.RED}Multi-Crypto Portfolio (20+ symbols){Style.RESET_ALL}
{Fore.WHITE}Timeframe{Style.RESET_ALL}     : {Fore.RED}H1 (1 Hour) - Aggressive trend following{Style.RESET_ALL}
{Fore.WHITE}Position Sizing{Style.RESET_ALL}: Volatility-based: (1/N) × Capital × (T/V) × (F/8) × IDM
{Fore.WHITE}Risk Target{Style.RESET_ALL}   : {Fore.RED}90% annual volatility (dynamic per instrument count){Style.RESET_ALL}
{Fore.WHITE}Entry Threshold{Style.RESET_ALL}: {Fore.RED}±1.5 (low entry){Style.RESET_ALL}
{Fore.WHITE}Exit Method{Style.RESET_ALL}    : {Fore.RED}Trailing Stop (2.2× ATR) + Stop and Reverse{Style.RESET_ALL}
{Fore.WHITE}Max Position Size{Style.RESET_ALL}: {Fore.RED}95% of balance per trade (increased from 85%){Style.RESET_ALL}
{Fore.WHITE}Max Margin Usage{Style.RESET_ALL}: {Fore.RED}75% per trade (increased from 60%){Style.RESET_ALL}
{Fore.WHITE}IDM (Leverage){Style.RESET_ALL} : {Fore.RED}Dynamic up to 5.0x (increased){Style.RESET_ALL}
{Fore.WHITE}Max Concurrent Positions{Style.RESET_ALL}: {Fore.RED}30 (increased){Style.RESET_ALL}
{Fore.WHITE}Poll Interval{Style.RESET_ALL} : 30 seconds

{Fore.RED}{Style.BRIGHT}Press Ctrl+C to stop - This WILL be volatile!{Style.RESET_ALL}

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

    if account.balance < 500:  # Increased minimum for H1
        print(f"\n{Fore.RED}{Style.BRIGHT} LOW BALANCE WARNING {Style.RESET_ALL}")
        print(f"  Current balance: R{account.balance:.2f}")
        print(f"  Minimum recommended: R500 (higher for H1)")

        if account.balance < 250:
            print(f"\n{Fore.RED}CRITICAL: Balance below minimum requirement for H1. Trading may fail.{Style.RESET_ALL}")
            response = input("Continue anyway? (yes/no): ")
            if response.lower() != 'yes':
                return False

    if account.currency == "ZAR":
        print(f"\n{Fore.YELLOW}Currency Check:{Style.RESET_ALL}")
        usd_zar = mt5.symbol_info("USDZAR")
        if usd_zar is None:
            print(f"  {Fore.RED}WARNING: USDZAR not found!{Style.RESET_ALL}")
        else:
            tick = mt5.symbol_info_tick("USDZAR")
            if tick and tick.bid > 0:
                print(f" USD/ZAR rate: {tick.bid:.4f}")

    return True


def print_apex_config_summary(config) -> None:
    print(f"{Fore.RED}{'─' * 80}")
    print(f"APEX SYSTEM CONFIGURATION SUMMARY - H1 TIMEFRAME - HIGH RISK")
    print(f"{'─' * 80}{Style.RESET_ALL}")

    enabled_symbols = [sym for sym, cfg in config.symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)

    print(f"\n{Fore.YELLOW}  PORTFOLIO CONFIGURATION{Style.RESET_ALL}")
    print(f"  Active instruments      : {active_count}")
    print(f"  Asset class             : CRYPTO (Diversified Portfolio)")
    print(f"  Expected positions (N)  : {config.vol_position_sizing.expected_positions}")
    print(f"  IDM (diversification)   : {Fore.RED}{get_idm_for_instrument_count(active_count):.2f}x{Style.RESET_ALL}")
    print(f"  Risk target (T)         : {Fore.RED}{config.vol_position_sizing.risk_target_pct*100:.0f}%{Style.RESET_ALL} annual vol")
    print(f"  Max concurrent positions: {Fore.RED}{active_count}{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}  STRATEGY CONFIGURATION{Style.RESET_ALL}")
    print(f"  Primary strategy        : EWMAC + Breakout")
    print(f"  EWMAC weight            : {Fore.RED}{config.strategy.ewmac_weight*100:.0f}%{Style.RESET_ALL}")
    print(f"  Breakout weight         : {Fore.RED}{config.strategy.breakout_weight*100:.0f}%{Style.RESET_ALL}")
    print(f"  EWMAC speeds            : {Fore.RED}8/32, 16/64, 32/128, 64/256{Style.RESET_ALL}")
    print(f"  Breakout periods        : {Fore.RED}160, 320, 640, 1280 bars{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}  ENTRY/EXIT CONFIGURATION{Style.RESET_ALL}")
    print(f"  Entry threshold         : {Fore.RED}±{config.strategy.entry_threshold}{Style.RESET_ALL}")
    print(f"  Primary timeframe       : {Fore.RED}H1 (1 Hour){Style.RESET_ALL}")
    print(f"  Stop multiplier         : {Fore.RED}{config.atr_trailing.multiple}× ATR{Style.RESET_ALL}")
    print(f"  ATR period              : {Fore.RED}{config.strategy.atr_period}{Style.RESET_ALL}")
    print(f"  Forecast cap            : ±{config.strategy.cap_max}")
    print(f"  FDM (forecast mult)     : {config.strategy.fdm}")
    print(f"  Price drift tolerance   : {Fore.RED}1.5% base (adjusts by symbol){Style.RESET_ALL}")
    print(f"  Re-entry cooldown       : {Fore.RED}30 min after stop, 15 min after reversal{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}  POSITION SIZING (ULTRA AGGRESSIVE - H1){Style.RESET_ALL}")
    print(f"  Max notional per trade  : {Fore.RED}95% of balance (was 85%){Style.RESET_ALL}")
    print(f"  Max margin per trade    : {Fore.RED}75% of free margin (was 60%){Style.RESET_ALL}")
    print(f"  Vol target per symbol   : {Fore.RED}1.00% (was 0.80%){Style.RESET_ALL}")
    print(f"  Formula                 : (1/N) × Capital × (T/V) × (F/8) × IDM")

    print(f"\n{Fore.YELLOW}  ACTIVE INSTRUMENTS{Style.RESET_ALL}")
    print(f"  {'SYMBOL':<12} {'TIMEFRAME':<10} {'VOL TARGET':<12} {'DAILY LIMIT':<12}")
    print(f"  {'─' * 50}")
    for sym, cfg in config.symbols.items():
        if cfg.enabled:
            print(f"  {sym:<12} {cfg.primary_tf:<10} {cfg.vol_target_pct*100:.2f}%{'':<6} {cfg.max_daily_trades} trades")

    print(f"\n{Fore.RED}{Style.BRIGHT}  EXPECTED OUTCOMES:{Style.RESET_ALL}")
    print(f"  • Win rate             : 30-35% (high risk/reward)")
    print(f"  • Avg trade duration   : 1-4 hours (H1 timeframe)")
    print(f"  • Exit method          : Trailing stop (2.2× ATR) + Signal reversal")
    print(f"  • Position sizing      : Up to 95% of balance per trade")

    print(f"{Fore.RED}{'─' * 80}{Style.RESET_ALL}")

    print(f"\n{Fore.YELLOW}Press Enter to start APEX H1 trading (Ctrl+C to cancel)...{Style.RESET_ALL}")
    input()


def main() -> None:
    print(APEX_BANNER)

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
    config = load_apex_config()
    setup_logging(config.log_to_file)
    logger = logging.getLogger(__name__)

    print_apex_config_summary(config)
    time.sleep(2)

    bot = None
    try:
        bot = ApexTradingBot(config)
        bot.run()
    except ConnectionError as exc:
        logger.critical(f"Connection failed: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Keyboard interrupt received - shutting down...{Style.RESET_ALL}")
    except Exception as exc:
        logger.critical(f"Fatal error: {exc}", exc_info=True)
    finally:
        if bot:
            bot.shutdown()
        mt5.shutdown()

    print(f"\n{Fore.GREEN}APEX Bot stopped cleanly.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Please check apex_trading_bot.log for detailed trade history.{Style.RESET_ALL}")

if __name__ == "__main__":
    main()