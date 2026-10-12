# Claude Trading Desk → My_Vibe-Trading Canonical Integration Plan

**Date:** 2026-10-12  
**Status:** Canonical plan — supersedes the earlier roadmap and execution-plan documents  
**Primary repository:** `isam1978mm/My_Vibe-Trading`  
**Reference repository:** private `isam1978mm/claude-trading-desk`  
**Implementation target:** Vibe remains the platform; Claude Trading Desk is a reference for selected design patterns only.

## 1. Executive decision

Do **not** execute the previous ten-branch plan as written.

The corrected approach is:

1. protect the currently running Donchian soak and do not mutate either active worktree while it is running;
2. preserve the local-only gateway and Track B work before any checkout, pull, stash, rebase, reset, merge, or branch-reconciliation step;
3. establish a post-soak baseline that actually contains the code being tested;
4. adapt Claude Trading Desk concepts to Vibe's **target-allocation** model rather than forcing a discrete-entry/stop/target trade contract onto Donchian;
5. require experiment pre-registration and statistical-power eligibility **before** adding a gate/model experiment;
6. treat historical LLM decisions as engineering/reproducibility tests only, not as evidence of predictive edge;
7. make exits and other risk-reducing allocation changes bypass any AI gate;
8. build risk authority and decision journaling before audit/parity layers that depend on them;
9. qualify changes on Binance Spot Testnet only after the baseline, contracts, risk, and parity work are complete;
10. keep real-money trading out of scope for this plan.

---

## 2. Current blocking state: active Donchian soak

The active Donchian run must be treated as immutable infrastructure until it finishes.

Current run information supplied for this plan:

- run started: `2026-10-12 14:44 UTC`;
- scheduled end: `2026-10-19`;
- first tick: `2026-10-13 00:05 UTC`;
- the runner loads its gateway directly from the worktree path (`donchian_paper.py:40`).

### While the soak is running

**Forbidden in either worktree:**

- `git pull`;
- `git checkout` / `git switch`;
- `git stash`;
- `git rebase`;
- `git reset`;
- `git clean`;
- merge/cherry-pick operations;
- dependency upgrades;
- edits to files used by the runner;
- test runs or tooling that can rewrite runtime/config/state files;
- any attempt to make the local tree match remote `main`.

**Allowed:**

- read-only inspection such as `git status`, `git diff`, `git log`, file reads, and process/log inspection;
- a filesystem-level backup/copy of the local-only source to a separate directory or storage location;
- checksums/manifests of that backup;
- documentation-only commits made remotely through GitHub, provided the active machine does **not** pull them during the soak.

### Immediate protection requirement

The gateway and Track B code currently exist on one disk only. That is the first risk to remove.

Before the soak ends, create a **read-only external snapshot** of the local source/worktrees. The snapshot must include modified and untracked source files; a fresh clone is not sufficient because a clone cannot capture local-only work.

Record:

```text
snapshot timestamp
source path(s)
backup path
local HEAD SHA(s)
git status --short output
list of modified/untracked source files
checksum/manifest location
```

Do not use Git branch manipulation to perform this preservation while the soak is active.

---

## 3. No feature branches from current `main` yet

The previous plan proposed a sequence of feature branches cut from `main`. That is unsafe because current `main` does not contain all of the local gateway/Track B work under test.

### Correct branch rule

No integration feature branch is created until all of these are true:

1. the current soak has ended or been intentionally stopped;
2. no process is loading code from the worktree;
3. the external snapshot has been verified;
4. local-only source has been inventoried;
5. the intended local code has been committed to a **preservation branch**;
6. that preservation branch has been pushed successfully;
7. a reviewed integration-baseline commit has been selected.

All later feature branches are cut from the **integration baseline**, not blindly from the old GitHub `main`.

---

# 4. Corrected domain model: allocation intents, not discrete trades

Claude Trading Desk's worked contract assumes discrete trades with side, stop, target and R-multiples. That is not the correct abstraction for the current Donchian/Vibe path.

Vibe's relevant strategy flow produces target portfolio weights. Donchian v1 is a long/cash spot ensemble. It has no required profit target and its strategy semantics are expressed as changes in desired allocation.

Therefore the integration contract must model **portfolio allocation intent**.

## 4.1 Canonical proposal

Use a neutral proposal such as:

```text
AllocationProposal
- proposal_id
- strategy_id
- strategy_version
- decision_timestamp
- observable_market_timestamp
- venue / market
- current_weights
- proposed_target_weights
- per-symbol allocation deltas
- strategy-visible features/context
- source-data identity/version where practical
```

For each symbol, derive an action from the allocation delta:

```text
INCREASE_RISK
REDUCE_RISK
EXIT
HOLD
```

A stop, target, side, or R-multiple is **optional strategy-specific metadata**, not a required platform contract.

## 4.2 Gate/model contract

For a long/cash spot strategy, a gate/model may only affect **risk-increasing** allocation changes.

Allowed model action for a proposed increase:

```text
ALLOW_PROPOSED_INCREASE
SUPPRESS_INCREASE
```

The model may not:

- create a symbol that the strategy did not propose;
- create a short allocation for a long/cash strategy;
- increase a target above the deterministic strategy's proposed target;
- turn a reduction into an increase;
- widen platform risk limits;
- alter exit semantics.

## 4.3 Exits and reductions bypass the model

This is non-negotiable.

If the deterministic strategy requests a reduction or exit, that risk-reducing intent bypasses the AI gate and proceeds directly to deterministic risk/sanity checks and execution.

A model response of `WAIT`, timeout, malformed output, missing key, or provider failure must **never** turn an exit/reduction into a hold.

The risk layer may reject only for execution/safety impossibility (for example malformed quantity, unavailable balance, invalid venue state), not because the AI disagreed with the exit.

## 4.4 Metrics

Do not require `mean R`/`median R` for Donchian or other allocation strategies that do not define stop-based R.

Primary platform-compatible metrics include:

```text
net return / CAGR where appropriate
max drawdown
Sharpe / Sortino where appropriate
turnover
market exposure
transaction costs / slippage
allocation changes
round trips when meaningful
upside/downside capture where meaningful
rejected risk increases
missed upside after rejection
avoided drawdown after rejection
```

R-based metrics remain optional for strategies whose contract genuinely defines R.

---

# 5. LLM look-ahead rule

A deterministic cache solves **reproducibility**. It does not solve historical information leakage.

A current general-purpose LLM may have been trained on market history covering part or all of a 2018–2026 backtest. Therefore a historical AI arm cannot be treated as a causal out-of-sample test merely because the model only sees contemporaneous features in the prompt.

## 5.1 Historical model runs

Allowed purposes:

- plumbing tests;
- schema validation;
- cache/replay validation;
- latency/failure behavior;
- qualitative comparison of model vs deterministic gate decisions.

Forbidden claim:

> historical model-arm P&L proves the LLM adds predictive edge.

## 5.2 Valid performance evidence

For the current project, model performance evidence must be **prospective** unless a separately documented methodology can prove a strict pre-evaluation training cutoff and causal information set.

Prospective decisions must be:

- generated after the experiment freeze time;
- timestamped before the outcome bar/data is available;
- written immutably to the journal/cache;
- tied to an exact provider/model identifier;
- tied to prompt/schema hashes;
- generated without future-aware browsing/retrieval;
- never regenerated retrospectively to replace an unfavorable decision.

If a provider silently changes an unpinned `latest` model, that starts a new experiment unless equivalence can be demonstrated.

---

# 6. Statistical-power eligibility comes before the experiment

Pre-registration belongs near the start, not at the end.

The current Donchian audit has only about 20 BTC and 38 ETH round trips over roughly 3.75 years. That sample is not sufficient to claim a robust difference between rules, handwritten gate, and model gate.

Prospective shadow evaluation on daily bars would also accumulate independent evidence very slowly.

## Current Donchian status

**Donchian v1 is not currently eligible for an AI-vs-gate edge claim.**

It may still be used for:

- platform regression;
- execution qualification;
- logging/journal tests;
- shadow plumbing;
- replay/parity tests.

But model/gated performance superiority is **deferred** until a pre-registered power/sample rule is satisfied.

Do not manufacture significance by treating highly dependent daily observations as independent samples.

---

# 7. Mandatory pre-registration before any gate/model experiment

Before implementing or tuning a strategy-specific gate/model experiment, freeze a one-page experiment spec containing:

```text
strategy name/version/SHA
market and instruments
bar frequency
evaluation start/end rules
exact deterministic baseline
hypothesis: what failure mode the gate is intended to reduce
handwritten gate rules and thresholds
model provider
exact model/version identifier
prompt/schema version + hash
model-visible features
forbidden inputs/retrieval
primary success metric
secondary metrics
cost/slippage model
minimum effective sample or power rule
prospective decision-recording method
failure/stop rules
rules for model/provider/prompt changes
rules for post-freeze tuning
```

No gate is tuned after the evaluation window begins. A changed hypothesis, threshold, prompt, model, or feature set creates a new experiment/version.

If the minimum-sample/power requirement is undefined, the experiment is **BLOCKED**.

---

# 8. Correct execution order

## Stage S0 — Active-soak protection (NOW)

**Goal:** Finish the existing Donchian soak without changing its code environment and remove the single-disk risk.

Tasks:

- leave both active worktrees untouched;
- create and verify an external snapshot of local-only source;
- record read-only Git/worktree identity;
- monitor the soak only;
- do not pull the remote documentation commits into the active tree.

**Exit gate:** soak is complete/stopped; external snapshot verified; runner no longer uses the worktree.

---

## Stage S1 — Post-soak preservation and true baseline

**Goal:** Create the first Git baseline that actually includes the code that was running.

Order matters:

1. archive the soak output/state/manifests;
2. confirm the runner is stopped;
3. record local branch, HEAD, status, diff and untracked-source inventory;
4. compare against the verified external snapshot;
5. create a preservation branch from the current local state;
6. commit intended gateway/Track B source only — never secrets/runtime artifacts;
7. push the preservation branch;
8. verify the remote branch contains the preserved files;
9. only then reconcile with remote `main` and choose an integration-baseline commit/tag.

### Test baseline

`-m unit` is not the baseline because it selects only a subset of the suite.

After the soak, first record collection:

```bash
python -m pytest agent/tests --collect-only -q
```

Then run the full feasible suite for the baseline:

```bash
python -m pytest agent/tests -q
```

Record exact collected/passed/failed/skipped/xfailed counts and environment versions.

Targeted markers such as `-m unit` are useful for iteration later but do not replace the full baseline status.

**Exit gate:** local-only work exists in a pushed preservation branch; integration baseline selected; complete test inventory/status recorded; baseline Donchian result and soak artifacts preserved.

---

## Stage S2 — Strategy/experiment eligibility and pre-registration

**Goal:** Decide whether a gate/model experiment is statistically and causally meaningful before writing it.

For Donchian v1, record current status as:

```text
platform/execution testing: ELIGIBLE
historical LLM edge claim: NOT VALID
prospective AI-vs-gate edge claim: INSUFFICIENT SAMPLE / DEFERRED
```

If a future strategy has enough effective decision events, write and freeze the experiment spec from Section 7 before implementation.

**Exit gate:** either (A) experiment is pre-registered and sample/power eligible, or (B) AI/gate edge testing is explicitly deferred and work proceeds only on platform architecture.

---

## Stage S3 — Allocation/decision contract

**Goal:** Introduce a strategy-neutral allocation proposal contract compatible with Vibe's target-weight semantics.

Important constraints:

- do not force this into `agent/backtest/` merely because the old plan named that directory;
- first map the preserved Track B/spot execution path and existing domain abstractions;
- do not reuse a perpetual-biased abstraction for spot until its assumptions are audited;
- prefer an existing neutral portfolio/execution domain module if one exists; otherwise add one only after the post-soak code inventory.

Tests must cover:

- deterministic proposal identity;
- stable serialization;
- current vs target weights;
- increase/reduction/exit/hold classification;
- model cannot increase beyond deterministic proposal;
- model cannot create short exposure in long/cash mode;
- exit/reduction cannot be converted to hold by model output/failure.

**Exit gate:** existing Donchian target weights can be represented losslessly without inventing stop/target/R fields.

---

## Stage S4 — Risk authority and decision journal foundation

**Goal:** Build the components that later audit/parity phases depend on.

Required risk semantics:

- deterministic exit/reduction has priority over model gating;
- gate/model can only suppress risk increases;
- risk authority runs immediately before order intent/submission;
- kill/halt, exposure, stale-data, balance, min-order and idempotency checks remain deterministic;
- AI can never override a risk veto.

Journal the chain:

```text
strategy proposal
allocation classification
optional gate/model shadow decision
risk verdict
order intent
broker/exchange response
fill/reconciliation
```

**Exit gate:** a proposal can be traced through deterministic risk and journal events before audit/parity work begins.

---

## Stage S5 — Gate/model adapter, initially shadow-only

**Goal:** Port the useful Claude Trading Desk idea without pretending historical model P&L is valid.

Implement only after Stage S2 determines eligibility.

For Donchian v1, any model integration remains **shadow-only** until a valid prospective experiment exists.

Historical calls may populate/replay caches for engineering tests, but reports must label those results:

```text
ENGINEERING / NON-CAUSAL MODEL REPLAY — NOT PERFORMANCE EVIDENCE
```

If a pre-registered higher-sample strategy is used later, rules/gated/model must receive the same deterministic allocation proposals.

**Exit gate:** model failure cannot block exits/reductions, cannot increase risk, and cached replay is deterministic.

---

## Stage S6 — Independent audit

**Goal:** Audit the allocation/risk/order chain using spot/weight semantics.

Audit at minimum:

- proposal timestamps are causal;
- features were observable at the decision timestamp;
- target-weight changes match frozen strategy rules;
- exits/reductions bypass model gating;
- model never increases risk beyond the deterministic proposal;
- risk verdict exists before risk-increasing order intent;
- costs/fills reconcile;
- no orphan order/fill exists;
- no duplicate intent is emitted after restart.

Do not require stops/targets/R unless that strategy actually defines them.

**Exit gate:** reference replay/soak artifacts produce zero unexplained allocation/order discrepancies.

---

## Stage S7 — Backtest/replay/live-path parity

**Goal:** Verify that the research path and production-like no-submit path interpret the same data consistently.

Compare:

```text
proposal IDs
timestamps
current weights
target weights
allocation action classifications
gate/model decisions when applicable
risk verdicts
order intents
```

Replay must not submit orders and must not contact live-money endpoints.

**Exit gate:** zero unexplained parity differences for the selected fixture.

---

## Stage S8 — Observability/dashboard

**Goal:** Surface the journal rather than creating a parallel truth source.

Show:

- deterministic proposal/current/target weights;
- gate/model shadow verdict where applicable;
- risk verdict and reason;
- order/fill reconciliation;
- cache/model identity;
- parity/audit failures;
- turnover/costs/exposure/drawdown;
- whether a result is historical engineering replay or prospective evidence.

**Exit gate:** any fill can be traced backward to its proposal, risk verdict, and execution context.

---

## Stage S9 — Post-integration Binance Spot Testnet qualification

**Goal:** Qualify the modified architecture without touching real money.

Sequence:

1. no-submit order-intent replay;
2. Binance Spot Testnet reconciliation;
3. restart/idempotency tests;
4. deterministic risk-halt test;
5. shadow model only unless Stage S2 has a valid prospective experiment;
6. multi-day post-integration soak.

The currently running Donchian soak is a **baseline soak**, not proof that future integration changes are qualified.

**Exit gate:** no accidental live endpoint use, no duplicate orders, every Testnet fill reconciles, risk halts work, and no unexplained audit/parity failure remains.

---

## Stage S10 — Statistical evaluation and promotion decision

**Goal:** Separate functioning software from evidence of edge.

For deterministic strategy changes, use appropriate Vibe validation tools only after confirming their assumptions fit spot/weight semantics.

For any AI/gate claim:

- use the pre-registered primary metric;
- use only causally valid/prospective model decisions for edge claims;
- account for dependence/effective sample size;
- compare model against the handwritten-gate control, not merely raw rules;
- report costs, drawdown, concentration and regime sensitivity;
- do not promote on a statistically underpowered result.

Possible outcomes:

```text
PLATFORM QUALIFIED — MODEL EDGE NOT TESTED
PLATFORM QUALIFIED — MODEL EXPERIMENT STILL UNDERPOWERED
MODEL/GATE EXPERIMENT REJECTED
MODEL/GATE EXPERIMENT QUALIFIED FOR FURTHER TESTNET SHADOWING
```

Real-money deployment is not part of this plan.

---

# 9. Canonical stop conditions

This is the **single** stop-condition list for this integration plan.

Stop and do not advance if any of these is true:

1. the baseline soak is still using the active worktree;
2. local-only gateway/Track B source is not externally backed up;
3. local-only source is not preserved in a pushed Git branch after the soak;
4. the integration baseline has not been selected and recorded;
5. full test collection/baseline status is unknown;
6. a gate/model experiment lacks a frozen hypothesis and deterministic control;
7. minimum effective sample/power criteria are undefined or not met;
8. model/provider/prompt/schema identity is not pinned/recorded;
9. a historical LLM replay is being presented as predictive out-of-sample evidence;
10. any model path can block or reverse a deterministic exit/reduction;
11. risk authority/journal provenance required by the audit does not exist yet;
12. replay/parity has unexplained differences;
13. any step would submit to a real-money endpoint or require real-money trading.

---

# 10. Branch/PR sequence after the baseline exists

Do **not** pre-create these branches now. Create each only when its prerequisite is satisfied, and base it on the reviewed integration baseline/current merged integration state.

| PR | Scope | Gate before merge |
|---|---|---|
| P0 | Preserve local Track B/gateway baseline after soak | Remote preservation verified |
| P1 | Baseline inventory/test record | Full collection/status recorded |
| P2 | Allocation proposal/decision contract | Weight semantics + exit-bypass tests pass |
| P3 | Risk authority + decision journal | Risk/journal provenance tests pass |
| P4 | Shadow gate/model adapter and deterministic cache | No risk increase/exit blocking; replay deterministic |
| P5 | Independent allocation audit | Zero unexplained audit failures |
| P6 | Backtest/no-submit parity | Zero unexplained parity failures |
| P7 | Dashboard/observability | Fill→proposal trace works |
| P8 | Post-integration Binance Testnet qualification | Testnet/restart/idempotency gates pass |
| P9 | Statistical evaluation report | Causal/sample-power rules respected |

A model/gate PR is optional and may remain shadow-only indefinitely if Stage S2 says the strategy is underpowered.

---

# 11. Documentation policy

The repository's `.gitignore` ignores `docs/`. Existing files already committed there remain tracked, but new local documentation created under `docs/` can be silently ignored.

Therefore this root-level file is the canonical integration plan:

```text
CLAUDE_TRADING_DESK_INTEGRATION_PLAN.md
```

The two earlier files under `docs/` are retained only as short pointers to this canonical document so old links do not break. They are not independent sources of requirements.

---

# 12. Immediate next action

**Do not start coding the integration and do not reconcile Git while the Donchian soak is running.**

The immediate action is only:

1. leave the active worktrees unchanged;
2. make and verify an external snapshot of the local-only gateway/Track B source;
3. record the current local Git identities/status read-only;
4. allow the existing soak to finish;
5. after the runner is stopped, execute Stage S1 exactly in order.

That preserves the evidence from the running qualification and removes the much larger risk: losing the only copy of the actual Track B/gateway work.