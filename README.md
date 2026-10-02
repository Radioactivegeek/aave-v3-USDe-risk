# Aave V3 Ethena (USDe / sUSDe) Risk Engine & Solvency Monitor

[![Aave V3](https://img.shields.io/badge/Aave-V3-B6509E?logo=aave&logoColor=white)](https://aave.com/)
[![Ethena](https://img.shields.io/badge/Ethena-USDe%20%2F%20sUSDe-000000)](https://ethena.fi/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

An on-chain risk toolkit built to stress-test and monitor Ethena's synthetic dollar (`USDe` and `sUSDe`) on Aave V3.

Instead of relying on delayed dashboards, this engine queries Ethereum RPC nodes and live market data directly to analyze **loan book health**, **whale concentration**, **intraday price shocks**, and **governance cap changes**.

---

## ⚡ Quick Takeaways (TL;DR)

1. **Looping Hit the Ceiling:** Yield loopers filled Aave V3 Plasma deposits to 100% capacity, forcing risk stewards to rapidly expand supply caps ($550M → $750M).
2. **Whale Concentration is Extreme:** Just 2 protocol custody contracts hold **81.9%** of the entire $4.87B USDe supply (Gini coefficient: **0.9998**).
3. **Thin DEX Liquidity:** While tradable float is ~$430M, total secondary DEX exit liquidity (Uniswap + Curve) is only **~$86M**. A massive liquidation cannot exit via AMMs without severe slippage.
4. **Oracle Filtered the Flash Crash:** When Binance spot briefly wicked down to **$0.9202** on Sep 22, 2026, Aave's Chainlink aggregator held above **$0.9970**, saving healthy borrowers from unfair liquidations.

---

## 📊 Visual Risk Breakdown

### 1. TVL Inflow vs. Supply Caps
How fast deposits grew compared to risk steward limit adjustments:

![Aave Plasma USDe Caps](assets/aave_plasma_usde_caps.png)

* **Aug 10:** Supply cap reduced ($475M → $375M) to remove idle buffer.
* **Sep 22:** High yield looping drove deposits straight into the $550M ceiling.
* **Action:** Risk stewards expanded the cap to $750M to keep borrow transactions from failing.

---

### 2. Supply Breakdown & Whale Inequality
Where is all the USDe actually located?

![Float Decomposition & Lorenz Inequality Curve](assets/usde_advanced_concentration_lorenz.png)

```text
Total USDe Supply: $4.87 Billion (100%)
├── 🏛️ Protocol Locked:        $3.99B (81.9%)  [Bridge Escrow, Staking Vault, Aave Pool]
├── 🏦 CEX Hedge Margin:       $0.45B  (9.2%)  [Derivatives backing on Bybit / Binance]
└── 💧 Active Tradable Float:  $0.43B  (8.8%)  [Circulating tokens / Looper capital]

⚠️ Secondary AMM Liquidity:    $0.086B ($86M total across Curve & Uniswap)
```

* **Gini Score (0.9998):** Top 0.3% of addresses hold over 99.7% of all tokens.
* **AMM Liquidity Cliff:** Liquidating even a single whale borrower would drain secondary on-chain pools.

---

### 3. Hourly Price Shocks & Max Drawdown
Daily charts hide intra-day flash crashes. Here is the hourly breakdown over 61 days:

![USDe Hourly Volatility & Drawdown Analysis](assets/usde_hourly_volatility_drawdown.png)

* **Binance Spot Dip ($0.9202):** A localized order book imbalance triggered an 8% drop.
* **Chainlink Oracle Buffer:** The multi-source feed smoothed out the glitch (> $0.9970), preventing safe accounts ($H_f \approx 1.23$) from cascading liquidations.

---

## 🔎 Verified Parameters & Contract Addresses

| Layer | Parameter / Target | Verified Value | Context |
| :--- | :--- | :--- | :--- |
| **Governance** | Plasma USDe Supply Cap (Aug 10) | $475M → $375M | Cut due to 57.3% low utilization |
| **Governance** | Plasma sUSDe Supply Cap (Aug 10) | $450M → $225M | Cut due to 34.8% low utilization |
| **Governance** | Plasma USDe Supply Cap (Sep 22) | $550M → $750M | Emergency boost (100% capacity hit) |
| **Governance** | Core USDe Borrow Cap (Sep 22) | $700M → $100M | Slashed (borrowers use Plasma, not Core) |
| **On-Chain Contract** | Aave V3 Pool Proxy | `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2` | Ethereum Mainnet |
| **On-Chain Contract** | Ethena USDe Token | `0x4c9edd5852cd905f086c759e8383e09bff1e68b3` | ERC-20 contract |
| **Price / Oracle** | Binance Spot Low (Sep 22) | $0.9202 | 1-min order book tick |
| **Price / Oracle** | Chainlink Aggregator Peg (Sep 22) | > $0.9970 | Filtered out CEX order book noise |

---

## 🚀 Quickstart

### 1. Clone & Install
```bash
git clone https://github.com/Radioactivegeek/aave-v3-USDe-risk.git
cd aave-v3-USDe-risk

python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows PowerShell:
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 2. Run the Scripts

* **Scan Active Borrower Health Factors (Live RPC):**
  ```bash
  # Scan recent USDT borrowers on Aave V3 (last 120 mins)
  python scripts/scan_health_factors.py --token USDT --minutes 120

  # Scan USDC borrowers over 2,500 blocks
  python scripts/scan_health_factors.py --token USDC --blocks 2500
  ```

* **Analyze Whale Concentration & Gini / HHI:**
  ```bash
  python scripts/usde_chart.py
  ```

* **Plot Hourly Drawdown & Price Volatility:**
  ```bash
  python scripts/usde_volatility_analysis.py
  ```

* **Compare Inflows vs. Governance Caps:**
  ```bash
  python scripts/plot_aave_usde.py
  ```

---

## 📁 Repository Layout

```text
├── assets/          # Generated charts & visual risk reports
├── data/            # On-chain snapshots & governance proposal logs
├── scripts/         # Production analysis & live RPC scanner scripts
├── requirements.txt # Python dependencies (web3, pandas, matplotlib)
└── README.md        # Risk memo & usage guide
```

---

## 📌 Key Solvency Conclusions

1. **USDe is used for collateral, not borrowing on Mainnet:** Core borrow utilization stayed at ~11%, while supply on Plasma hit 100%. Users deposit USDe to borrow USDT/USDC or loop yields on L2s.
2. **Loopers run on thin margins:** Typical health factors sit around **1.10 - 1.25**. A drop of only 15% to 20% in collateral value begins triggering liquidations.
3. **Aggregated oracles are mandatory:** With secondary AMM depth at only $86M, decentralized lending platforms must rely on multi-venue aggregated oracles to survive isolated exchange order-book flash wicks.