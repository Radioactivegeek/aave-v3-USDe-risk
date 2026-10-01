"""
Ethena USDe Volatility & Intraday Drawdown Risk Engine
Repository: aave-v3-ethena-risk-engine
File: scripts/usde_volatility_analysis.py

Theoretical Grounding:
    Daily close data obscures systemic tail risks because arbitrageurs often re-peg 
    synthetic assets within hours. Risk desks evaluate hourly/tick candles to measure 
    the true peak-to-trough liquidation depth (Maximum Drawdown) and assess whether 
    borrowers' Health Factors dipped below 1.0 during transient market shocks.
"""

from datetime import datetime
import os
import sys
import time
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# -----------------------------------------------------------------------------
# 1. VERIFIED TIME RANGE & COINGECKO API CONFIGURATION
# -----------------------------------------------------------------------------
# CoinGecko enforces hourly granularity ONLY when range is between 2 and 90 days.
# Date window: August 1, 2026 00:00:00 UTC to September 30, 2026 23:59:59 UTC (61 days)
START_DATE = datetime(2026, 8, 1, 0, 0, 0)
END_DATE = datetime(2026, 9, 30, 23, 59, 59)

UNIX_FROM = int(START_DATE.timestamp())
UNIX_TO = int(END_DATE.timestamp())

COINGECKO_RANGE_URL = (
    "https://api.coingecko.com/api/v3/coins/ethena-usde/market_chart/range"
)
params = {
    "vs_currency": "usd",
    "from": UNIX_FROM,
    "to": UNIX_TO,
}

headers = {
    "Accept": "application/json",
    "User-Agent": "AaveRiskResearch/1.0",
}
# Optional: inject demo API key if present in environment
if os.getenv("COINGECKO_API_KEY"):
    headers["x-cg-demo-api-key"] = os.getenv("COINGECKO_API_KEY")

print(
    f"[*] Fetching hourly price points from CoinGecko ({START_DATE.date()} to {END_DATE.date()})..."
)

# -----------------------------------------------------------------------------
# 2. DATA INGESTION & ROBUST ERROR HANDLING
# -----------------------------------------------------------------------------
max_retries = 3
retry_delay = 10
raw_payload = None

for attempt in range(1, max_retries + 1):
    try:
        response = requests.get(
            COINGECKO_RANGE_URL, params=params, headers=headers, timeout=15
        )
        if response.status_code == 200:
            raw_payload = response.json()
            break
        elif response.status_code == 429:
            print(
                f"[!] Rate limited (429). Backing off for {retry_delay}s (Attempt {attempt}/{max_retries})..."
            )
            time.sleep(retry_delay)
            retry_delay *= 2
        else:
            print(
                f"[-] HTTP Error {response.status_code}: {response.text[:200]}"
            )
            break
    except requests.exceptions.RequestException as err:
        print(f"[-] Network connection error on attempt {attempt}: {err}")
        time.sleep(3)

if not raw_payload or "prices" not in raw_payload:
    print("[-] Failed to retrieve price series from CoinGecko. Aborting.")
    sys.exit(1)

# -----------------------------------------------------------------------------
# 3. DATA CLEANING & STRUCTURED NORMALIZATION
# -----------------------------------------------------------------------------
df = pd.DataFrame(raw_payload["prices"], columns=["timestamp_ms", "price"])
df["datetime"] = pd.to_datetime(df["timestamp_ms"], unit="ms")
df = df.drop(columns=["timestamp_ms"]).sort_values("datetime").reset_index(drop=True)

# Drop any nulls or invalid price anomalies
df = df.dropna(subset=["price"])
df = df[df["price"] > 0]

print(f"[+] Loaded {len(df)} discrete price observations.")

# -----------------------------------------------------------------------------
# 4. QUANTITATIVE RISK METRICS (HOURLY RESOLUTION)
# -----------------------------------------------------------------------------
# Hourly returns
df["hourly_return"] = df["price"].pct_change()

# 30-Day Rolling Annualized Volatility:
# 30 days * 24 hours = 720 observations
# Annualization factor = sqrt(24 * 365) = sqrt(8760)
HOURLY_PERIODS_30D = 30 * 24
ANNUALIZATION_FACTOR = np.sqrt(8760)

df["volatility_30d"] = (
    df["hourly_return"].rolling(window=HOURLY_PERIODS_30D).std()
    * ANNUALIZATION_FACTOR
    * 100
)

# Cumulative Peak & Maximum Drawdown (%)
df["cumulative_peak"] = df["price"].cummax()
df["drawdown_pct"] = (
    (df["price"] - df["cumulative_peak"]) / df["cumulative_peak"]
) * 100

max_drawdown = df["drawdown_pct"].min()
min_price = df["price"].min()
min_price_time = df.loc[df["price"].idxmin(), "datetime"]
latest_vol = (
    df["volatility_30d"].dropna().iloc[-1]
    if not df["volatility_30d"].dropna().empty
    else np.nan
)

print("\n" + "=" * 80)
print("          ETHENA USDe: HOURLY VOLATILITY & DRAWDOWN AUDIT")
print("=" * 80)
print(f"Observation Window:               {START_DATE.date()} -> {END_DATE.date()}")
print(f"Total Hourly Candle Points:       {len(df)}")
print(f"Lowest Recorded Price:            ${min_price:.4f} (at {min_price_time} UTC)")
print(f"Max Peak-to-Trough Drawdown:      {max_drawdown:.2f}%")
print(f"Current 30-Day Annualized Vol:    {latest_vol:.2f}%")
print("=" * 80)

# Specific Event Analysis
print("\n[+] Target Governance Interventions:")
for event_name, event_dt in [
    ("Aug 10 Cap Cut", datetime(2026, 8, 10)),
    ("Sep 22 Cap Raise / Wick", datetime(2026, 9, 22)),
]:
    day_slice = df[df["datetime"].dt.date == event_dt.date()]
    if not day_slice.empty:
        low = day_slice["price"].min()
        high = day_slice["price"].max()
        dd = day_slice["drawdown_pct"].min()
        print(
            f" * {event_name} ({event_dt.date()}): High = ${high:.4f} | Low = ${low:.4f} | Intra-day Max DD = {dd:.2f}%"
        )
    else:
        print(f" * {event_name}: No observations on this date.")
print("-" * 80 + "\n")

# -----------------------------------------------------------------------------
# 5. VISUALIZATION (DUAL-PANEL: PRICE HISTORY & DRAWDOWN)
# -----------------------------------------------------------------------------
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True, gridspec_kw={"height_ratios": [2, 1]})

# --- Subplot 1: Price Action & Governance Interventions ---
ax1.plot(df["datetime"], df["price"], color="#0284c7", linewidth=1.4, label="USDe Hourly Price")
ax1.axhline(1.000, color="#10b981", linestyle="--", alpha=0.7, label="Peg Parity ($1.00)")

# Governance Event Markers
ax1.axvline(datetime(2026, 8, 10), color="#64748b", linestyle=":", linewidth=1.8, label="Aug 10: Cap Cut (Plasma)")
ax1.axvline(datetime(2026, 9, 22), color="#8b5cf6", linestyle=":", linewidth=1.8, label="Sep 22: Cap Raise & Wick")

# Annotate the September 22 Event
ax1.annotate(
    "Sep 22: CEX Flash Wick to $0.9202\n(Aave Chainlink Peg: >$0.9970)",
    xy=(datetime(2026, 9, 22, 12, 0), min(df[df['datetime'].dt.date == datetime(2026, 9, 22).date()]['price'].min(), 0.98)),
    xytext=(datetime(2026, 8, 25), 0.965),
    arrowprops=dict(facecolor="#dc2626", shrink=0.08, width=1.5, headwidth=7),
    fontsize=9.5,
    fontweight="bold",
    bbox=dict(boxstyle="round,pad=0.3", fc="#fef2f2", ec="#dc2626", lw=1),
)

ax1.set_title("Ethena USDe: Hourly Price Action & Governance Interventions", fontsize=13, fontweight="bold", pad=12)
ax1.set_ylabel("Price (USD)", fontsize=11, fontweight="bold")
ax1.legend(loc="lower left", frameon=True)

# --- Subplot 2: Maximum Drawdown Line ---
ax2.plot(df["datetime"], df["drawdown_pct"], color="#dc2626", linewidth=1.2, label="Intraday Drawdown (%)")
ax2.fill_between(df["datetime"], df["drawdown_pct"], 0, color="#f87171", alpha=0.25)
ax2.axvline(datetime(2026, 8, 10), color="#64748b", linestyle=":", linewidth=1.8)
ax2.axvline(datetime(2026, 9, 22), color="#8b5cf6", linestyle=":", linewidth=1.8)

ax2.set_title("Maximum Drawdown Profile (%)", fontsize=11, fontweight="bold", pad=8)
ax2.set_ylabel("Drawdown %", fontsize=11, fontweight="bold")
ax2.set_xlabel("Date", fontsize=11, fontweight="bold")
ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
ax2.legend(loc="lower left", frameon=True)

plt.tight_layout()

output_path = os.path.join(os.path.dirname(__file__), "..", "assets", "usde_hourly_volatility_drawdown.png")
os.makedirs(os.path.dirname(output_path), exist_ok=True)
plt.savefig(output_path, dpi=300)
print(f"[+] High-resolution chart saved to: {output_path}")
plt.show()