"""Live Aave V3 USDe bad-debt stress test against KyberSwap depth."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import matplotlib.pyplot as plt
import requests


LLAMA_POOLS_URL = "https://yields.llama.fi/pools"
KYBERSWAP_ROUTES_URL = (
    "https://aggregator-api.kyberswap.com/ethereum/api/v1/routes"
)

USDE_ADDRESS = "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3"
USDC_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDE_DECIMALS = 18
USDC_DECIMALS = 6

REFERENCE_AMOUNT_USDE = Decimal("100")
PRICE_IMPACT_TARGETS = (
    Decimal("1.0"),
    Decimal("3.0"),
    Decimal("5.0"),
)

LOOPED_DEPOSIT_SHARE = Decimal("0.15")
LIQUIDATABLE_SHARE_BY_SHOCK = {
    Decimal("0.03"): Decimal("0.50"),
    Decimal("0.05"): Decimal("1.00"),
}

REQUEST_TIMEOUT_SECONDS = 30
REQUEST_DELAY_SECONDS = 0.3
BINARY_SEARCH_ITERATIONS = 40
INITIAL_DEPTH_USDE = REFERENCE_AMOUNT_USDE


@dataclass(frozen=True)
class RouteQuote:
    amount_in_usde: Decimal
    amount_out_usdc: Decimal
    price_impact: Decimal
    raw_price_impact: str
    price_impact_source: str


def get_json(
    session: requests.Session,
    url: str,
    params: dict[str, str] | None = None,
) -> Any:
    time.sleep(REQUEST_DELAY_SECONDS)
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Expected JSON from {response.url}.") from exc


def fetch_aave_usde_tvl(session: requests.Session) -> Decimal:
    payload = get_json(session, LLAMA_POOLS_URL)
    pools = payload.get("data")
    if not isinstance(pools, list):
        raise RuntimeError("DefiLlama response did not contain a pool list.")

    matching_tvls: list[Decimal] = []
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        if (
            str(pool.get("project", "")).lower() != "aave-v3"
            or str(pool.get("chain", "")).lower() != "ethereum"
            or str(pool.get("symbol", "")).upper() != "USDE"
        ):
            continue
        try:
            tvl = Decimal(str(pool["tvlUsd"]))
        except (KeyError, InvalidOperation, TypeError) as exc:
            raise RuntimeError(
                "A matching DefiLlama pool did not contain a valid tvlUsd."
            ) from exc
        if tvl < 0:
            raise RuntimeError("DefiLlama returned a negative tvlUsd.")
        matching_tvls.append(tvl)

    if not matching_tvls:
        raise RuntimeError(
            "No DefiLlama pool matched project=aave-v3, "
            "chain=Ethereum, symbol=USDe."
        )
    return sum(matching_tvls, Decimal("0"))


def parse_route_quote(payload: Any, amount_in_usde: Decimal) -> RouteQuote:
    if not isinstance(payload, dict):
        raise RuntimeError("KyberSwap response was not an object.")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("KyberSwap response did not contain route data.")

    route_summary = data.get("routeSummary", data)
    if not isinstance(route_summary, dict):
        raise RuntimeError("KyberSwap response did not contain routeSummary.")

    try:
        amount_out_raw = Decimal(str(route_summary["amountOut"]))
        amount_in_usd = Decimal(str(route_summary["amountInUsd"]))
        amount_out_usd = Decimal(str(route_summary["amountOutUsd"]))
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise RuntimeError(
            "KyberSwap route must contain amountOut, amountInUsd, "
            "and amountOutUsd."
        ) from exc

    amount_out_usdc = amount_out_raw / Decimal(10**USDC_DECIMALS)
    if amount_out_usdc <= 0 or amount_in_usd <= 0 or amount_out_usd < 0:
        raise RuntimeError("KyberSwap returned invalid route amounts.")

    native_price_impact = route_summary.get("priceImpact")
    if native_price_impact is not None:
        try:
            price_impact = Decimal(str(native_price_impact))
        except (InvalidOperation, TypeError) as exc:
            raise RuntimeError(
                "KyberSwap returned an invalid routeSummary.priceImpact."
            ) from exc
        raw_price_impact = str(native_price_impact)
        price_impact_source = "API routeSummary.priceImpact"
    else:
        # This matches the current KyberSwap frontend calculation.
        price_impact = (
            (amount_in_usd - amount_out_usd) * Decimal("100") / amount_in_usd
        )
        raw_price_impact = str(price_impact)
        price_impact_source = (
            "KyberSwap frontend formula; API field absent"
        )

    return RouteQuote(
        amount_in_usde=amount_in_usde,
        amount_out_usdc=amount_out_usdc,
        price_impact=price_impact,
        raw_price_impact=raw_price_impact,
        price_impact_source=price_impact_source,
    )


def fetch_route_quote(
    session: requests.Session,
    amount_in_usde: Decimal,
) -> RouteQuote:
    if amount_in_usde <= 0:
        raise ValueError("Route input must be greater than zero.")

    amount_in_raw = str(int(amount_in_usde * Decimal(10**USDE_DECIMALS)))
    params = {
        "tokenIn": USDE_ADDRESS,
        "tokenOut": USDC_ADDRESS,
        "amountIn": amount_in_raw,
    }
    payload = get_json(session, KYBERSWAP_ROUTES_URL, params)
    return parse_route_quote(payload, amount_in_usde)


def find_depth_at_impact(
    session: requests.Session,
    target_price_impact: Decimal,
) -> tuple[Decimal, RouteQuote]:
    low = Decimal("0")
    high = INITIAL_DEPTH_USDE
    high_quote = fetch_route_quote(session, high)

    while high_quote.price_impact <= target_price_impact:
        low = high
        high *= Decimal("2")
        high_quote = fetch_route_quote(session, high)

    for _ in range(BINARY_SEARCH_ITERATIONS):
        midpoint = (low + high) / Decimal("2")
        midpoint_quote = fetch_route_quote(session, midpoint)
        if midpoint_quote.price_impact <= target_price_impact:
            low = midpoint
        else:
            high = midpoint

    return low, fetch_route_quote(session, low)


def format_usd(value: Decimal) -> str:
    return f"${float(value):,.2f}"


def plot_stress_test(
    scenario_labels: list[str],
    liquidatable: list[Decimal],
    dex_depth: list[Decimal],
) -> None:
    positions = list(range(len(scenario_labels)))
    width = 0.36
    scale = Decimal(1_000_000)

    liquidatable_m = [float(value / scale) for value in liquidatable]
    dex_depth_m = [float(value / scale) for value in dex_depth]

    fig, ax = plt.subplots(figsize=(10, 6))
    liquidatable_bars = ax.bar(
        [position - width / 2 for position in positions],
        liquidatable_m,
        width,
        label="Liquidatable Collateral",
        color="#dc2626",
    )
    depth_bars = ax.bar(
        [position + width / 2 for position in positions],
        dex_depth_m,
        width,
        label="Available DEX Depth at 5% Impact",
        color="#2563eb",
    )

    ax.set_title("USDe Bad-Debt Stress Test vs. Multi-DEX Exit Depth")
    ax.set_ylabel("USD Millions ($M)")
    ax.set_xticks(positions, scenario_labels)
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    for bars in (liquidatable_bars, depth_bars):
        ax.bar_label(bars, fmt="$%.1fM", padding=3)

    fig.tight_layout()
    plt.savefig("assets/usde_bad_debt_test.png", dpi=300)
    plt.show()


def print_summary(
    total_tvl: Decimal,
    spot_quote: RouteQuote,
    depth_quotes: dict[Decimal, tuple[Decimal, RouteQuote]],
    scenarios: list[tuple[Decimal, Decimal, Decimal, Decimal]],
) -> None:
    print("\nUSDe BAD-DEBT STRESS TEST")
    print("=" * 100)
    print(f"{'Fetched/calculated value':<44} {'Value':>22}")
    print("-" * 100)
    print(f"{'Aave V3 Ethereum USDe TVL':<44} {format_usd(total_tvl):>22}")
    print(
        f"{'100 USDe spot quote (USDC)':<44} "
        f"{format_usd(spot_quote.amount_out_usdc):>22}"
    )
    print(
        f"{'KyberSwap spot priceImpact':<44} "
        f"{spot_quote.raw_price_impact:>22}"
    )
    print(f"{'Spot impact source':<44} {spot_quote.price_impact_source:>22}")

    for target, (capacity, quote) in depth_quotes.items():
        print(
            f"{f'Max sell capacity at {target}% impact':<44} "
            f"{format_usd(capacity):>22}"
        )
        print(
            f"{'  Raw priceImpact at returned capacity':<44} "
            f"{quote.raw_price_impact:>22}"
        )
        print(f"{'  PriceImpact source':<44} {quote.price_impact_source:>22}")

    print("-" * 100)
    print(
        f"{'Scenario':<14} {'Liquidatable':>20} {'DEX depth':>20} "
        f"{'Bad-debt gap':>20} {'Uncovered gap':>20}"
    )
    for shock, liquidatable, depth, gap in scenarios:
        uncovered = max(gap, Decimal("0"))
        print(
            f"{shock:.0%} depeg      {format_usd(liquidatable):>20} "
            f"{format_usd(depth):>20} {format_usd(gap):>20} "
            f"{format_usd(uncovered):>20}"
        )
    print("=" * 100)


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "USDe-bad-debt-stress-test/1.0"})

    total_tvl = fetch_aave_usde_tvl(session)
    spot_quote = fetch_route_quote(session, REFERENCE_AMOUNT_USDE)
    depth_quotes = {
        target: find_depth_at_impact(session, target)
        for target in PRICE_IMPACT_TARGETS
    }
    dex_depth = depth_quotes[Decimal("5.0")][0]

    looped_tranche = total_tvl * LOOPED_DEPOSIT_SHARE
    scenarios: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    for shock, liquidation_share in LIQUIDATABLE_SHARE_BY_SHOCK.items():
        liquidatable = looped_tranche * liquidation_share
        gap = liquidatable - dex_depth
        scenarios.append((shock, liquidatable, dex_depth, gap))

    print_summary(total_tvl, spot_quote, depth_quotes, scenarios)
    plot_stress_test(
        [f"{shock:.0%} Depeg" for shock, *_ in scenarios],
        [liquidatable for _, liquidatable, _, _ in scenarios],
        [depth for _, _, depth, _ in scenarios],
    )


if __name__ == "__main__":
    main()
