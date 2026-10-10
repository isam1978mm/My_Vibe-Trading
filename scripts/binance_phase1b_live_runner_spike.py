#!/usr/bin/env python3
"""Phase 1b qualification harness for Vibe-Trading LiveRunner + Binance Testnet.

Disposable qualification spike, not production trading code.

By default this script is read-only. It only submits an order when --execute is
combined with --run-once. Writes are hard-limited to Binance Spot Testnet and at
most 10 fake USDT per adjustment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from src.config.paths import get_runtime_root  # noqa: E402
from src.live.mandate.model import (  # noqa: E402
    AssetClass,
    ConsentMeta,
    HardCaps,
    InstrumentType,
    Mandate,
    UniverseConstraint,
)
from src.live.runtime.runner import LiveRunner  # noqa: E402
from src.live.runtime.triggers import Trigger  # noqa: E402
from src.trading.connectors.binance import sdk as binance_sdk  # noqa: E402
from src.trading.connectors.binance.shaping import normalize_symbol, order_to_dict  # noqa: E402

SYMBOL = "BTC/USDT"
BASE_ASSET = "BTC"
QUOTE_ASSET = "USDT"
BROKER_KEY = "binance-phase1b-testnet"
MAX_ORDER_NOTIONAL_USDT = 10.0
STATE_FILE = get_runtime_root() / "diagnostics" / "binance-phase1b-target.json"
OBS_FILE = get_runtime_root() / "diagnostics" / "binance-phase1b-observations.jsonl"


@dataclass(frozen=True)
class HarnessReconcileReport:
    is_safe: bool
    requires_halt: bool
    reason: str
    btc: float
    usdt: float
    open_orders: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_testnet_config() -> Any:
    cfg = binance_sdk.load_config()
    failures: list[str] = []
    if cfg.environment != "paper":
        failures.append(f"environment={cfg.environment!r}")
    if cfg.profile != "paper":
        failures.append(f"profile={cfg.profile!r}")
    if cfg.market_type != "spot":
        failures.append(f"market_type={cfg.market_type!r}")
    if not cfg.is_testnet:
        failures.append("is_testnet=False")
    if cfg.host.rstrip("/") != binance_sdk.DEFAULT_TESTNET_HOST.rstrip("/"):
        failures.append(f"host={cfg.host!r}")
    if failures:
        raise SystemExit(
            "REFUSING TO CONTINUE: expected Binance Spot Testnet config; "
            + "; ".join(failures)
        )
    binance_sdk._assert_host(cfg)
    return cfg


def _require_ccxt() -> Any:
    try:
        import ccxt  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit("ccxt is required for this Phase 1b spike") from exc
    return ccxt


def _mainnet_public_exchange() -> Any:
    ccxt = _require_ccxt()
    exchange = ccxt.binance({"enableRateLimit": True, "timeout": 15_000})
    if getattr(exchange, "apiKey", "") or getattr(exchange, "secret", ""):
        raise RuntimeError("public mainnet exchange unexpectedly has credentials")
    return exchange


def _public_mainnet_price(exchange: Any) -> float:
    ticker = exchange.fetch_ticker(SYMBOL)
    for key in ("last", "close", "ask", "bid"):
        value = ticker.get(key) if isinstance(ticker, Mapping) else None
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            return price
    raise RuntimeError("could not obtain a valid public Binance mainnet BTC/USDT price")


def _testnet_exchange_and_market(cfg: Any) -> tuple[Any, Mapping[str, Any]]:
    exchange = binance_sdk._exchange(cfg)
    exchange.load_markets()
    market = exchange.market(SYMBOL)
    if not isinstance(market, Mapping):
        raise RuntimeError("could not resolve Binance Testnet BTC/USDT market metadata")
    return exchange, market


def _market_min_notional(market: Mapping[str, Any]) -> float:
    raw = market.get("limits", {}).get("cost", {}).get("min")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 5.0
    return value if math.isfinite(value) and value > 0 else 5.0


def _market_amount_step(market: Mapping[str, Any]) -> float:
    raw = market.get("precision", {}).get("amount")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    return value if math.isfinite(value) and value > 0 else 0.0


def _positions_reader(cfg: Any):
    def read() -> list[dict[str, Any]]:
        payload = binance_sdk.get_positions(cfg)
        if not isinstance(payload, Mapping) or payload.get("status") != "ok":
            raise RuntimeError(f"positions read failed: {payload}")
        rows = payload.get("positions")
        if not isinstance(rows, list):
            raise RuntimeError("positions payload did not contain a list")
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    return read


def _balance_reader(cfg: Any):
    def read() -> dict[str, Any]:
        payload = binance_sdk.get_account_snapshot(cfg)
        if not isinstance(payload, Mapping) or payload.get("status") != "ok":
            raise RuntimeError(f"balance read failed: {payload}")
        return dict(payload)

    return read


def _open_orders_reader(exchange: Any):
    def read() -> list[dict[str, Any]]:
        raw = binance_sdk._read_with_clock_retry(
            exchange,
            lambda: exchange.fetch_open_orders(SYMBOL),
        )
        if raw is None:
            return []
        if not isinstance(raw, (list, tuple)):
            raise RuntimeError("symbol-scoped open-order read did not return a list")
        return [order_to_dict(item) for item in raw]

    return read


def _asset_qty(positions: list[dict[str, Any]], asset: str) -> float:
    asset = asset.upper()
    for row in positions:
        if str(row.get("symbol") or "").upper() != asset:
            continue
        try:
            qty = float(row.get("quantity") or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return qty if math.isfinite(qty) else 0.0
    return 0.0


def _append_observation(payload: Mapping[str, Any]) -> None:
    OBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OBS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, default=str) + "\n")


def _tolerant_reconcile(broker: str, read_positions, read_balance, read_open_orders):
    del broker
    positions = list(read_positions())
    _ = dict(read_balance())
    open_orders = list(read_open_orders())
    btc = _asset_qty(positions, BASE_ASSET)
    usdt = _asset_qty(positions, QUOTE_ASSET)
    safe = len(open_orders) == 0
    reason = "clean market-order state" if safe else "unexpected resting BTC/USDT order"
    report = HarnessReconcileReport(
        is_safe=safe,
        requires_halt=not safe,
        reason=reason,
        btc=btc,
        usdt=usdt,
        open_orders=len(open_orders),
    )
    _append_observation({"ts": _utc_now().isoformat(), "kind": "reconcile", **asdict(report)})
    return report


def _load_target() -> dict[str, Any] | None:
    if not STATE_FILE.is_file():
        return None
    raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"invalid Phase 1b target state at {STATE_FILE}")
    return raw


def _save_target(*, actual_btc: float, increment_usdt: float, mainnet_price: float) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "symbol": SYMBOL,
        "created_at": _utc_now().isoformat(),
        "baseline_btc": actual_btc,
        "target_btc": actual_btc + (increment_usdt / mainnet_price),
        "requested_increment_usdt": increment_usdt,
        "initial_mainnet_price": mainnet_price,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _build_test_mandate() -> Mandate:
    now = _utc_now()
    return Mandate(
        schema_version=1,
        hard_caps=HardCaps(
            account_funding_usd=10_000.0,
            max_order_notional_usd=MAX_ORDER_NOTIONAL_USDT,
            max_total_exposure_usd=MAX_ORDER_NOTIONAL_USDT,
            max_leverage=1.0,
            allowed_instruments=(InstrumentType.CRYPTO,),
            max_trades_per_day=10,
        ),
        universe=UniverseConstraint(
            asset_classes=(AssetClass.CRYPTO,),
            min_market_cap_usd=None,
            min_avg_daily_volume_usd=None,
            exclude_symbols=(),
        ),
        consent=ConsentMeta(
            created_at=now.isoformat(),
            consent_token_sha256="phase1b-testnet-qualification-only",
            broker=BROKER_KEY,
            account_ref="binance-spot-testnet",
            expires_at=(now + timedelta(days=1)).isoformat(),
        ),
        flatten_on_halt=False,
    )


def _make_agent_caller(
    *,
    cfg: Any,
    positions_reader,
    mainnet_exchange: Any,
    testnet_market: Mapping[str, Any],
    execute: bool,
):
    min_notional = _market_min_notional(testnet_market)
    amount_step = _market_amount_step(testnet_market)

    async def caller(session_id: str, prompt: str) -> Mapping[str, Any]:
        del session_id, prompt
        target = _load_target()
        positions = positions_reader()
        actual_btc = _asset_qty(positions, BASE_ASSET)
        actual_usdt = _asset_qty(positions, QUOTE_ASSET)
        mainnet_price = _public_mainnet_price(mainnet_exchange)

        if target is None:
            result = {
                "action": "hold",
                "reason": "no Phase 1b target initialized",
                "actual_btc": actual_btc,
                "actual_usdt": actual_usdt,
                "mainnet_price": mainnet_price,
            }
            _append_observation({"ts": _utc_now().isoformat(), "kind": "decision", **result})
            return result

        desired_btc = float(target["target_btc"])
        gap_btc = desired_btc - actual_btc
        gap_notional = abs(gap_btc) * mainnet_price
        qty_is_dust = amount_step > 0 and abs(gap_btc) < amount_step

        if gap_notional < min_notional or qty_is_dust:
            result = {
                "action": "hold",
                "reason": "target reached within exchange minimum/lot tolerance",
                "desired_btc": desired_btc,
                "actual_btc": actual_btc,
                "gap_btc": gap_btc,
                "gap_notional_usdt": gap_notional,
                "mainnet_price": mainnet_price,
            }
            _append_observation({"ts": _utc_now().isoformat(), "kind": "decision", **result})
            return result

        side = "buy" if gap_btc > 0 else "sell"
        if not execute:
            result = {
                "action": f"would_{side}",
                "reason": "write disabled; dry-run target-position decision",
                "desired_btc": desired_btc,
                "actual_btc": actual_btc,
                "gap_btc": gap_btc,
                "gap_notional_usdt": gap_notional,
                "mainnet_price": mainnet_price,
            }
            _append_observation({"ts": _utc_now().isoformat(), "kind": "decision", **result})
            return result

        if side == "buy":
            order_notional = min(MAX_ORDER_NOTIONAL_USDT, max(min_notional, gap_notional))
            order = binance_sdk.place_order(
                cfg,
                symbol=SYMBOL,
                side="buy",
                notional=order_notional,
                order_type="market",
            )
        else:
            exchange = binance_sdk._exchange(cfg)
            quantity = float(exchange.amount_to_precision(SYMBOL, abs(gap_btc)))
            if quantity <= 0 or quantity * mainnet_price < min_notional:
                result = {
                    "action": "hold",
                    "reason": "sell residual falls below Testnet minimum after precision",
                    "gap_btc": gap_btc,
                    "gap_notional_usdt": gap_notional,
                }
                _append_observation({"ts": _utc_now().isoformat(), "kind": "decision", **result})
                return result
            order = binance_sdk.place_order(
                cfg,
                symbol=SYMBOL,
                side="sell",
                quantity=quantity,
                order_type="market",
            )

        if not isinstance(order, Mapping) or order.get("status") != "ok":
            raise RuntimeError(f"Binance Testnet market order failed: {order}")
        result = {
            "action": side,
            "reason": "target-position adjustment submitted to Binance Spot Testnet",
            "desired_btc": desired_btc,
            "actual_btc_before": actual_btc,
            "gap_btc_before": gap_btc,
            "gap_notional_usdt_before": gap_notional,
            "mainnet_price": mainnet_price,
            "order": dict(order),
        }
        _append_observation({"ts": _utc_now().isoformat(), "kind": "decision", **result})
        return result

    return caller


def _print_target(target: dict[str, Any] | None) -> None:
    if target is None:
        print("  target      : not initialized")
        return
    print(f"  target BTC  : {float(target['target_btc']):.8f}")
    print(f"  baseline BTC: {float(target['baseline_btc']):.8f}")


async def _run(args: argparse.Namespace) -> int:
    cfg = _load_testnet_config()
    if normalize_symbol(SYMBOL) != SYMBOL:
        raise SystemExit("REFUSING TO CONTINUE: unexpected symbol normalization")

    testnet_exchange, market = _testnet_exchange_and_market(cfg)
    min_notional = _market_min_notional(market)
    mainnet_exchange = _mainnet_public_exchange()
    mainnet_price = _public_mainnet_price(mainnet_exchange)
    positions_reader = _positions_reader(cfg)
    balance_reader = _balance_reader(cfg)
    open_orders_reader = _open_orders_reader(testnet_exchange)
    positions = positions_reader()
    actual_btc = _asset_qty(positions, BASE_ASSET)
    actual_usdt = _asset_qty(positions, QUOTE_ASSET)

    print("Phase 1b LiveRunner qualification harness")
    print("  execution   : Binance Spot Testnet only")
    print(f"  testnet host: {cfg.host}")
    print("  market data : Binance public mainnet (no credentials)")
    print(f"  mainnet BTC : {mainnet_price}")
    print(f"  Testnet BTC : {actual_btc}")
    print(f"  Testnet USDT: {actual_usdt}")
    print(f"  min notional: {min_notional} USDT")

    if args.reset_target:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print(f"  target reset: {STATE_FILE}")
        else:
            print("  target reset: no existing target file")

    if args.initialize_target_usdt is not None:
        increment = float(args.initialize_target_usdt)
        if increment < min_notional or increment > MAX_ORDER_NOTIONAL_USDT:
            raise SystemExit(
                f"target increment must be between {min_notional:g} and "
                f"{MAX_ORDER_NOTIONAL_USDT:g} fake USDT"
            )
        target = _save_target(
            actual_btc=actual_btc,
            increment_usdt=increment,
            mainnet_price=mainnet_price,
        )
        print(f"  target init : +{increment:g} USDT equivalent")
    else:
        target = _load_target()
    _print_target(target)

    if not args.run_once:
        print("\nREAD-ONLY CHECK COMPLETE: LiveRunner was not invoked and no order was submitted.")
        return 0

    if args.execute:
        print("\nWRITE ARMED: one target-position adjustment may be submitted to TESTNET only.")
    else:
        print("\nDRY RUN: LiveRunner will run one tick; the caller cannot submit an order.")

    runner = LiveRunner(
        BROKER_KEY,
        agent_caller=_make_agent_caller(
            cfg=cfg,
            positions_reader=positions_reader,
            mainnet_exchange=mainnet_exchange,
            testnet_market=market,
            execute=bool(args.execute),
        ),
        reconcile_fn=_tolerant_reconcile,
        read_positions=positions_reader,
        read_balance=balance_reader,
        read_open_orders=open_orders_reader,
        load_mandate_fn=lambda _broker: _build_test_mandate(),
        triggers=[Trigger.market("crypto")],
        session_id="phase1b-binance-testnet",
    )

    result = await runner.run_once()
    print("\nLiveRunner tick result")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"\nTarget state : {STATE_FILE}")
    print(f"Observations : {OBS_FILE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1b LiveRunner + Binance Testnet qualification spike"
    )
    parser.add_argument(
        "--initialize-target-usdt",
        type=float,
        metavar="USDT",
        help=(
            "Create/replace the persistent desired BTC target at current BTC + this "
            "fake-USDT equivalent. This does not place an order by itself."
        ),
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Delete only the Phase 1b local target file; never touches Binance.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Construct the existing LiveRunner and execute exactly one tick.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow the one LiveRunner tick to submit a Testnet market adjustment if needed.",
    )
    args = parser.parse_args()
    if args.execute and not args.run_once:
        parser.error("--execute requires --run-once")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
