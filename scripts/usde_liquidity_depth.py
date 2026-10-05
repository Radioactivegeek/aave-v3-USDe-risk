"""Calculate KyberSwap aggregate Ethereum USDe-to-USDC liquidity depth."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import requests


ROUTES_URL = "https://aggregator-api.kyberswap.com/ethereum/api/v1/routes"
USDE_ADDRESS = "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3"
USDC_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

USDE_DECIMALS = 18
USDC_DECIMALS = 6
BASELINE_USDE = Decimal("100")
MIN_SEARCH_USDE = Decimal("10000")
MAX_SEARCH_USDE = Decimal("50000000")
TARGET_IMPACTS = (1.0, 3.0, 5.0)
SEARCH_ITERATIONS = 25
REQUEST_DELAY_SECONDS = 0.1
REQUEST_TIMEOUT_SECONDS = 30
MAX_REQUEST_RETRIES = 3
RETRY_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class RouteQuote:
    amount_in_usde: Decimal
    amount_out_usdc: Decimal
    price_impact: float
    price_impact_source: str


def get_route_payload(
    session: requests.Session,
    amount_in_usde: Decimal,
) -> dict[str, Any]:
    amount_in_raw = str(int(amount_in_usde * Decimal(10**USDE_DECIMALS)))
    params = {
        "tokenIn": USDE_ADDRESS,
        "tokenOut": USDC_ADDRESS,
        "amountIn": amount_in_raw,
    }

    for attempt in range(1, MAX_REQUEST_RETRIES + 1):
        time.sleep(REQUEST_DELAY_SECONDS)
        try:
            response = session.get(
                ROUTES_URL,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code in {502, 503, 504}:
                if attempt == MAX_REQUEST_RETRIES:
                    response.raise_for_status()
                time.sleep(RETRY_DELAY_SECONDS * attempt)
                continue
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == MAX_REQUEST_RETRIES:
                raise
            time.sleep(RETRY_DELAY_SECONDS * attempt)

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("KyberSwap returned a non-object JSON response.")
    return payload


def parse_route_quote(
    payload: dict[str, Any],
    amount_in_usde: Decimal,
) -> RouteQuote:
    try:
        route_summary = payload["data"]["routeSummary"]
        amount_out_raw = Decimal(str(route_summary["amountOut"]))
        amount_in_usd = Decimal(str(route_summary["amountInUsd"]))
        amount_out_usd = Decimal(str(route_summary["amountOutUsd"]))
    except (KeyError, TypeError, InvalidOperation, ValueError) as exc:
        raise RuntimeError(
            "KyberSwap response must contain amountOut, amountInUsd, "
            "and amountOutUsd in data.routeSummary."
        ) from exc

    if amount_out_raw <= 0:
        raise RuntimeError("KyberSwap returned a non-positive amountOut.")

    native_price_impact = route_summary.get("priceImpact")
    if native_price_impact is not None:
        try:
            price_impact = float(native_price_impact)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "KyberSwap returned an invalid routeSummary.priceImpact."
            ) from exc
        price_impact_source = "API routeSummary.priceImpact"
    else:
        # The current KyberSwap frontend derives its displayed value from
        # amountInUsd and amountOutUsd because the REST payload omits the field.
        if amount_in_usd <= 0:
            raise RuntimeError("KyberSwap returned an invalid amountInUsd.")
        price_impact = float(
            (amount_in_usd - amount_out_usd) * Decimal("100") / amount_in_usd
        )
        price_impact_source = (
            "KyberSwap frontend formula; API priceImpact absent"
        )

    amount_out_usdc = amount_out_raw / Decimal(10**USDC_DECIMALS)
    return RouteQuote(
        amount_in_usde,
        amount_out_usdc,
        price_impact,
        price_impact_source,
    )


def fetch_quote(
    session: requests.Session,
    amount_in_usde: Decimal,
) -> RouteQuote:
    return parse_route_quote(
        get_route_payload(session, amount_in_usde),
        amount_in_usde,
    )


def find_capacity_at_impact(
    session: requests.Session,
    target_impact: float,
) -> RouteQuote:
    low = MIN_SEARCH_USDE
    high = MAX_SEARCH_USDE
    low_quote = fetch_quote(session, low)
    high_quote = fetch_quote(session, high)

    if low_quote.price_impact > target_impact:
        raise RuntimeError(
            f"{target_impact:.1f}% impact is below the configured "
            f"search floor of {low:,} USDe."
        )
    if high_quote.price_impact <= target_impact:
        raise RuntimeError(
            f"{target_impact:.1f}% impact was not reached at the configured "
            f"search ceiling of {high:,} USDe."
        )

    for _ in range(SEARCH_ITERATIONS):
        midpoint = (low + high) / Decimal("2")
        midpoint_quote = fetch_quote(session, midpoint)
        if midpoint_quote.price_impact <= target_impact:
            low = midpoint
            low_quote = midpoint_quote
        else:
            high = midpoint

    return low_quote


def print_report(
    baseline: RouteQuote,
    results: dict[float, RouteQuote],
) -> None:
    print("\nUSDe -> USDC AGGREGATE ETHEREUM DEX LIQUIDITY DEPTH")
    print("=" * 78)
    print(f"Baseline trade: {baseline.amount_in_usde:,.0f} USDe")
    print(f"Baseline output: {baseline.amount_out_usdc:,.6f} USDC")
    print(f"Baseline API price impact: {baseline.price_impact:.6f}%")
    print(f"Price impact source: {baseline.price_impact_source}")
    print("-" * 78)
    print(
        f"{'Target Impact':<18}"
        f"{'Max Sell Capacity (USDe)':>28}"
        f"{'Confirmed API Price Impact':>30}"
    )
    print("-" * 78)
    for target, quote in results.items():
        print(
            f"{target:>6.1f}%{'':<11}"
            f"{quote.amount_in_usde:>28,.2f}"
            f"{quote.price_impact:>29.6f}%"
        )
    print("=" * 78)


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "USDe-ethereum-depth/1.0"})

    baseline = fetch_quote(session, BASELINE_USDE)
    results = {
        target: find_capacity_at_impact(session, target)
        for target in TARGET_IMPACTS
    }
    print_report(baseline, results)


if __name__ == "__main__":
    main()
