"""
Aave V3 Dynamic Risk Engine - Multi-Asset Borrower Health Factor Scanner
Author: Quantitative DeFi Risk Project
Repository: aave-v3-ethena-risk-engine

Description:
    Dynamically identifies active debtors on Aave V3 Ethereum Core by filtering
    on-chain 'Borrow' event logs for a target reserve asset. Accepts either
    block count (--blocks) or duration in minutes (--minutes).
    If no events are discovered, offers an interactive manual address inspection.
"""

import argparse
import os
import sys
from web3 import Web3

# -----------------------------------------------------------------------------
# 1. VERIFIED TOKEN & CONTRACT REGISTRY (Ethereum Mainnet)
# -----------------------------------------------------------------------------
TOKEN_REGISTRY = {
    "USDT": Web3.to_checksum_address(
        "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    ),
    "USDC": Web3.to_checksum_address(
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    ),
    "USDE": Web3.to_checksum_address(
        "0x4c9edd5852cd905f086c759e8383e09bff1e68b3"
    ),
    "WETH": Web3.to_checksum_address(
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    ),
    "WBTC": Web3.to_checksum_address(
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
    ),
}

# [VERIFIED] Aave V3 Pool Proxy on Ethereum Core
AAVE_V3_POOL_ADDRESS = Web3.to_checksum_address(
    "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
)

# [VERIFIED] Canonical Borrow event topic 0
BORROW_EVENT_SIG = (
    "0xb3d084820fb1a9decffb176436bd02558d15fac9b0ddfed8c465bc7359d7dce0"
)

POOL_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "user", "type": "address"}
        ],
        "name": "getUserAccountData",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "totalCollateralBase",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "totalDebtBase",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "availableBorrowsBase",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "currentLiquidationThreshold",
                "type": "uint256",
            },
            {"internalType": "uint256", "name": "ltv", "type": "uint256"},
            {
                "internalType": "uint256",
                "name": "healthFactor",
                "type": "uint256",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# -----------------------------------------------------------------------------
# 2. CLI ARGUMENT PARSER (MUTUALLY EXCLUSIVE: BLOCKS OR MINUTES)
# -----------------------------------------------------------------------------
parser = argparse.ArgumentParser(
    description="Scan Aave V3 borrower health factors by reserve asset over blocks or minutes."
)
parser.add_argument(
    "--token",
    type=str,
    default="USDT",
    choices=list(TOKEN_REGISTRY.keys()),
    help="Target asset symbol to scan (default: USDT)",
)

# Create mutually exclusive group so user can supply either --blocks OR --minutes
time_group = parser.add_mutually_exclusive_group()
time_group.add_argument(
    "--blocks",
    type=int,
    help="Exact number of recent blocks to inspect (e.g. --blocks 2000)",
)
time_group.add_argument(
    "--minutes",
    type=int,
    help="Time window in minutes to convert to blocks at 12s/block (e.g. --minutes 120)",
)

args = parser.parse_args()

target_symbol = args.token.upper()
target_token_address = TOKEN_REGISTRY[target_symbol]

# Compute scan window in blocks
BLOCK_TIME_SECONDS = 12
if args.minutes is not None:
    blocks_to_scan = max(1, (args.minutes * 60) // BLOCK_TIME_SECONDS)
    window_description = (
        f"{args.minutes} minute(s) (~{blocks_to_scan} blocks @ 12s/block)"
    )
elif args.blocks is not None:
    blocks_to_scan = max(1, args.blocks)
    estimated_mins = (blocks_to_scan * BLOCK_TIME_SECONDS) / 60
    window_description = f"{blocks_to_scan} blocks (~{estimated_mins:.1f} mins)"
else:
    # Default fallback window: 1500 blocks (~5 hours)
    blocks_to_scan = 1500
    window_description = "1500 blocks (default, ~5.0 hours)"

# -----------------------------------------------------------------------------
# 3. RPC CONNECTION POOL
# -----------------------------------------------------------------------------
RPC_CHAIN = [
    os.getenv("RPC_URL", "").strip(),
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
]


def establish_rpc_connection(endpoints):
    for url in endpoints:
        if not url:
            continue
        try:
            w3_instance = Web3(
                Web3.HTTPProvider(url, request_kwargs={"timeout": 15})
            )
            if w3_instance.is_connected():
                print(f"[+] Connected to RPC: {url}")
                return w3_instance
        except Exception:
            continue
    print("[-] Error: All RPC endpoints exhausted.")
    sys.exit(1)


w3 = establish_rpc_connection(RPC_CHAIN)
pool_contract = w3.eth.contract(address=AAVE_V3_POOL_ADDRESS, abi=POOL_ABI)

# -----------------------------------------------------------------------------
# 4. CHUNKED LOG SCANNING
# -----------------------------------------------------------------------------
target_topic_filter = "0x" + target_token_address[2:].lower().rjust(64, "0")
latest_block = w3.eth.block_number
start_block = latest_block - blocks_to_scan
CHUNK_SIZE = 500

print(f"[*] Target Asset: {target_symbol} ({target_token_address})")
print(f"[*] Scan Window:  {window_description}")
print(
    f"[*] Block Range:  #{start_block} to #{latest_block} (chunks of {CHUNK_SIZE})..."
)

discovered_borrowers = set()

for chunk_start in range(start_block, latest_block, CHUNK_SIZE):
    chunk_end = min(chunk_start + CHUNK_SIZE - 1, latest_block)
    try:
        logs = w3.eth.get_logs(
            {
                "fromBlock": chunk_start,
                "toBlock": chunk_end,
                "address": AAVE_V3_POOL_ADDRESS,
                "topics": [BORROW_EVENT_SIG, target_topic_filter],
            }
        )
        for log in logs:
            if len(log["topics"]) > 2:
                debtor_raw = "0x" + log["topics"][2].hex()[-40:]
                discovered_borrowers.add(Web3.to_checksum_address(debtor_raw))
    except Exception as err:
        print(f"[-] RPC error on blocks {chunk_start}-{chunk_end}: {err}")

# -----------------------------------------------------------------------------
# 5. NO-EVENT HANDLER: MANUAL WALLET INPUT PROMPT
# -----------------------------------------------------------------------------
if not discovered_borrowers:
    print(
        f"\n[!] Notice: No {target_symbol} borrow events recorded in the specified window."
    )
    choice = (
        input(
            "--> Would you like to manually inspect specific wallet addresses? (y/n): "
        )
        .strip()
        .lower()
    )

    if choice in ["y", "yes"]:
        raw_wallets = input(
            "--> Enter Ethereum wallet address(es) separated by commas:\n    "
        )
        for w in raw_wallets.split(","):
            cleaned = w.strip()
            if cleaned and Web3.is_address(cleaned):
                discovered_borrowers.add(Web3.to_checksum_address(cleaned))
            elif cleaned:
                print(f"[-] Invalid Ethereum address skipped: {cleaned}")

    if not discovered_borrowers:
        print("[*] No addresses to evaluate. Exiting scan cleanly.")
        sys.exit(0)

# -----------------------------------------------------------------------------
# 6. SOLVENCY EVALUATION & REPORTING (FULL 42-CHAR ADDRESS DISPLAY)
# -----------------------------------------------------------------------------
print("\n" + "=" * 118)
print(
    f"{'BORROWER ADDRESS (FULL)':<44} | {'COLLATERAL (USD)':<18} | {'DEBT (USD)':<16} | {'HEALTH FACTOR':<16} | {'STATUS'}"
)
print("=" * 118)

evaluated_count = 0
for borrower in discovered_borrowers:
    try:
        data = pool_contract.functions.getUserAccountData(borrower).call()
        evaluated_count += 1

        collateral_usd = data[0] / 1e8
        debt_usd = data[1] / 1e8
        raw_hf = data[5]
        hf = raw_hf / 1e18 if raw_hf < 1e30 else float("inf")

        if hf < 1.05 and debt_usd > 0:
            status = "\033[91mCRITICAL RISK\033[0m"
        elif hf < 1.15 and debt_usd > 0:
            status = "\033[93mWARNING\033[0m"
        elif debt_usd == 0:
            status = "NO ACTIVE DEBT"
        else:
            status = "\033[92mHEALTHY\033[0m"

        hf_str = f"{hf:.4f}" if hf != float("inf") else "N/A"

        print(
            f"{borrower:<44} | ${collateral_usd:>16,.2f} | ${debt_usd:>14,.2f} | {hf_str:<16} | {status}"
        )
    except Exception as err:
        print(f"[-] Error querying borrower {borrower}: {err}")

print("=" * 118)
print(f"[*] Total Borrowers Evaluated: {evaluated_count}\n")