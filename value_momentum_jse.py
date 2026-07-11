import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# JSE STOCK TICKERS
# ============================================================

tickers = [
    "NPN.JO", "CFR.JO", "FSR.JO", "SBK.JO", "AGL.JO", "BIL.JO", "MTN.JO", "VOD.JO", "CPI.JO", "NED.JO", 
    "ABG.JO", "SHF.JO", "SOL.JO", "PPC.JO", "IMP.JO", "AMS.JO", "SAP.JO", "WHL.JO", "MRP.JO", "TRU.JO", 
    "ARI.JO", "ANG.JO", "APN.JO", "BAT.JO", "CML.JO", "DSBP.JO", "DRD.JO", "EXX.JO", "TFG.JO", "GRT.JO", 
    "INL.JO", "JSE.JO", "KIO.JO", "TGA.JO", "MTH.JO", "AFEP.JO", "AFT.JO", "OUT.JO", "TKG.JO", "SLM.JO", 
    "SSW.JO", "SPP.JO", "SHP.JO", "PIK.JO"
]

# Remove duplicates
tickers = list(dict.fromkeys(tickers))

print(f"Total JSE tickers to analyze: {len(tickers)}")

# ============================================================
# COLLECT DATA
# ============================================================

results = []
failed_tickers = []

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y")
        
        # Get company name and sector
        company_name = info.get("longName", info.get("shortName", ticker.replace(".JO", "")))
        sector = info.get("sector", info.get("industry", "N/A"))
        
        # More flexible data requirement - at least 6 months of data
        if len(hist) < 126:  # Reduced from 252 to 126 days (6 months)
            print(f"Skipping {ticker}: Insufficient historical data ({len(hist)} days)")
            failed_tickers.append(ticker)
            continue

        close = hist["Close"]
        
        # Calculate latest available price
        current_price = close.iloc[-1]

        # ====================================================
        # MOMENTUM FACTORS (based on price)
        # ====================================================
        
        # 1-month return (approximately 21 trading days)
        if len(close) >= 21:
            ret_1m = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        else:
            ret_1m = np.nan
            
        # 3-month return (approximately 63 trading days)
        if len(close) >= 63:
            ret_3m = (close.iloc[-1] / close.iloc[-63] - 1) * 100
        else:
            ret_3m = np.nan
            
        # 6-month return (approximately 126 trading days)
        if len(close) >= 126:
            ret_6m = (close.iloc[-1] / close.iloc[-126] - 1) * 100
        else:
            ret_6m = np.nan
            
        # 12-month return (use available data)
        if len(close) >= 252:
            ret_12m = (close.iloc[-1] / close.iloc[-252] - 1) * 100
        else:
            # Use first available data point
            ret_12m = (close.iloc[-1] / close.iloc[0] - 1) * 100

        # ====================================================
        # VALUE FACTORS
        # ====================================================
        
        # Traditional multiples
        pe = info.get("trailingPE", np.nan)
        pb = info.get("priceToBook", np.nan)
        ps = info.get("priceToSalesTrailing12Months", np.nan)
        
        # Enterprise Value calculations
        market_cap = info.get("marketCap", np.nan)
        total_debt = info.get("totalDebt", np.nan)
        cash = info.get("totalCash", np.nan)
        
        enterprise_value = np.nan
        if market_cap and not np.isnan(market_cap):
            if total_debt and cash and not np.isnan(total_debt) and not np.isnan(cash):
                enterprise_value = market_cap + total_debt - cash
            elif total_debt and not np.isnan(total_debt):
                enterprise_value = market_cap + total_debt
            else:
                enterprise_value = market_cap
        
        # EV/EBIT (Enterprise Value / Earnings Before Interest & Tax)
        ebit = info.get("ebitda", np.nan)  # Using EBITDA as proxy if EBIT not available
        ev_ebit = np.nan
        if enterprise_value and not np.isnan(enterprise_value) and ebit and not np.isnan(ebit) and ebit != 0:
            ev_ebit = enterprise_value / ebit
        
        # EV/GP (Enterprise Value / Gross Profit)
        gross_profit = info.get("grossProfits", np.nan)
        ev_gp = np.nan
        if enterprise_value and not np.isnan(enterprise_value) and gross_profit and not np.isnan(gross_profit) and gross_profit != 0:
            ev_gp = enterprise_value / gross_profit
        
        # Traditional EV/EBITDA
        ebitda = info.get("ebitda", np.nan)
        ev_ebitda = np.nan
        if enterprise_value and not np.isnan(enterprise_value) and ebitda and not np.isnan(ebitda) and ebitda != 0:
            ev_ebitda = enterprise_value / ebitda

        results.append({
            "Ticker": ticker,
            "Company": company_name,
            "Sector": sector,
            "PE": pe,
            "PB": pb,
            "PS": ps,
            "EV_EBIT": ev_ebit,
            "EV_GP": ev_gp,
            "EV_EBITDA": ev_ebitda,
            "1M Return": ret_1m,
            "3M Return": ret_3m,
            "6M Return": ret_6m,
            "12M Return": ret_12m
        })
        
        print(f"Processed: {ticker} - {company_name[:30]} - {sector}")

    except Exception as e:
        print(f"Error processing {ticker}: {str(e)}")
        failed_tickers.append(ticker)

# ============================================================
# CREATE DATAFRAME
# ============================================================

df = pd.DataFrame(results)

if df.empty:
    print("\nNo data collected. Exiting.")
    print(f"Failed to process {len(failed_tickers)} tickers: {failed_tickers}")
    exit()

print(f"\nSuccessfully processed {len(df)} JSE stocks")
if failed_tickers:
    print(f"Failed to process {len(failed_tickers)} tickers")

# ============================================================
# VALUE RANKS (Lower = Better)
# ============================================================

# Use these columns for value ranking (excluding any with too many NaNs)
value_cols = ["PE", "PB", "PS", "EV_EBIT", "EV_GP"]

# Rank each value metric (lower percentiles are better)
for col in value_cols:
    if col in df.columns:
        # Fill NaN with median for ranking
        median_val = df[col].median()
        if not np.isnan(median_val):
            df[col].fillna(median_val, inplace=True)
        else:
            df[col].fillna(df[col].mean(), inplace=True)
        
        # Lower values get higher ranks (lower percentile rank = better)
        df[f"{col}_Rank"] = df[col].rank(ascending=True, pct=True)
        
        # Convert to 0-100 scale where 100 is best (lowest PE, etc.)
        df[f"{col}_Score"] = (1 - df[f"{col}_Rank"]) * 100

# Calculate Value Score (average of all value metric scores)
value_score_cols = [f"{col}_Score" for col in value_cols if f"{col}_Score" in df.columns]
df["Value_Score"] = df[value_score_cols].mean(axis=1)

# ============================================================
# MOMENTUM RANKS (Higher = Better)
# ============================================================

momentum_cols = ["1M Return", "3M Return", "6M Return", "12M Return"]

for col in momentum_cols:
    if col in df.columns:
        # Fill NaN with 0 for momentum
        df[col].fillna(0, inplace=True)
        
        # Higher returns get higher ranks
        df[f"{col}_Rank"] = df[col].rank(ascending=False, pct=True)
        
        # Convert to 0-100 scale where 100 is best (highest return)
        df[f"{col}_Score"] = df[f"{col}_Rank"] * 100

# Calculate Momentum Score (average of all momentum scores)
momentum_score_cols = [f"{col}_Score" for col in momentum_cols if f"{col}_Score" in df.columns]
df["Momentum_Score"] = df[momentum_score_cols].mean(axis=1)

# ============================================================
# COMPOSITE SCORE (50% Value, 50% Momentum)
# ============================================================

df["Composite_Score"] = (0.50 * df["Value_Score"]) + (0.50 * df["Momentum_Score"])

# ============================================================
# FINAL RANK (1 = Best)
# ============================================================

df["Rank"] = df["Composite_Score"].rank(ascending=False).astype(int)

# ============================================================
# GENERATE SIGNALS based on percentile thresholds
# ============================================================

def get_signal(composite_score, percentile_80, percentile_60, percentile_40):
    if composite_score >= percentile_80:
        return "STRONG BUY"
    elif composite_score >= percentile_60:
        return "BUY"
    elif composite_score >= percentile_40:
        return "HOLD"
    else:
        return "SELL"

# Calculate percentile thresholds from actual data
percentile_80 = df["Composite_Score"].quantile(0.80)
percentile_60 = df["Composite_Score"].quantile(0.60)
percentile_40 = df["Composite_Score"].quantile(0.40)

df["Signal"] = df["Composite_Score"].apply(
    lambda x: get_signal(x, percentile_80, percentile_60, percentile_40)
)

# ============================================================
# SORT BY COMPOSITE SCORE 
# ============================================================

df = df.sort_values("Composite_Score", ascending=False).reset_index(drop=True)

# ============================================================
# FORMAT OUTPUT COLUMNS
# ============================================================

# Round percentages to 1 decimal
for col in momentum_cols:
    if col in df.columns:
        df[col] = df[col].round(1)

# Round value metrics to 1 decimal
for col in value_cols + ["EV_EBITDA"]:
    if col in df.columns:
        df[col] = df[col].round(1)

# Round scores to 1 decimal
df["Value_Score"] = df["Value_Score"].round(1)
df["Momentum_Score"] = df["Momentum_Score"].round(1)
df["Composite_Score"] = df["Composite_Score"].round(1)

# ============================================================
# SELECT FINAL COLUMNS IN REQUESTED ORDER
# ============================================================

output_columns = [
    "Rank", "Ticker", "Company", "Sector", "PE", "PB", "PS", 
    "EV_EBIT", "EV_GP", "1M Return", "3M Return", "6M Return", 
    "12M Return", "Value_Score", "Momentum_Score", "Composite_Score", "Signal"
]

final_columns = [col for col in output_columns if col in df.columns]
df_output = df[final_columns]

# ============================================================
# SAVE TO CSV FILE
# ============================================================

# Generate filename with timestamp
from datetime import datetime
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"JSE_Stock_Rankings_{timestamp}.csv"

# Save to CSV
df_output.to_csv(filename, index=False)
print(f"\ Data saved to: {filename}")

# Also save a clean version with proper formatting for Excel
filename_excel = f"JSE_Stock_Rankings_{timestamp}_formatted.csv"
df_output.to_csv(filename_excel, index=False, float_format='%.1f')
print(f" Formatted data saved to: {filename_excel}")

# ============================================================
# DISPLAY SUMMARY STATISTICS IN TERMINAL
# ============================================================

print("\n" + "="*80)
print("AMARE CAPITAL MANAGEMENT")
print("JOHANNESBURG STOCK EXCHANGE (JSE) STOCK RANKINGS")
print("="*80)

print(f"\n Total Stocks Analyzed: {len(df_output)}")
if failed_tickers:
    print(f" Failed to process: {len(failed_tickers)} tickers")
print(f" File saved: {filename}")
print(f" File saved (formatted): {filename_excel}")

print(f"\n SIGNAL DISTRIBUTION:")
print(f"  STRONG BUY: {len(df_output[df_output['Signal'] == 'STRONG BUY'])}")
print(f"  BUY: {len(df_output[df_output['Signal'] == 'BUY'])}")
print(f"  HOLD: {len(df_output[df_output['Signal'] == 'HOLD'])}")
print(f"  SELL: {len(df_output[df_output['Signal'] == 'SELL'])}")

print(f"\n TOP 5 STRONGEST BUY RECOMMENDATIONS:")
for idx, row in df_output.head(5).iterrows():
    print(f"  #{row['Rank']}. {row['Ticker']} - {row['Company'][:35]}")
    print(f"     Composite: {row['Composite_Score']} | Signal: {row['Signal']}")
    print(f"     Value: {row['Value_Score']} | Momentum: {row['Momentum_Score']}")

print(f"\n BOTTOM 5 AVOID/SELL RECOMMENDATIONS:")
for idx, row in df_output.tail(5).iterrows():
    print(f"  #{row['Rank']}. {row['Ticker']} - {row['Company'][:35]}")
    print(f"     Composite: {row['Composite_Score']} | Signal: {row['Signal']}")

print("\n" + "="*80)
print(" SCREENING COMPLETE - DATA EXPORTED TO CSV")
print("="*80)

# ============================================================
# Preview first few rows in console
# ============================================================

print("\n PREVIEW OF FIRST 10 ROWS (CSV OUTPUT):")
print("-"*100)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 25)
pd.set_option('display.float_format', lambda x: f'{x:.1f}' if not pd.isna(x) and isinstance(x, float) else str(x))

# Show preview with limited columns for readability
preview_columns = ["Rank", "Ticker", "Company", "Sector", "Composite_Score", "Signal", "Value_Score", "Momentum_Score"]
preview_df = df_output[preview_columns].head(10)
print(preview_df.to_string(index=False))
print("-"*100)

print(f"\n Full dataset with all metrics exported to CSV file.")
print(f" Open the CSV file in Excel/Google Sheets for full analysis.")