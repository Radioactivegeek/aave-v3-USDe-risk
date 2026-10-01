import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# 1. Pull dynamic supply history from DefiLlama
pool_id = "42eaf290-24c3-4ce0-82ab-c1276444871b"
res = requests.get(f"https://yields.llama.fi/chart/{pool_id}").json()

df = pd.DataFrame(res["data"])
time_col = "timestamp" if "timestamp" in df.columns else "date"
df["date"] = pd.to_datetime(df[time_col])
df["tvl_millions"] = df["tvlUsd"] / 1e6

# 2. Filter to our research window (August - September 2026)
df = df[(df["date"] >= "2026-08-01") & (df["date"] <= "2026-09-30")].copy()

# 3. Add Verified Governance Cap Line (Aug 10 cut to 375M, Sep 22 raise to 750M)
conditions = [
    df["date"] < "2026-08-10",
    (df["date"] >= "2026-08-10") & (df["date"] < "2026-09-01"),
    (df["date"] >= "2026-09-01") & (df["date"] < "2026-09-22"),
    df["date"] >= "2026-09-22",
]
cap_values = [475, 375, 550, 750]
df["supply_cap"] = np.select(conditions, cap_values, default=750)

# 4. Plot both together
plt.figure(figsize=(11, 6))
plt.plot(
    df["date"],
    df["supply_cap"],
    label="Supply Cap",
    color="#d9534f",
    linestyle="--",
    linewidth=2,
)
plt.plot(
    df["date"],
    df["tvl_millions"],
    label="Actual USDe Supplied (DefiLlama API)",
    color="#0275d8",
    linewidth=2.5,
)
plt.fill_between(
    df["date"], df["tvl_millions"], color="#0275d8", alpha=0.15
)

# Marker lines for proposals
plt.axvline(
    pd.to_datetime("2026-08-10"),
    color="gray",
    linestyle=":",
    label="Aug 10: Cap Cut",
)
plt.axvline(
    pd.to_datetime("2026-09-22"),
    color="purple",
    linestyle=":",
    label="Sep 22: Cap Raised",
)

plt.title(
    "Aave V3 USDe: Real TVL Inflow vs. Risk Steward Caps",
    fontsize=13,
    fontweight="bold",
)
plt.ylabel("USD Millions ($M)", fontweight="bold")
plt.xlabel("Date", fontweight="bold")
plt.legend(loc="upper left")
plt.tight_layout()
plt.savefig("usde_api_with_caps.png", dpi=300)
plt.show()