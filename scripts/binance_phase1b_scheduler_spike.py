#!/usr/bin/env python3
"""Read-only Phase 1b scheduler/heartbeat qualification spike.

This script intentionally cannot place orders. It loads the existing Phase 1b
LiveRunner spike from the same directory, reuses its Binance Testnet readers and
target-position caller with execute=False, then exercises LiveRunner.run_loop()
through the real Scheduler with exactly two one-shot jobs.

The probe deliberately avoids a short recurring interval. Binance reads are
synchronous and can take longer than a very short cadence; using a recurring
1-second job can keep the scheduler continuously overdue and starve a separate
async timeout. Two one-shot jobs test scheduler dispatch, LiveRunner ticks,
heartbeat, and audit behavior while making the probe intrinsically bounded.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "binance_phase1b_live_runner_spike.py"

if not BASE_PATH.is_file():
    raise SystemExit(
        "Missing binance_phase1b_live_runner_spike.py beside this script. "
        "Download both Phase 1b spike files into the same directory."
    )

spec = importlib.util.spec_from_file_location("phase1b_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit(f"Could not load {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

from src.live.runtime.liveness import is_runner_alive, last_tick  # noqa: E402
from src.live.runtime.runner import LiveRunner  # noqa: E402
from src.live.runtime.scheduler import Job, Scheduler  # noqa: E402


async def run_probe(seconds: float) -> int:
    cfg = base._load_testnet_config()
    testnet_exchange, market = base._testnet_exchange_and_market(cfg)
    mainnet_exchange = base._mainnet_public_exchange()

    positions_reader = base._positions_reader(cfg)
    balance_reader = base._balance_reader(cfg)
    open_orders_reader = base._open_orders_reader(testnet_exchange)

    before_positions = positions_reader()
    before_btc = base._asset_qty(before_positions, base.BASE_ASSET)
    before_usdt = base._asset_qty(before_positions, base.QUOTE_ASSET)

    tick_results: list[dict[str, Any]] = []
    holder: dict[str, LiveRunner] = {}

    async def on_fire(_job: Any) -> None:
        result = await holder["runner"].run_once()
        tick_results.append(dict(result))
        agent_result = result.get("agent_result") if isinstance(result, dict) else None
        action = agent_result.get("action") if isinstance(agent_result, dict) else None
        print(
            f"  scheduled tick {len(tick_results)}: "
            f"outcome={result.get('outcome')} action={action} audit_id={result.get('audit_id')}"
        )

    scheduler = Scheduler(on_fire, max_recheck_ms=250)
    runner = LiveRunner(
        base.BROKER_KEY,
        agent_caller=base._make_agent_caller(
            cfg=cfg,
            positions_reader=positions_reader,
            mainnet_exchange=mainnet_exchange,
            testnet_market=market,
            execute=False,  # load-bearing: this scheduler probe is read-only
        ),
        reconcile_fn=base._tolerant_reconcile,
        read_positions=positions_reader,
        read_balance=balance_reader,
        read_open_orders=open_orders_reader,
        scheduler=scheduler,
        load_mandate_fn=lambda _broker: base._build_test_mandate(),
        triggers=[],
        session_id="phase1b-binance-testnet-scheduler",
    )
    holder["runner"] = runner

    print("Phase 1b scheduler/heartbeat probe")
    print("  broker writes : DISABLED")
    print(f"  execution host: {cfg.host}")
    print("  schedule      : exactly two one-shot ticks")
    print(f"  settle wait   : {seconds:g} seconds")
    print(f"  BTC before    : {before_btc}")
    print(f"  USDT before   : {before_usdt}")

    now_ms = int(time.time() * 1000)
    jobs = [
        Job(
            id=f"{base.BROKER_KEY}-phase1b-once-1",
            next_run_at=now_ms,
            schedule="once",
            payload={"broker": base.BROKER_KEY, "probe": "phase1b", "ordinal": 1},
        ),
        Job(
            id=f"{base.BROKER_KEY}-phase1b-once-2",
            next_run_at=now_ms,
            schedule="once",
            payload={"broker": base.BROKER_KEY, "probe": "phase1b", "ordinal": 2},
        ),
    ]

    runner.run_loop(jobs=jobs)
    try:
        # The two broker-backed ticks may themselves take longer than this wait.
        # Once they return, no recurring jobs remain, so control is guaranteed
        # to come back to this coroutine and the probe can stop cleanly.
        await asyncio.sleep(seconds)
    finally:
        await runner.stop_loop()

    after_positions = positions_reader()
    after_btc = base._asset_qty(after_positions, base.BASE_ASSET)
    after_usdt = base._asset_qty(after_positions, base.QUOTE_ASSET)

    heartbeat = last_tick(base.BROKER_KEY)
    alive = is_runner_alive(base.BROKER_KEY)
    audit_ids = [
        result.get("audit_id")
        for result in tick_results
        if isinstance(result, dict) and result.get("audit_id")
    ]
    actions = []
    for result in tick_results:
        agent_result = result.get("agent_result") if isinstance(result, dict) else None
        actions.append(agent_result.get("action") if isinstance(agent_result, dict) else None)

    summary = {
        "scheduled_ticks": len(tick_results),
        "actions": actions,
        "audit_ids": audit_ids,
        "heartbeat_last_tick_ms": heartbeat,
        "heartbeat_fresh": alive,
        "btc_before": before_btc,
        "btc_after": after_btc,
        "usdt_before": before_usdt,
        "usdt_after": after_usdt,
        "balances_unchanged": before_btc == after_btc and before_usdt == after_usdt,
    }

    print("\nScheduler probe summary")
    print(json.dumps(summary, indent=2))

    if len(tick_results) != 2:
        print(f"\nRESULT: FAIL — expected exactly two scheduled ticks, got {len(tick_results)}.")
        return 2
    if not alive:
        print("\nRESULT: FAIL — scheduler fired, but heartbeat is not fresh.")
        return 3
    if len(audit_ids) != len(tick_results):
        print("\nRESULT: FAIL — one or more scheduled ticks lacked an audit id.")
        return 4
    if not summary["balances_unchanged"]:
        print("\nRESULT: FAIL — balances changed during a read-only scheduler probe.")
        return 5

    print(
        "\nRESULT: PASS — exactly two scheduled ticks fired, heartbeat is fresh, "
        "audits were written, and no broker write occurred."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only bounded LiveRunner scheduler/heartbeat qualification probe"
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=1.0,
        help="Post-dispatch settle wait in seconds (default 1; allowed 0.5-5).",
    )
    args = parser.parse_args()
    if not (0.5 <= args.seconds <= 5.0):
        parser.error("--seconds must be between 0.5 and 5")
    return asyncio.run(run_probe(args.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
