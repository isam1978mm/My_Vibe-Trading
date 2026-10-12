# Claude Trading Desk → My_Vibe-Trading Execution Plan

**Date:** 2026-10-12  
**Status:** Active execution plan  
**Primary repository:** `isam1978mm/My_Vibe-Trading`  
**Branch:** `main`  
**Strategic roadmap:** [`docs/CLAUDE_TRADING_DESK_INTEGRATION_ROADMAP.md`](./CLAUDE_TRADING_DESK_INTEGRATION_ROADMAP.md)  
**Private reference repository:** `isam1978mm/claude-trading-desk`

---

## 1. Purpose

This document defines **how the integration roadmap will actually be executed**.

The roadmap answers **what we want to build**. This document answers:

- what order we will work in;
- what branch/PR structure we will use;
- what must be tested at each stage;
- what blocks the next stage;
- what evidence must be recorded;
- when Binance Spot Testnet can be used;
- when AI is allowed to influence execution;
- and when a strategy can be considered qualified.

The implementation principle is simple:

> **My_Vibe-Trading remains the platform. Claude Trading Desk is a reference implementation whose strongest ideas are selectively ported into Vibe.**

We are **not** replacing Vibe with Claude Trading Desk and we are **not** building a second competing trading platform.

---

## 2. Target execution architecture

```text
MARKET DATA
    ↓
DETERMINISTIC STRATEGY
    ↓
TRADE CANDIDATE
    ↓
┌────────────┬───────────────┬──────────────┐
│ RULES ARM  │ GATED ARM     │ MODEL ARM    │
│ take raw   │ explicit      │ AI approves/ │
│ signal     │ if-statements │ rejects only │
└────────────┴───────────────┴──────────────┘
    ↓
FINAL RISK AUTHORITY
    ↓
ORDER INTENT
    ↓
BROKER / EXCHANGE ADAPTER
    ↓
DRY RUN / PAPER / BINANCE TESTNET
    ↓
JOURNAL + AUDIT + PARITY + DASHBOARD
```

### Non-negotiable rules

1. Strategy creates the candidate.
2. AI cannot invent an unrelated trade.
3. AI cannot reverse the side.
4. AI cannot increase position size.
5. AI cannot widen risk limits.
6. Risk engine has final authority.
7. Model failure defaults to `WAIT/REJECT` for new positions.
8. Backtests must be reproducible.
9. Paper/Testnet comes before any real-money consideration.
10. No live order placement or cancellation is part of this implementation plan without a separate explicit approval and a separately qualified live phase.

---

# 3. Working model

## Repository roles

### Primary implementation repository

```text
isam1978mm/My_Vibe-Trading
```

All production-facing integration work belongs here.

### Private reference repository

```text
isam1978mm/claude-trading-desk
```

Use it to inspect/reference:

- three-arm experiment design;
- bounded AI decision flow;
- deterministic model caching;
- mechanical trade auditing;
- replay validation;
- operational guardrails.

Do **not** turn the private Claude repository into a second production platform.

---

# 4. Branch and PR strategy

Do not implement everything in one long-lived branch.

Use one focused branch/PR per stage:

```text
main
 ├── feature/01-baseline-inventory
 ├── feature/02-trade-candidate-contract
 ├── feature/03-three-arm-runner
 ├── feature/04-ai-gate-cache
 ├── feature/05-mechanical-trade-audit
 ├── feature/06-replay-parity
 ├── feature/07-risk-hardening
 ├── feature/08-decision-journal-dashboard
 ├── feature/09-binance-testnet-qualification
 └── feature/10-live-promotion-controls
```

### Standard development cycle for every branch

```text
Create branch from current main
        ↓
Write/adjust tests first
        ↓
Implement smallest required change
        ↓
Run focused tests
        ↓
Run regression tests
        ↓
Run relevant backtest/replay
        ↓
Check stage exit gate
        ↓
Review diff
        ↓
Merge to main
```

### Rule

**Do not start the next phase until the current phase's exit gate passes.**

---

# 5. Phase 0 — Preserve and qualify the current baseline

## Objective

Establish exactly what works today before touching the architecture.

This is the first execution task and must be completed before new model/decision code is added.

## Why this phase comes first

The local checkout has previously exercised Binance Spot Testnet/CCXT behavior, while GitHub `main` may not contain every local experiment or change. The biggest avoidable mistake would be overwriting or silently losing a working local state.

## Procedure

### 0.1 Record GitHub baseline

Record:

```text
main HEAD SHA
repository version
Python version
important dependency versions
current date/time
```

### 0.2 Inspect local working tree

Working directory:

```text
C:\Dev\vibe-trading-test
```

Record:

```text
git status
git branch --show-current
git rev-parse HEAD
git diff --stat
git log -1 --oneline
```

Do not reset, clean, stash, checkout or overwrite unrelated local Runtime Status changes merely to make the tree look clean.

### 0.3 Reconcile local vs GitHub main

Identify:

- committed changes not on `main`;
- uncommitted Binance/CCXT changes;
- experiment-only files;
- local configuration that must remain local;
- generated files that should not enter Git;
- any local secrets or credentials that must never be committed.

### 0.4 Preserve working Testnet changes

If useful local code exists outside `main`, preserve it on a dedicated feature branch before refactoring.

Do not recreate working code from memory if the exact implementation already exists locally.

### 0.5 Run tests

Start with unit tests:

```bash
python -m pytest agent/tests -m unit
```

Then run the full suite available in the environment:

```bash
python -m pytest agent/tests
```

Record:

```text
passed
failed
skipped
expected pre-existing failures
runtime
```

### 0.6 Preserve one regression backtest

Choose one known existing strategy only as a platform regression fixture.

Record at minimum:

```text
strategy/version
data range
starting capital
ending capital
return
trade count
win rate
profit factor
max drawdown
Sharpe if available
fees/slippage settings
```

The purpose is not to prove the strategy is good. It is to detect unintended platform changes later.

## Deliverable

Create a baseline report such as:

```text
BASELINE REPORT

GitHub main SHA:
Local SHA:
Local working tree:
Python:
Tests:
Known failures:
Binance Spot Testnet connector state:
Reference backtest:
Uncommitted work preserved:
Baseline status: PASS / BLOCKED
```

## Exit gate

Phase 0 passes only when:

- local work is safely preserved;
- the baseline commit is known;
- test status is known;
- one backtest is reproducible;
- no secret material is staged for Git;
- Testnet-related local work is accounted for.

---

# 6. Phase 1 — Canonical TradeCandidate and Decision contracts

## Objective

Create one standard object representing a strategy opportunity before filters, AI, risk, or execution touch it.

## Why it matters

Without a canonical candidate object, `rules`, `gated`, and `model` can accidentally evaluate different opportunities. That would make performance comparisons invalid.

## Required candidate data

At minimum:

```text
candidate_id
strategy_id
strategy_version
symbol/instrument
market/venue
side
signal_timestamp
observable_market_timestamp
reference_price
entry intent
stop
profit target(s)
raw strategy-visible features
risk metadata
source data identity/version where practical
```

`candidate_id` must be deterministic from canonical strategy-visible information.

## Required decision data

```text
candidate_id
arm: rules | gated | model
verdict: take | wait/reject
reason codes
confidence/probability when applicable
model/provider/version when applicable
request_hash when applicable
latency
cache_hit
created_at
```

## Required tests

- identical candidate input → identical `candidate_id`;
- materially different input → different `candidate_id`;
- serialization key order cannot alter identity;
- a decision cannot silently mutate candidate direction;
- malformed fields fail validation;
- stop/target/side remain immutable through decision evaluation.

## Exit gate

All future decision arms can consume the same `TradeCandidate` without strategy-specific logic in the experiment runner.

---

# 7. Phase 2 — Three-arm experiment runner

## Objective

Implement the Claude Trading Desk comparison methodology inside Vibe.

## Arms

### Rules

Take every valid deterministic strategy candidate.

### Gated

Apply explicit programmed filters to the same candidates.

### Model

Ask the AI decision layer to approve/reject the same candidates.

## Critical experiment rule

Candidate generation happens **once**.

All arms receive the same ordered candidate set.

Before showing performance, the report must first prove:

```text
rules candidate IDs == gated candidate IDs == model candidate IDs
```

## Required metrics

For each arm:

```text
candidates seen
accepted
rejected
trades
win rate
mean R
median R
profit factor
gross P&L
net P&L
return
fees
slippage
max drawdown
Sharpe where appropriate
train/test or walk-forward metrics
```

Comparisons:

```text
rules vs gated
gated vs model
rules vs model
model/gated decision overlap
rejection reason breakdown
```

## Exit gate

The runner proves identical candidate sets before comparing returns.

---

# 8. Phase 3 — Bounded AI gate and deterministic cache

## Objective

Make AI a controlled second opinion, not an autonomous trading engine.

## Allowed decision contract

The model can return only:

```text
TAKE_PROPOSED
WAIT
```

Additional explanation/confidence fields are diagnostic only.

## Forbidden behavior

```text
strategy LONG → model SHORT
strategy SHORT → model LONG
model increases size
model widens stop
model bypasses risk limit
model creates new symbol
model creates new candidate
```

Any attempted side flip becomes:

```text
WAIT
```

## Failure behavior

All of these fail closed to no new position:

```text
timeout
provider unavailable
missing API key
HTTP error
invalid JSON
schema mismatch
unrecognized choice
model version mismatch where strict replay is required
```

## Deterministic cache

Canonical request hash should include:

```text
provider
model/version
prompt version
schema version
candidate_id
normalized model-visible features/context
question/criteria schema
```

## Required tests

- same request → same hash;
- prompt/schema change → different hash;
- model change → different hash;
- populated cache → rerun without network calls;
- malformed response → WAIT;
- timeout → WAIT;
- side-flip response → WAIT;
- offline replay reproduces previous decisions exactly.

## Exit gate

A completed model-assisted backtest can be rerun offline using cached decisions and produce identical decision results.

---

# 9. Phase 4 — Independent mechanical trade audit

## Objective

Verify that backtested/executed trades actually obey the written strategy and risk rules.

## Independence requirement

The audit must not simply call the same signal function that produced the trade.

It should recompute validity from persisted candidate/trade data.

## Checks

At minimum:

```text
signal was causal
data was available at signal time
entry side matches strategy
stop is on correct side
stop/target relationships are valid
position sizing matches policy
no forbidden same-bar lookahead
fees/slippage reconcile
accepted decision exists
risk approval exists
exit reason reconciles
P&L reconciles with fills
```

## Required output

```text
N/N trades passed
0 unexplained trades
0 orphan fills
0 candidates lacking decision provenance
```

Any failure must identify candidate/trade ID and exact failed rule.

## Exit gate

Reference backtest reports `N/N` valid trades with no unexplained exceptions.

---

# 10. Phase 5 — Backtest/live replay parity

## Objective

Prove that the live execution path interprets a known historical market sequence consistently with the research/backtest path.

## Method

Use or add a no-submit/replay broker mode.

Feed historical data through the production-like path:

```text
historical market sequence
        ↓
strategy
        ↓
candidate
        ↓
gate/model
        ↓
risk
        ↓
order intent
        ↓
NO SUBMIT
```

## Compare

```text
candidate IDs
timestamps
sides
gate/model decisions
risk verdicts
sizes
stops
targets
order intents
```

## Required restart test

Restart the replay process mid-session and verify the same candidate/order intent cannot be duplicated.

## Required isolation

Replay validation must not contact a live broker.

Model-assisted reproducibility tests should be cache-only/offline.

## Exit gate

A known session produces zero unexplained decision/order-intent differences between backtest and replay.

---

# 11. Phase 6 — Risk hardening

## Objective

Guarantee that a correct strategy or AI decision still cannot bypass operational risk controls.

## Required controls

```text
global kill switch
per-strategy enable/disable
max daily loss/drawdown
max open positions
max position exposure
max portfolio exposure
max risk per trade
minimum/maximum order sanity checks
stale-data rejection
wrong-side stop rejection
duplicate-order/idempotency protection
persistent halt state where required
explicit paper/Testnet/live separation
restart recovery
```

## Required tests

- kill switch prevents new orders;
- risk veto overrides model `TAKE`;
- max exposure works;
- max daily loss halt persists as designed;
- stale input is rejected;
- invalid stop is rejected;
- duplicate candidate cannot produce a second order after restart;
- no unit test requires live credentials.

## Exit gate

Every defined unsafe scenario has an automated regression test.

---

# 12. Phase 7 — Decision journal and dashboard observability

## Objective

Make every trade explainable from signal through fill and exit.

## Persist per candidate/trade

```text
candidate_id
strategy/version
market snapshot identity
rules decision
gated decision + reason
model request_hash
model/provider/version
model decision/confidence
cache hit/miss
risk verdict + reason
order intent
exchange/broker order ID
fills
fees
slippage
exit
realized P&L
```

## Dashboard additions

Use the existing Vibe dashboard instead of creating a parallel UI.

Useful views/filters:

```text
strategy
symbol
three-arm performance
AI approval/rejection rate
handwritten gate rejection rate
model/gate overlap
risk vetoes
model latency/errors
cache hit rate
broker rejects
parity failures
audit failures
equity/drawdown
gross vs net performance
```

## Exit gate

Starting from any fill, the operator can trace backward to:

```text
fill → order → risk decision → arm decision → candidate → strategy context
```

---

# 13. Phase 8 — Binance Spot Testnet qualification

## Objective

Qualify Vibe's exchange execution path using Binance Spot Testnet and CCXT, without creating a second Alpaca-centric execution stack.

## Important first step

Before changing the Binance implementation, reconcile and preserve the previously working local Testnet work discovered in Phase 0.

## Qualification sequence

### Step A — No-submit

Generate and log order intents only.

No exchange submission.

### Step B — Binance Spot Testnet basic execution

Using only Testnet and the smallest practical test size:

```text
create test order
confirm order state
confirm fill handling
cancel eligible test order
confirm cancellation state
```

No real-money trading.

### Step C — Reconciliation

Verify every exchange fill maps to one internal order intent and one candidate.

### Step D — Restart/idempotency

Restart during an active Testnet scenario and confirm:

```text
no duplicate submission
state recovers
existing exchange order is reconciled
```

### Step E — AI shadow mode

The strategy/rules path continues controlling Testnet behavior.

AI records only what it **would have done**:

```text
actual action: TAKE
AI shadow: WAIT
```

AI does not alter execution yet.

### Step F — Evaluate shadow results

Measure:

```text
AI acceptance rate
AI rejection rate
agreement with gated arm
trades AI would have prevented
winning trades AI would have prevented
losing trades AI would have prevented
net hypothetical effect after fees/slippage
```

### Step G — AI-gated Testnet

Only after shadow behavior is understood may the bounded model gate control Testnet acceptance/rejection.

Risk remains final authority.

### Step H — Multi-day soak

Run long enough to observe:

```text
reconnects
restarts
API errors
stale data
cache behavior
state recovery
risk halts
order reconciliation
journal completeness
```

## Testnet acceptance criteria

- zero accidental live endpoint calls;
- zero duplicate orders in restart tests;
- every fill maps to exactly one internal order intent;
- actual fill price and fees are persisted;
- provider/model failure cannot create a trade;
- kill/risk halt prevents new submissions;
- state recovers after restart;
- no unexplained audit/parity failures.

## Exit gate

Binance Spot Testnet execution is considered **platform-qualified** only when all acceptance criteria above pass.

---

# 14. Phase 9 — Statistical qualification

## Objective

Separate software correctness from trading edge.

A working platform is not evidence that a strategy is profitable.

## Required evaluation

Use the existing Vibe validation framework where possible, including existing validation functionality under `agent/backtest/validation.py`.

For each strategy/arm combination evaluate:

```text
sample size
fees/slippage
out-of-sample results
walk-forward results
bootstrap confidence interval
Monte Carlo/permutation evidence
regime stability
trade concentration
max drawdown
profit factor
Sharpe where appropriate
mean/median trade return
```

## Critical AI decision rule

The relevant comparison is not only:

```text
model > rules
```

It must also be:

```text
model > handwritten gated control
```

If the model cannot robustly beat the simpler handwritten filter, the AI layer is not justified merely because it beats raw rules.

## Required qualification result

Every evaluated strategy/model combination ends with one explicit outcome:

```text
QUALIFIED FOR CONTINUED PAPER/TESTNET EVALUATION
```

or

```text
NO EVIDENCE OF EDGE — STOP OR START A NEW PRE-REGISTERED EXPERIMENT
```

## Exit gate

A written qualification report exists and the reported result is reproducible.

---

# 15. Phase 10 — Optional live-promotion controls

## Objective

Prepare safeguards so live mode cannot happen accidentally.

This phase does **not** mean the system is automatically approved for real-money trading.

## Preconditions

All prior phases must pass, plus:

```text
extended paper/Testnet soak completed
emergency stop tested
withdrawal permission absent
allowed venue/account explicitly pinned
strategy/version pinned
model/version pinned
prompt/schema version pinned
risk limits reviewed
rollback procedure documented
```

## Design requirements

- live mode defaults OFF;
- explicit live profile required;
- startup clearly records environment identity;
- account/venue/profile mismatch causes preflight failure;
- production credentials are separate from Testnet credentials;
- any material model/prompt behavior change triggers requalification.

## Exit gate

Only a **separate explicit decision** can promote a qualified system beyond paper/Testnet.

---

# 16. Execution checklist by PR

| PR | Branch | Main deliverable | Exit requirement |
|---|---|---|---|
| 1 | `feature/01-baseline-inventory` | Baseline report and preserved local/Testnet work | Baseline reproducible |
| 2 | `feature/02-trade-candidate-contract` | Canonical candidate/decision contracts | Contract tests pass |
| 3 | `feature/03-three-arm-runner` | Rules/gated/model runner | Candidate sets identical |
| 4 | `feature/04-ai-gate-cache` | Bounded AI + deterministic cache | Offline rerun identical |
| 5 | `feature/05-mechanical-trade-audit` | Independent trade audit | Reference run N/N valid |
| 6 | `feature/06-replay-parity` | Backtest/live no-submit replay | Zero unexplained parity drift |
| 7 | `feature/07-risk-hardening` | Risk and idempotency controls | Safety tests pass |
| 8 | `feature/08-decision-journal-dashboard` | Full decision provenance | Fill-to-candidate trace works |
| 9 | `feature/09-binance-testnet-qualification` | Testnet + shadow AI + soak | Testnet criteria pass |
| 10 | `feature/10-live-promotion-controls` | Explicit live-preflight safeguards | Live remains OFF by default |

---

# 17. Standard evidence required before merging each PR

Every PR should include:

```text
1. What changed
2. Why it changed
3. Tests added/updated
4. Commands run
5. Test results
6. Backtest/replay impact if relevant
7. Known limitations
8. Rollback path
9. Exit-gate status: PASS / BLOCKED
```

Do not merge with an unexplained failed exit gate.

---

# 18. Stop conditions

Pause implementation and investigate if any of these occur:

- working local/Testnet code would be overwritten;
- candidate sets differ across experiment arms;
- model can alter side/size/risk unexpectedly;
- cached model replay is not deterministic;
- audit finds unexplained trades;
- replay/live path differs from backtest without explanation;
- restart can duplicate orders;
- paper/Testnet/live configuration is ambiguous;
- Testnet code contacts a live exchange endpoint;
- journal cannot reconcile an exchange fill;
- risk halt fails to block a new submission;
- strategy result depends on a very small number of outlier trades without clear reporting;
- model improvement disappears against the handwritten-gate control.

---

# 19. Current execution position

As of this document:

```text
Strategic roadmap                         DONE
Private Claude Trading Desk reference    DONE
Execution plan                           DONE

Phase 0 — Baseline preservation          NEXT
Phase 1 — Candidate/decision contracts   NOT STARTED
Phase 2 — Three-arm runner               NOT STARTED
Phase 3 — AI gate/cache                  NOT STARTED
Phase 4 — Mechanical audit               NOT STARTED
Phase 5 — Replay parity                  NOT STARTED
Phase 6 — Risk hardening                 NOT STARTED
Phase 7 — Journal/dashboard              NOT STARTED
Phase 8 — Binance Testnet qualification  NOT STARTED
Phase 9 — Statistical qualification      NOT STARTED
Phase 10 — Live controls                 NOT STARTED
```

---

# 20. Immediate next action

Start **Phase 0 only**.

The first implementation session should:

1. inspect `C:\Dev\vibe-trading-test` without destructive Git operations;
2. compare local state with GitHub `main`;
3. identify and preserve any Binance Spot Testnet/CCXT work;
4. run unit/full tests;
5. rerun one known regression backtest;
6. produce the baseline report;
7. stop if any state is unclear rather than resetting the repository.

Only after Phase 0 passes should Phase 1 architecture work begin.

---

## Definition of Done for the overall integration

The integration is complete only when:

- the same candidate set can be evaluated by rules, gates, and AI;
- AI is reproducible, bounded, and fail-closed;
- every trade passes an independent mechanical audit;
- backtest and production-like replay have no unexplained behavioral drift;
- risk controls are automated and regression-tested;
- every fill has full candidate/decision/risk provenance;
- Binance Spot Testnet survives execution/restart/reconciliation testing;
- AI shadow-mode evidence is available before AI controls Testnet trades;
- statistical qualification separates software correctness from strategy edge;
- live mode remains an explicit, separate, opt-in state.
