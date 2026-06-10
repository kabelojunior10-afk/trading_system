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
        handlers.append(logging.FileHandler("aggressive_trading_bot.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )

BANNER = f"""{Fore.RED}{'═' * 100}
{Fore.YELLOW}⚠️  AGGRESSIVE R250 TRADING SYSTEM - HIGH RISK MODE  ⚠️{Style.RESET_ALL}
{Fore.CYAN}{'═' * 100}{Style.RESET_ALL}

{Fore.RED}{Style.BRIGHT}!!! WARNING - AGGRESSIVE CONFIGURATION ACTIVE !!!{Style.RESET_ALL}
{Fore.YELLOW}This configuration is designed for a R250 account with HIGH RISK tolerance.{Style.RESET_ALL}
{Fore.YELLOW}Expected drawdown: 50-70%. Only use capital you can afford to lose completely.{Style.RESET_ALL}

{Fore.WHITE}Strategy{Style.RESET_ALL}      : Aggressive Systematic Trend Following (EWMAC 4/16/8/32/16/64/32/128)
{Fore.WHITE}Position Sizing{Style.RESET_ALL}: Volatility-based: (1/N) × Capital × (T/V) × (F/10) × IDM
{Fore.WHITE}Risk Target{Style.RESET_ALL}   : {Fore.RED}35% annual volatility (conservative: 12%){Style.RESET_ALL}
{Fore.WHITE}Entry Threshold{Style.RESET_ALL}: {Fore.RED}±3 (conservative: ±7){Style.RESET_ALL}
{Fore.WHITE}Exit Method{Style.RESET_ALL}    : {Fore.RED}Trailing Stop Loss + Stop and Reverse (NO take profit){Style.RESET_ALL}
{Fore.WHITE}Stop Distance{Style.RESET_ALL}  : {Fore.RED}2.5× ATR (conservative: 4× ATR){Style.RESET_ALL}
{Fore.WHITE}Timeframe{Style.RESET_ALL}     : {Fore.RED}M15 (15 minute) - More frequent trades{Style.RESET_ALL}
{Fore.WHITE}Max Positions{Style.RESET_ALL} : 3 concurrent max
{Fore.WHITE}Daily Trades{Style.RESET_ALL}  : 5 max per symbol
{Fore.WHITE}Poll Interval{Style.RESET_ALL} : 30 seconds

{Fore.RED}{Style.BRIGHT}Press Ctrl+C to stop - Monitor closely!{Style.RESET_ALL}

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

    if account.balance < 250:
        print(f"\n{Fore.RED}{Style.BRIGHT}⚠️  LOW BALANCE WARNING ⚠️{Style.RESET_ALL}")
        print(f"  Current balance: R{account.balance:.2f}")
        print(f"  Minimum recommended for aggressive mode: R250")
        print(f"  You may face margin restrictions or rapid account depletion.")
        
        if account.balance < 100:
            print(f"\n{Fore.RED}CRITICAL: Balance below R100. Trading may not be possible.{Style.RESET_ALL}")
            response = input("Continue anyway? (yes/no): ")
            if response.lower() != 'yes':
                return False

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
    print(f"{Fore.RED}{'─' * 80}")
    print(f"  AGGRESSIVE R250 CONFIGURATION SUMMARY")
    print(f"{'─' * 80}{Style.RESET_ALL}")

    enabled_symbols = [sym for sym, cfg in config.symbols.items() if cfg.enabled]
    active_count = len(enabled_symbols)

    idm = get_idm_for_instrument_count(active_count)
    recommended_risk = get_recommended_risk_target(active_count)

    print(f"\n{Fore.RED}{Style.BRIGHT}  ⚠️  HIGH RISK SETTINGS ACTIVE  ⚠️{Style.RESET_ALL}")
    
    print(f"\n{Fore.YELLOW}  PORTFOLIO CONFIGURATION{Style.RESET_ALL}")
    print(f"  Active instruments      : {active_count}")
    print(f"  Asset class             : CRYPTO-ONLY (Concentrated)")
    print(f"  Expected positions (N)  : {config.vol_position_sizing.expected_positions}")
    print(f"  IDM (diversification)   : {Fore.RED}{idm:.2f}{Style.RESET_ALL} (conservative: ~1.2)")
    print(f"  Risk target (T)         : {Fore.RED}{config.vol_position_sizing.risk_target_pct*100:.1f}%{Style.RESET_ALL} annual vol (conservative: 12%)")
    print(f"  Recommended risk target : {recommended_risk*100:.1f}% (for {active_count} instruments)")

    print(f"\n{Fore.YELLOW}  ENTRY/EXIT THRESHOLDS (AGGRESSIVE){Style.RESET_ALL}")
    print(f"  Entry threshold         : {Fore.RED}±{config.strategy.entry_threshold}{Style.RESET_ALL} (conservative: ±7)")
    print(f"  Exit method             : {Fore.RED}Trailing Stop Loss + Stop and Reverse{Style.RESET_ALL} (NO take profit, NO forecast fade)")
    print(f"  Forecast cap            : ±{config.strategy.cap_max} (conservative: ±20)")
    print(f"  FDM (forecast mult)     : {config.strategy.fdm} (conservative: 1.13)")

    print(f"\n{Fore.YELLOW}  POSITION SIZING FORMULA{Style.RESET_ALL}")
    print(f"  notional = (1/N) × Capital × (T/V) × (F/10) × IDM")
    print(f"  Max notional per trade  : {Fore.RED}50% of balance{Style.RESET_ALL} (conservative: 20%)")
    print(f"  Max margin per trade    : {Fore.RED}25% of free margin{Style.RESET_ALL} (conservative: 10%)")

    print(f"\n{Fore.YELLOW}  STOP LOSS & ATR CONFIGURATION{Style.RESET_ALL}")
    print(f"  Primary timeframe      : {Fore.RED}M15 (15 minute){Style.RESET_ALL} (conservative: H1)")
    tf_meta = TIMEFRAME_META.get(config.symbols[enabled_symbols[0]].primary_tf, TIMEFRAME_META["M15"])
    print(f"  Stop multiplier        : {Fore.RED}{tf_meta['stop_multiplier']}× ATR{Style.RESET_ALL} (conservative: 4×)")
    print(f"  ATR period             : {config.strategy.atr_period} (conservative: 14)")
    print(f"  Poll interval          : {config.poll_interval}s (conservative: 60s)")

    print(f"\n{Fore.YELLOW}  ACTIVE INSTRUMENTS{Style.RESET_ALL}")
    print(f"  {'SYMBOL':<12} {'TIMEFRAME':<10} {'VOL TARGET':<12} {'DAILY LIMIT':<12}")
    print(f"  {'─' * 50}")
    for sym, cfg in config.symbols.items():
        if cfg.enabled:
            print(
                f"  {sym:<12} {cfg.primary_tf:<10} "
                f"{cfg.vol_target_pct*100:.2f}%{'':<6} "
                f"{cfg.max_daily_trades or 5} trades"
            )

    print(f"\n{Fore.RED}{Style.BRIGHT}  EXPECTED OUTCOMES:{Style.RESET_ALL}")
    print(f"  • Annual return target : 40-80%")
    print(f"  • Expected drawdown    : 50-70%")
    print(f"  • Win rate             : 35-40%")
    print(f"  • Avg trade duration   : Hours")
    print(f"  • Monthly trades       : 30-60")
    print(f"  • Exit method          : Trailing stop (2.5× ATR) + Signal reversal")

    print(f"{Fore.RED}{'─' * 80}{Style.RESET_ALL}")
    
    print(f"\n{Fore.YELLOW}Press Enter to start aggressive trading (Ctrl+C to cancel)...{Style.RESET_ALL}")
    input()

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
        print(f"\n{Fore.YELLOW}Keyboard interrupt received - shutting down...{Style.RESET_ALL}")
    except Exception as exc:
        logger.critical(f"Fatal error: {exc}", exc_info=True)
    finally:
        if bot:
            bot.shutdown()
        mt5.shutdown()

    print(f"\n{Fore.GREEN}Bot stopped cleanly.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Please check aggressive_trading_bot.log for detailed trade history.{Style.RESET_ALL}")

if __name__ == "__main__":
    main()