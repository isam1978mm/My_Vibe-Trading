# Vibe-Trading App Qualification

This document tracks the decision to qualify Vibe-Trading itself before investing time in a new trading strategy.

## Goal

Determine whether Vibe-Trading can serve as the base platform for automated Binance Testnet trading without rebuilding a separate bot.

This track is about **platform capability**, not strategy profitability.

## Current qualification status

- **A14 — complete:** Vibe-Trading has a real autonomous trading runtime with scheduler, audit, kill switch, mandate support, reconciliation, and broker execution plumbing.
- **A15 — complete:** `LiveRunner` is reusable in principle for Binance, but Binance Testnet is not wired into the managed runner path today.
- **A16 — fail today for Binance:** the existing runtime state/recovery model cannot safely attribute Binance Spot balance changes to the runner's own orders.
- **Phase 1a — complete:** real Binance Spot Testnet evidence confirmed the predicted post-fill `unknown_fill` behavior in the unchanged built-in reconciler.
- **Phase 1b — in progress:** the direct `LiveRunner` harness has now completed an automatic Testnet market trade, a subsequent no-duplicate tick, and a fresh-process restart/no-duplicate check without changing `LiveRunner` core behavior. Scheduler/run-loop and heartbeat behavior remain to be checked.

### A16 root cause

For Binance Spot, holdings such as BTC and USDT are exposed as positions. The built-in reconciler saves a baseline at the start of a clean tick and compares the next broker snapshot against it. A normal order changes those balances, but the runtime does not persist enough Binance order ownership information after the order to prove that the change was its own.

As a result, a later reconcile can classify the runner's own fill as `unknown_fill` and halt. Conversely, a resting order that was never durably recorded can be invisible to the current ownership model and creates a duplicate-order risk after a crash/restart.

The stronger `pending_action` write-ahead mechanism already exists in Vibe-Trading, but it is currently Alpaca-specific.

## Decision: Testnet-first Option A

Continue with Vibe-Trading, but do **not** build the full production-grade Binance write-ahead adapter yet.

For Testnet qualification only:

- use **market orders only**;
- use **target-position behavior** so each tick compares desired holdings with actual holdings and trades only the difference;
- use Binance public mainnet market data for signals later, while execution stays on Binance Spot Testnet;
- keep all real-money profiles out of scope;
- treat the initial runner work as a qualification harness, not the final production implementation.

Before any real-money use, a full durable pre-submit ownership/recovery mechanism is still required.

## Phase 1a — connector/reconcile spike

**Time box:** 1–2 hours.

**Purpose:** verify the current code-reading predictions using Binance Spot Testnet before changing runtime behavior.

No `LiveRunner` integration and no production fix in this phase.

### Probe

1. Load the existing Binance paper/Testnet configuration.
2. Hard-refuse unless the resolved environment is `paper`, market type is `spot`, and the host is exactly the Binance Testnet host.
3. Read BTC/USDT Testnet state.
4. Run the built-in reconciler once using an isolated spike broker key to create a clean baseline.
5. Place one small BTC/USDT **market** order on Testnet only. Default target size: 6 USDT, subject to the exchange's current minimum notional.
6. Read open orders with an explicit BTC/USDT symbol.
7. Run the **unchanged built-in reconciler** again.
8. Record whether it produces `unknown_fill`, whether state advances, and which asset balances caused the delta.

### Phase 1a success criteria

The spike succeeds if it gives reproducible evidence for the current behavior, regardless of whether reconciliation passes or fails.

Expected result from code reading: the post-fill reconcile should halt with `unknown_fill` because BTC and/or USDT quantities changed from the saved baseline.

### Phase 1a observed result — 2026-10-10

The probe was run against Binance Spot Testnet with one 6 USDT BTC/USDT market BUY.

Baseline reconcile:

- `had_prior_state = False`
- `is_safe = True`
- `requires_halt = False`
- `state_persisted = True`
- no deltas

After the Testnet fill:

- BTC changed from `1.0` to `1.00007`
- USDT changed from `9999.9921558` to `9994.1961558`
- the second built-in reconcile returned `is_safe = False`
- `requires_halt = True`
- `state_persisted = False`
- `unknown_fill` was reported for both `BTC` and `USDT`
- 517 position deltas were examined because the Testnet account contains many non-zero assets

This confirms the A16 prediction with real Testnet evidence: the unchanged reconciler treats the runner's own normal Binance Spot fill as unexplained balance drift and refuses to advance state.

The local evidence file was written under `~/.vibe-trading/diagnostics/` and is intentionally not committed.

## Phase 1b — direct `LiveRunner` qualification harness

**Time box:** the remainder of roughly one working day.

Start only after Phase 1a evidence is understood.

Construct the existing `LiveRunner` directly in a script and inject:

- Binance Testnet SDK reads and submits;
- Binance public mainnet market data;
- a crypto/interval trigger;
- a controlled test mandate loader;
- target-position decision logic;
- a Binance-tolerant reconcile function;
- symbol-scoped open-order reads.

Then test:

1. one automatic Testnet market trade;
2. a second tick without a duplicate order;
3. stop/restart and re-read broker truth;
4. another tick without a duplicate order;
5. audit/heartbeat/scheduler behavior.

### Phase 1b read-only dry run — 2026-10-10

The qualification harness was run with writes disabled and a target increment of 6 USDT equivalent.

Observed:

- execution profile resolved to Binance Spot Testnet;
- market data came from public Binance mainnet with no credentials;
- Testnet balances read successfully;
- target state was initialized from the existing BTC balance rather than treating the preloaded Testnet BTC as strategy-owned;
- `LiveRunner.run_once()` completed with `outcome = invoked`;
- the deterministic caller returned `action = would_buy`;
- desired BTC was `1.000142471470398` versus actual BTC `1.00007`;
- the computed gap was about 6 USDT;
- an audit id was emitted;
- no broker write occurred.

This proved the existing `LiveRunner` can reach the Binance-specific reconciliation and deterministic target-position decision path using its existing dependency injection points, without changing `LiveRunner` core semantics.

### Phase 1b Testnet trade + duplicate/restart check — 2026-10-10

With explicit operator approval, one armed `LiveRunner.run_once()` tick was executed.

Observed on the write tick:

- decision: `action = buy`
- Binance Spot Testnet order id: `1210202`
- order type: `market`
- order status: `closed`
- filled amount: `0.00007 BTC`
- reported price: about `83030.02 USDT/BTC`
- target BTC remained `1.000142471470398`
- an audit id was emitted

The next invocation was started as a fresh Python process with writes disabled. That makes it a practical stop/restart check for the qualification harness: the process had to reload the persistent target state and recompute from current broker truth.

Observed after restart:

- Testnet BTC: `1.00014`
- Testnet USDT: `9988.3840544`
- target BTC: `1.000142471470398`
- remaining BTC gap: `0.0000024714703978911956`
- remaining gap value: about `0.2052 USDT`
- decision: `action = hold`
- reason: `target reached within exchange minimum/lot tolerance`
- no duplicate order was submitted
- another audit id was emitted

The USDT decrease from the pre-trade Phase 1b balance (`9994.1961558`) to the post-trade balance (`9988.3840544`) is about `5.8121 USDT`, matching one `0.00007 BTC` fill near `83030 USDT/BTC`. This supports that only one Phase 1b Testnet buy occurred during the observed run.

This is positive evidence for the smaller Testnet-first design: target-position recomputation plus market-only execution avoided a duplicate on the next tick and across a fresh process restart, using the existing `LiveRunner` injection model rather than editing its core.

**Still not proven:** long-running `run_loop` scheduling/heartbeat behavior, and production-grade crash recovery for an order whose broker response is lost. The latter remains explicitly out of scope for Testnet qualification and is mandatory before real funds.

## GO / STOP rule

Known integration gaps do **not** count as a failure when they can be handled through `LiveRunner`'s existing injection points, including:

- `agent_caller`;
- `reconcile_fn`;
- broker read callables;
- `submit_fn`;
- `load_mandate_fn`;
- triggers.

A STOP signal is **new** evidence that the work requires changing the core semantics of `LiveRunner` or rebuilding major subsystems such as its lifecycle, scheduler, execution model, or crash/recovery model.

A small generic compatibility hook in `src/live` is not automatically a STOP; a redesign of core runtime behavior is.

## Production boundary

The Testnet qualification shortcut is not sufficient for real funds.

Before real-money use, require all of the following:

- generate a unique client order ID before submission;
- durably persist the intended order **before** the broker side effect;
- submit that client order ID to Binance;
- resolve an uncertain order after restart using broker evidence instead of resending;
- record broker order ID, fill quantity, fee, and final status;
- reconcile expected asset changes and fees with tolerance;
- distinguish runner-owned changes from unexplained/manual account changes;
- fail closed on unresolved ambiguity;
- preserve kill-switch, mandate, audit, and daily-count protections.

## Safety boundary for qualification

- Binance Spot **Testnet only** for writes.
- No live Binance order profile.
- No real funds.
- No secrets are printed or committed.
- The spike must refuse any non-Testnet host before a write.
- Market orders only in Phase 1a/1b.
- Evidence files belong under the local Vibe-Trading runtime directory, not in Git.
