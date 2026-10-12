# Claude Trading Desk → My_Vibe-Trading Integration Roadmap

**Date:** 2026-10-12  
**Status:** Implementation roadmap  
**Primary repository:** `isam1978mm/My_Vibe-Trading`  
**Reference upstream:** `aabrole/claude-trading-desk`  
**Branch:** `main`

## 1. Executive decision

My_Vibe-Trading remains the primary trading platform. Claude Trading Desk is a reference implementation whose strongest ideas will be ported selectively rather than replacing the existing Vibe architecture.

The target architecture is:

```text
Market data
   ↓
Deterministic strategy engine
   ↓
Immutable trade candidate
   ├── rules arm
   ├── handwritten-gates arm
   └── AI-gated arm
   ↓
Final risk authority
   ↓
Broker/exchange adapter
   ↓
Paper/Testnet execution
   ↓
Journal + parity/audit data + dashboard
```

The AI is never the unrestricted trading engine. It may evaluate a strategy-generated candidate, but it must not invent a new side, bypass risk controls, silently change position size, or directly control withdrawals/transfers.

## 2. Why integrate instead of migrate

Vibe already provides the broader foundation: multi-market data/backtesting, validation tooling, agent infrastructure, dashboarding, broker/exchange extensibility, and `ccxt` as a declared dependency. It also has an established `agent/tests` pytest suite.

Claude Trading Desk contributes a smaller set of especially useful design patterns:

1. identical-candidate three-arm testing (`rules`, `gated`, `model`);
2. AI as a bounded second opinion rather than a free-form trader;
3. deterministic request hashing and response caching for model decisions;
4. independent mechanical trade audits;
5. replaying historical data through the live execution path to detect backtest/live drift;
6. explicit operational guardrails and a decision stream suitable for monitoring.

## 3. Non-negotiable architectural invariants

These rules apply before implementation starts and remain true afterward.

- **One candidate, three arms.** `rules`, `gated`, and `model` must receive the same candidate IDs and market context.
- **No AI side flipping.** If a strategy proposes LONG and the model wants SHORT, the result is `WAIT/REJECT`, never SHORT.
- **Risk is final authority.** The risk layer can veto any action approved by rules or AI.
- **Fail closed.** Model timeout, malformed response, missing key, or provider failure defaults to no new position.
- **Reproducible backtests.** Historical model decisions must be cacheable by a canonical request hash and replayable without new network calls.
- **Paper/Testnet first.** No new feature gets a live-money path as its first validation environment.
- **No secret material in Git.** Exchange/API keys stay in environment/secret storage and test fixtures use fakes.
- **Backtest/live logic parity.** Strategy and risk rules should be shared rather than reimplemented independently for live execution.
- **Every material decision is auditable.** Candidate, filters, model response, risk verdict, intended order, broker response, and realized fill must have correlatable IDs.

## 4. Current-state note before any code changes

The current GitHub `main` declares `ccxt>=4.5.71`, but the Binance Spot Testnet work previously exercised locally is not obvious from the current `main` tree/search results. Do not overwrite or recreate that work blindly.

**Phase 0 must first reconcile:**

- local working tree vs GitHub `main`;
- any unpushed CCXT/Binance Testnet adapter/profile/config changes;
- any experiment-only files that should not become production code;
- the exact commit that represents the current trusted baseline.

Nothing in later phases should begin until that state is preserved in Git.

---

# Implementation phases

## Phase 0 — Preserve the known-good baseline

### Goal
Create a reproducible baseline before architecture changes.

### Tasks

1. Pull/inspect `main` and record the current HEAD SHA.
2. Compare the working PC checkout with GitHub `main`.
3. Preserve any local Binance/CCXT Testnet changes on a dedicated feature branch before rebasing or refactoring.
4. Run the existing fast/unit test suite:

```bash
python -m pytest agent/tests -m unit
```

5. Run the full test suite available in the local environment:

```bash
python -m pytest agent/tests
```

6. Record failures that already exist before this project so they are not misattributed to the integration.
7. Preserve one known backtest fixture/result as a regression baseline.

### Exit gate

- Local/testnet work is committed or otherwise safely preserved.
- Baseline commit is recorded.
- Existing unit tests have a known status.
- A known backtest can be rerun reproducibly.

---

## Phase 1 — Introduce a canonical TradeCandidate / Decision contract

### Goal
Create one immutable object that represents the strategy's opportunity before any gate or model touches it.

### Primary areas

- `agent/backtest/`
- strategy-generation contracts under `agent/src/skills/strategy-generate/`
- new focused module only if no existing contract cleanly fits (prefer extending existing abstractions over parallel architecture).

### Candidate fields

At minimum:

```text
candidate_id
strategy_id / strategy_version
symbol / instrument
market / venue
side
signal_timestamp
observable_market_timestamp
reference_price
entry intent
stop
profit target(s)
raw strategy features/context
risk metadata
source data identity/version where practical
```

`candidate_id` must be deterministic from canonical strategy-visible information, not from model output.

### Decision fields

```text
candidate_id
arm: rules | gated | model
verdict: take | wait/reject
reason codes
confidence/probabilities (optional for rules/gates)
model/provider/version when applicable
request_hash when applicable
latency/cache_hit
created_at
```

### Required tests

Create focused unit tests under `agent/tests/` verifying:

- candidate ID is stable for identical inputs;
- materially different inputs produce different IDs;
- serialization order does not change hashes;
- decision cannot mutate candidate side/stop/target implicitly;
- malformed values fail validation rather than silently becoming zero/default facts.

### Exit gate
All three future decision arms can consume the same `TradeCandidate` without strategy-specific branching in the core comparison layer.

---

## Phase 2 — Add the three-arm experiment runner

### Goal
Make AI value falsifiable rather than comparing unrelated runs.

### Arms

1. **rules** — accept every valid deterministic strategy candidate;
2. **gated** — apply explicit handwritten filters;
3. **model** — ask an AI decision layer to approve/reject the exact same candidate.

### Requirements

- Candidate generation happens once per experiment.
- All arms receive the same ordered candidate set.
- Position sizing/fill assumptions are held constant across arms unless the experiment explicitly studies those variables.
- The report must show candidate-set equality before performance metrics.
- A model cannot be credited for improvement merely because it saw fewer/different opportunities.

### Required output

For each arm:

```text
candidates seen
accepted/rejected
trades
win rate
mean/median R
profit factor
net P&L / return
fees
slippage
max drawdown
Sharpe where appropriate
train/test or walk-forward split metrics
```

And comparisons:

```text
rules vs gated
gated vs model
rules vs model
model/gated overlap
rejection reason breakdown
```

### Exit gate
An assertion or report proves that the three arms began from identical `candidate_id` sets.

---

## Phase 3 — Build the bounded AI gate and deterministic cache

### Goal
Use an LLM/model as a reproducible filter, not an autonomous trader.

### Model contract

Allowed outcomes:

```text
TAKE_PROPOSED
WAIT
```

Optional diagnostics may include confidence, probabilities, risk labels, or explanatory fields, but diagnostics cannot directly create orders.

### Hard restrictions

- proposed LONG cannot become SHORT;
- proposed SHORT cannot become LONG;
- model cannot increase quantity;
- model cannot widen stops;
- model cannot bypass max exposure/loss limits;
- provider/API failure => `WAIT` by default.

### Cache design

Canonical hash should cover:

```text
provider
model/version
prompt/schema version
candidate ID
exact normalized visible state/features
question/criteria schema
```

Store response plus metadata in an append-safe cache or existing Vibe persistence abstraction.

### Required tests

- same request => same hash;
- cached rerun makes zero model network calls;
- model tries to flip side => WAIT;
- timeout => WAIT;
- HTTP/provider failure => WAIT;
- malformed response => WAIT;
- old cache cannot silently satisfy a changed prompt/model schema.

### Exit gate
A complete backtest with a populated model cache can be rerun offline and produce identical model decisions.

---

## Phase 4 — Add an independent mechanical trade audit

### Goal
Verify that executed/backtested trades obey the written strategy rather than letting the strategy validate itself.

### Rule
The audit must read persisted candidate/trade records and recompute rule satisfaction independently. It must not simply call the same signal function that produced the trade.

### Audit checks

At minimum:

- candidate timestamp is causal;
- indicators/features were available at that timestamp;
- entry direction matches strategy signal;
- stop/target relationships are valid;
- risk size matches configured policy within tolerance;
- no forbidden same-bar lookahead;
- costs/slippage reconcile;
- accepted arm decision exists;
- risk approval exists;
- exit reason and P&L reconcile with recorded fills.

### Required report

```text
N / N trades satisfied
0 unexplained trades
0 orphan fills
0 candidates without traceable decision provenance
```

Failures must identify the exact trade/candidate and rule.

### Exit gate
The reference backtest passes `N/N` independent audit checks.

---

## Phase 5 — Backtest/live replay parity

### Goal
Prove that the production execution path interprets the same market sequence the same way as the backtest.

### Design
Introduce a no-submit/replay broker mode or reuse an existing simulation abstraction. Feed a recorded historical session/event stream through the same strategy → gate → risk → order-intent path used in paper/Testnet execution.

### Compare

```text
candidate IDs
candidate timestamps
strategy side
model/gate verdicts
risk verdicts
position sizes
stop/target values
order intent
```

Allow explicit numeric tolerances only where feed precision requires them.

### Required tests

- a deterministic replay fixture has zero unexplained differences;
- restart during replay does not duplicate an order intent;
- replay cannot contact a live broker;
- replay's model path is cache-only/offline when validating reproducibility.

### Exit gate
A known session produces exact candidate/decision parity between research/backtest and the no-submit live path.

---

## Phase 6 — Harden final risk authority

### Goal
Ensure a correct signal/model decision still cannot create an unsafe order.

### Required controls

- global kill switch;
- per-strategy enable/disable;
- max daily loss / drawdown halt;
- max open positions;
- max position and portfolio exposure;
- max risk per trade;
- minimum/maximum order sanity checks;
- duplicate-order/idempotency protection;
- persistence across process restart;
- stale-data rejection;
- bad-side stop rejection;
- explicit Testnet/paper/live account separation;
- flatten behavior where market/instrument semantics require it.

### Rule
Risk checks execute **after** the strategy/model decision and immediately before order submission. AI approval is never sufficient authorization.

### Required tests

- kill switch blocks new entries;
- risk veto overrides model TAKE;
- max exposure is enforced;
- daily loss halt persists across restart;
- stale data is rejected;
- malformed stop is rejected;
- duplicate candidate/order after restart does not resubmit;
- live credentials/endpoints are not required for any unit test.

### Exit gate
Every unsafe scenario above has an automated regression test.

---

## Phase 7 — Decision stream, journal, and dashboard observability

### Goal
Make every trade explainable after the fact.

### Persist for each candidate

```text
candidate_id
strategy/version
market snapshot identity
rules result
gate result + reason
model request_hash
model/provider/version
model response/confidence
cache hit/miss
risk verdict + reason
order intent
broker/exchange order ID
fill(s)
fees/slippage
realized P&L
```

### Dashboard additions

Use the existing dashboard rather than creating a second monitoring UI. Add views/filters for:

- strategy;
- symbol;
- three-arm comparison;
- AI approval/rejection rate;
- risk vetoes;
- model latency/errors/cache hits;
- broker rejects;
- parity/audit failures;
- equity/drawdown and net-vs-gross performance.

### Exit gate
Starting from any fill, an operator can trace backward to its candidate, decision arm, risk approval, and source strategy context.

---

## Phase 8 — Reconcile and qualify Binance Spot Testnet / CCXT

### Goal
Use the existing Vibe/CCXT direction rather than adding an Alpaca-specific execution stack from Claude Trading Desk.

### First step
Locate and preserve the previously tested Binance Spot Testnet work from the local checkout. If it is not in `main`, merge it through its own reviewed feature branch before adapting the new decision/risk contracts.

### Qualification sequence

1. **dry/no-submit mode** — generate order intents only;
2. **Binance Spot Testnet** — smallest safe test orders;
3. verify create/fill/cancel/order-state reconciliation;
4. verify restart/idempotency behavior;
5. run model gate in **monitor-only shadow mode** first;
6. enable model gating on Testnet only after shadow results are understood;
7. multi-day soak with dashboard/journal enabled.

### Testnet acceptance criteria

- zero accidental live endpoint calls;
- zero duplicate orders under restart tests;
- every exchange fill reconciles to one internal order intent;
- fees/fill prices are recorded rather than assumed;
- model failure never creates a trade;
- risk halt prevents submissions immediately;
- process can recover state after restart;
- no unexplained parity/audit failures.

---

## Phase 9 — Statistical qualification before any live promotion

### Goal
Separate functioning software from a proven trading edge.

Use Vibe's existing backtest/validation capabilities (including `agent/backtest/validation.py`) and add missing experiment-specific metrics rather than creating a second validation framework.

### Required evidence for a strategy/model combination

- adequate trade/sample count;
- net results after realistic costs;
- train/test or walk-forward performance;
- bootstrap confidence interval where applicable;
- Monte Carlo/permutation evidence where applicable;
- stability across meaningful periods/regimes;
- model arm compared directly with handwritten-gate control;
- no result driven by a few outlier trades without clearly reporting that concentration;
- audit and parity gates already passed.

A model arm that does not beat the simpler handwritten gate robustly is not promoted merely because it beats raw rules.

### Exit gate
A written strategy qualification report states one of two outcomes clearly:

- **QUALIFIED FOR CONTINUED PAPER/TESTNET EVALUATION**, or
- **NO EVIDENCE OF EDGE — STOP/TUNE ONLY UNDER A NEW PRE-REGISTERED EXPERIMENT**.

---

## Phase 10 — Optional live-money promotion controls

### Goal
Make live trading a separate explicit product state, never an accidental configuration change.

### Preconditions

All prior gates pass, plus:

- extended paper/Testnet soak;
- operator reviews credentials/permissions;
- withdrawal permissions are absent;
- account/venue allowlist is explicit;
- strategy/version/model/prompt versions are pinned;
- risk limits are lower than research maxima;
- emergency stop has been tested;
- deployment rollback procedure is documented and tested.

### Live safety design

- live mode defaults OFF;
- explicit live profile/account required;
- startup prints/records environment identity;
- production preflight fails if account/venue/profile mismatch;
- first live deployment uses minimal exposure;
- model/provider update requires requalification if decision behavior can change.

---

# 5. Recommended PR sequence

Do not implement this as one large branch. Use small, independently reviewable PRs:

| PR | Scope | Must pass before merge |
|---|---|---|
| 1 | Documentation + baseline inventory | Existing test status recorded |
| 2 | TradeCandidate/Decision contracts | New contract unit tests |
| 3 | Three-arm experiment runner | Candidate-set equality test |
| 4 | Bounded model gate + deterministic cache | Offline-identical rerun |
| 5 | Independent trade audit | Reference result reports N/N |
| 6 | Backtest/live replay parity | Zero unexplained parity differences |
| 7 | Risk hardening | All safety regression tests |
| 8 | Decision journal/dashboard | Fill-to-candidate trace works |
| 9 | CCXT/Binance Testnet reconciliation + soak tooling | Testnet acceptance gates |
| 10 | Optional live promotion controls | Explicit preflight + live-off default |

Each PR should include tests in `agent/tests/` alongside the production change and should avoid unrelated cleanup.

# 6. Validation matrix

| Layer | Question | Gate |
|---|---|---|
| Unit | Does each component behave correctly? | pytest passes |
| Candidate integrity | Did all arms see identical opportunities? | candidate IDs equal |
| Model reproducibility | Can the model backtest replay offline? | 100% cached identical decisions |
| Mechanical audit | Did trades obey the rules? | N/N |
| Research/live parity | Does replay produce the same intent? | zero unexplained mismatch |
| Statistical | Is there evidence of edge after costs? | documented qualification |
| Operational | Can faults cause unsafe orders? | fault-injection tests pass |
| Exchange | Do actual Testnet states reconcile? | zero orphan/duplicate orders |
| Soak | Is the system stable over time? | no critical incidents during defined soak |
| Live | Is live activation deliberate and bounded? | explicit human-controlled promotion |

# 7. Key automated tests to add

The final implementation should include, at minimum, tests for:

1. stable canonical candidate hashing;
2. same candidate set across all experiment arms;
3. AI cannot flip direction;
4. AI/provider failure fails closed;
5. risk veto overrides every upstream approval;
6. cache makes historical model decisions reproducible without network;
7. changed prompt/model/schema invalidates the relevant cache identity;
8. independent audit detects a deliberately corrupted trade;
9. no same-bar/lookahead leakage in the chosen strategy path;
10. slippage/fees reconcile from ideal/gross to net P&L;
11. replay/live path matches backtest candidate and order intent;
12. stale market data blocks entry;
13. kill switch blocks entry;
14. daily loss/drawdown halt persists;
15. max position/exposure limits work;
16. bad stop direction is rejected;
17. repeated candidate after restart is idempotent;
18. Testnet/live environment mismatch fails startup/preflight;
19. broker rejection is recorded and does not become an internal fill;
20. every fill can be traced to exactly one order intent and candidate.

# 8. Metrics to monitor

### Strategy/research

- candidates/day;
- arm acceptance rate;
- rule/gate/model overlap;
- rejection reason distribution;
- win rate;
- average and median R;
- profit factor;
- gross vs net return;
- fees/slippage drag;
- max drawdown;
- Sharpe and relevant confidence/validation statistics.

### Model

- approval rate;
- disagreement with handwritten gates;
- confidence calibration;
- provider error/timeout rate;
- P50/P95 latency;
- cache hit rate;
- token/API cost;
- behavior by model/prompt version.

### Execution/operations

- intended orders vs submitted orders;
- broker rejects;
- fills and partial fills;
- realized vs modeled slippage;
- state reconciliation mismatches;
- duplicate-prevention events;
- risk vetoes;
- kill-switch activations;
- parity/audit failures;
- process restarts/recoveries.

# 9. Security requirements

- Never commit exchange, broker, or model API secrets.
- Use least-privilege exchange permissions; trading only where possible, never withdrawal permissions for the bot.
- Keep Testnet/paper credentials completely separate from live credentials.
- Do not log secrets in model prompts, decision journals, exceptions, or dashboard payloads.
- Validate that model-visible state contains only information required for the decision.
- Treat model text as untrusted data; parse against a strict schema.
- Live deployment must use an allowlist of accounts/venues/strategies.

# 10. Fork/upstream policy for Claude Trading Desk

The Claude Trading Desk fork is a **reference fork**, not the new production base.

Recommended policy:

```text
origin  = personal fork of aabrole/claude-trading-desk
upstream = aabrole/claude-trading-desk
```

Use it to:

- inspect upstream changes;
- run the supplied ORB/SMA examples independently;
- reproduce useful ideas before porting them;
- maintain notes/experiments that are specific to that project.

Do **not** put My_Vibe-Trading production features into the Claude plugin tree merely to keep the two repos synchronized. Port concepts through reviewed Vibe PRs instead.

# 11. Definition of Done for the integration project

The integration is complete only when all of the following are true:

- [ ] existing local Binance/CCXT Testnet work is reconciled and preserved;
- [ ] canonical candidate/decision contracts exist;
- [ ] rules/gated/model arms use identical candidate sets;
- [ ] AI cannot flip a candidate or bypass risk;
- [ ] historical AI decisions replay offline identically;
- [ ] independent audit reports N/N on the qualification run;
- [ ] backtest/live replay has zero unexplained decision/order-intent mismatch;
- [ ] required safety controls have automated tests;
- [ ] journal/dashboard can trace every fill to candidate → decision → risk → order;
- [ ] Binance Spot Testnet passes restart/idempotency/reconciliation tests;
- [ ] defined Testnet soak completes without critical safety incidents;
- [ ] strategy qualification uses out-of-sample/walk-forward and cost-aware evidence;
- [ ] live mode remains OFF by default and requires explicit promotion/preflight.

# 12. Stop conditions

Pause implementation and investigate rather than tuning around the problem if any of these occur:

- candidate sets differ between experiment arms;
- backtest/live replay differences cannot be explained;
- a model decision cannot be reproduced from stored context/hash;
- an exchange fill lacks a unique internal order/candidate lineage;
- duplicate orders occur after restart;
- risk veto can be bypassed;
- testnet code can accidentally select a live endpoint/account;
- statistical improvement exists only through repeated parameter/prompt tuning on the test period.

# 13. Immediate next actions

Execute in this order:

1. **Baseline inventory:** reconcile local checkout vs GitHub `main`, especially the known CCXT/Binance Testnet work.
2. **Run/record tests:** `python -m pytest agent/tests -m unit`, then the full suite practical for the environment.
3. **Create PR 2 design:** identify the existing Vibe domain object closest to a trade candidate before creating a new package.
4. **Implement candidate/decision contracts with tests.**
5. **Build the three-arm runner before adding any new AI provider logic.**
6. **Only after raw + gated arms are trustworthy, add the bounded model gate/cache.**
7. Proceed through audit → parity → risk → observability → Binance Testnet soak.

This order prevents the most common failure mode: adding an impressive AI layer before there is a trustworthy experiment, execution path, and safety envelope underneath it.
