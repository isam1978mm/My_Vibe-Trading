#!/usr/bin/env python3
"""Phase 1a diagnostic spike for Binance Spot Testnet reconciliation.

This is intentionally a qualification probe, not a production runner.

It verifies the current behavior of Vibe-Trading's built-in reconciliation
against one tiny Binance Spot Testnet market fill:

1. hard-check the saved Binance config is paper/spot/Testnet;
2. read BTC/USDT broker state;
3. run the unmodified built-in reconciler to establish an isolated baseline;
4. place one small Testnet market BUY;
5. read open orders with an explicit BTC/USDT symbol;
6. run the same built-in reconciler again;
7. save redaction-safe evidence under ~/.vibe-trading/diagnostics/.

No real-money host is accepted.  Without --execute this script performs only
read-only environment/market checks and does not create reconcile state or send
an order.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from src.config.paths import get_runtime_root  # noqa: E402
from src.live.paths import broker_dir  # noqa: E402
from src.live.runtime.reconcile import reconcile  # noqa: E402
from src.trading.connectors.binance import sdk as binance_sdk  # noqa: E402
from src.trading.connectors.binance.shaping import (  # noqa: E402
    normalize_symbol,
    order_to_dict,
)


TEST_SYMBOL = "BTC/USDT"
DEFAULT_NOTIONAL_USDT = 6.0
MAX_SPIKE_NOTIONAL_USDT = 10.0


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _require_testnet_config() -> Any:
    cfg = binance_sdk.load_config()
    failures: list[str] = []

    if cfg.environment != "paper":
        failures.append(f"environment={cfg.environment!r} (expected 'paper')")
    if cfg.profile != "paper":
        failures.append(f"profile={cfg.profile!r} (expected 'paper')")
    if cfg.market_type != "spot":
        failures.append(f"market_type={cfg.market_type!r} (expected 'spot')")
    if not cfg.is_testnet:
        failures.append("is_testnet=False")
    if cfg.host.rstrip("/") != binance_sdk.DEFAULT_TESTNET_HOST.rstrip("/"):
        failures.append(
            f"host={cfg.host!r} (expected {binance_sdk.DEFAULT_TESTNET_HOST!r})"
        )

    if failures:
        joined = "; ".join(failures)
        raise SystemExit(
            "REFUSING TO CONTINUE: Binance configuration is not the expected "
            f"Spot Testnet profile: {joined}"
        )

    # Reuse the connector's own host assertion as a second, independent guard.
    binance_sdk._assert_host(cfg)
    return cfg


def _exchange_and_market(cfg: Any, symbol: str) -> tuple[Any, dict[str, Any]]:
    exchange = binance_sdk._exchange(cfg)
    exchange.load_markets()
    market = exchange.market(symbol)
    if not isinstance(market, dict):
        raise RuntimeError(f"could not resolve market metadata for {symbol}")
    return exchange, market


def _minimum_notional(market: dict[str, Any]) -> float | None:
    try:
        value = market.get("limits", {}).get("cost", {}).get("min")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _positions_reader(cfg: Any):
    def read() -> list[dict[str, Any]]:
        payload = binance_sdk.get_positions(cfg)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise RuntimeError(str(payload.get("error") if isinstance(payload, dict) else payload))
        rows = payload.get("positions")
        if not isinstance(rows, list):
            raise RuntimeError("Binance positions response did not contain a positions list")
        return [dict(row) for row in rows if isinstance(row, dict)]

    return read


def _balance_reader(cfg: Any):
    def read() -> dict[str, Any]:
        payload = binance_sdk.get_account_snapshot(cfg)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise RuntimeError(str(payload.get("error") if isinstance(payload, dict) else payload))
        return dict(payload)

    return read


def _open_orders_reader(cfg: Any, exchange: Any, symbol: str):
    def read() -> list[dict[str, Any]]:
        # Intentionally symbol-scoped.  The connector's generic all-symbol call
        # is one of the behaviors Phase 1a is designed to avoid conflating with
        # the position-diff result.
        raw = binance_sdk._read_with_clock_retry(
            exchange,
            lambda: exchange.fetch_open_orders(symbol),
        )
        if raw is None:
            return []
        if not isinstance(raw, (list, tuple)):
            raise RuntimeError(
                f"symbol-scoped fetch_open_orders returned {type(raw).__name__}, expected list"
            )
        return [order_to_dict(item) for item in raw]

    return read


def _asset_quantities(positions: list[dict[str, Any]], assets: set[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in assets:
            continue
        try:
            out[symbol] = float(row.get("quantity") or 0.0)
        except (TypeError, ValueError):
            out[symbol] = 0.0
    return out


def _report_summary(report: Any) -> dict[str, Any]:
    payload = asdict(report)
    payload["is_safe"] = report.is_safe
    payload["requires_halt"] = report.requires_halt
    return payload


def _print_report(label: str, report: Any) -> None:
    kinds = [delta.kind for delta in report.deltas]
    unknown_assets = [
        delta.identity
        for delta in report.deltas
        if delta.kind == "unknown_fill" and delta.subject == "position"
    ]
    print(f"\n{label}")
    print(f"  had_prior_state : {report.had_prior_state}")
    print(f"  is_safe         : {report.is_safe}")
    print(f"  requires_halt   : {report.requires_halt}")
    print(f"  state_persisted : {report.state_persisted}")
    print(f"  delta_count     : {len(report.deltas)}")
    print(f"  delta_kinds     : {sorted(set(kinds))}")
    print(f"  unknown_assets  : {unknown_assets}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Binance Testnet fill vs built-in Vibe-Trading reconciliation."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Place exactly one small BTC/USDT market BUY on Binance Spot Testnet.",
    )
    parser.add_argument(
        "--notional",
        type=float,
        default=DEFAULT_NOTIONAL_USDT,
        help=f"Fake USDT market-buy notional (default {DEFAULT_NOTIONAL_USDT:g}; max {MAX_SPIKE_NOTIONAL_USDT:g}).",
    )
    args = parser.parse_args()

    cfg = _require_testnet_config()
    symbol = normalize_symbol(TEST_SYMBOL)
    if symbol != TEST_SYMBOL:
        raise SystemExit(f"REFUSING TO CONTINUE: unexpected normalized symbol {symbol!r}")

    if not (0 < args.notional <= MAX_SPIKE_NOTIONAL_USDT):
        raise SystemExit(
            f"REFUSING TO CONTINUE: --notional must be > 0 and <= {MAX_SPIKE_NOTIONAL_USDT:g} USDT"
        )

    exchange, market = _exchange_and_market(cfg, symbol)
    min_notional = _minimum_notional(market)

    print("Phase 1a Binance reconciliation spike")
    print("  environment : paper")
    print(f"  host        : {cfg.host}")
    print(f"  market      : {symbol}")
    print(f"  min notional: {min_notional if min_notional is not None else 'unknown'}")
    print(f"  probe order : BUY {args.notional:g} USDT market (Testnet only)")

    if min_notional is not None and args.notional < min_notional:
        raise SystemExit(
            f"REFUSING TO PLACE ORDER: {args.notional:g} USDT is below the current "
            f"minimum notional {min_notional:g} USDT. Choose a value <= "
            f"{MAX_SPIKE_NOTIONAL_USDT:g} only if it clears the exchange minimum."
        )

    if not args.execute:
        print("\nDRY RUN ONLY: no reconcile state created and no order submitted.")
        print("Re-run with --execute only when you intend to place the fake Testnet order.")
        return 0

    stamp = _utc_stamp()
    spike_broker = f"binance-phase1a-spike-{stamp.lower()}"
    state_path = broker_dir(spike_broker) / "runtime_state.json"

    read_positions = _positions_reader(cfg)
    read_balance = _balance_reader(cfg)
    read_open_orders = _open_orders_reader(cfg, exchange, symbol)

    before_positions = read_positions()
    before_assets = _asset_quantities(before_positions, {"BTC", "USDT"})
    before_open_orders = read_open_orders()

    baseline = reconcile(
        spike_broker,
        read_positions,
        read_balance,
        read_open_orders,
    )
    _print_report("Baseline reconcile", baseline)
    if not baseline.is_safe or not baseline.state_persisted:
        raise RuntimeError("baseline reconcile was not clean; no order will be submitted")

    print("\nSubmitting exactly one fake Testnet market order...")
    order = binance_sdk.place_order(
        cfg,
        symbol=symbol,
        side="buy",
        notional=args.notional,
        order_type="market",
    )
    if not isinstance(order, dict) or order.get("status") != "ok":
        raise RuntimeError(f"Testnet order failed: {order}")

    # Market orders normally settle immediately, but give the signed balance read
    # a short moment to observe the fill before the second reconcile pass.
    time.sleep(1.0)

    after_positions = read_positions()
    after_assets = _asset_quantities(after_positions, {"BTC", "USDT"})
    after_open_orders = read_open_orders()

    post_fill = reconcile(
        spike_broker,
        read_positions,
        read_balance,
        read_open_orders,
    )
    _print_report("Post-fill built-in reconcile", post_fill)

    evidence = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "spike_broker": spike_broker,
        "state_path": str(state_path),
        "safety": {
            "environment": cfg.environment,
            "profile": cfg.profile,
            "market_type": cfg.market_type,
            "is_testnet": cfg.is_testnet,
            "host": cfg.host,
        },
        "market": {
            "symbol": symbol,
            "minimum_notional": min_notional,
            "submitted_notional": args.notional,
        },
        "before": {
            "asset_quantities": before_assets,
            "open_orders": before_open_orders,
        },
        "order": order,
        "after": {
            "asset_quantities": after_assets,
            "open_orders": after_open_orders,
        },
        "baseline_reconcile": _report_summary(baseline),
        "post_fill_reconcile": _report_summary(post_fill),
    }

    evidence_dir = get_runtime_root() / "diagnostics"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"binance-phase1a-{stamp}.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    print("\nEvidence")
    print(f"  file       : {evidence_path}")
    print(f"  BTC before : {before_assets.get('BTC')}")
    print(f"  BTC after  : {after_assets.get('BTC')}")
    print(f"  USDT before: {before_assets.get('USDT')}")
    print(f"  USDT after : {after_assets.get('USDT')}")
    print(f"  order id   : {order.get('order_id')}")
    print("  cleanup    : none (the spike sends only the one requested Testnet order)")

    if post_fill.requires_halt:
        print("\nRESULT: prediction confirmed — built-in reconcile blocks after the Testnet fill.")
    else:
        print("\nRESULT: prediction NOT confirmed — inspect the evidence before changing code.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
