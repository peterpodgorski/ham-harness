# Skill: /formalize

## Purpose
Prove the approved Gherkin is internally consistent before architecture or code
is generated, and declare the relations that define derived values. Produce a
**behavioural** Quint model (black-box, interface-level), extend the
**structural** Alloy domain model for the context, and run machine checking,
reachability, and the vacuity gate. Neither model encodes storage or
derivation (`architecture/rules.md` rules 6–7).

## When to Use
- **Entry point — any time** the story's `features/` exist and the models must be
  produced or changed, or a formal gate (`model_behaviour` / `model_structure`)
  has failed.
- **Anchor:** `formalize <story>`.
- It is the hard gate before /explain (plan), but it is still a legal direct
  entry; earlier stages need not have run in this session.

## Inputs
- Approved `stories/<story-name>/features/*.feature`.
- Approved `stories/<story-name>/story-map.md` (threat narrative).
- `lexicon/<context>.yaml` (the ubiquitous language).
- `architecture/<context>/pipeline.yaml` — which gates this context runs.

## Which gates to run

Resolve the context's pipeline first and run only its **`formalize`-phase**
enabled gates (`model_structure`, `model_behaviour`):

```sh
python3 tools/pipeline/pipeline.py plan --context <context>
```

Do not run a gate the context has disabled, and do not skip one it has enabled.
`vocabulary` runs in `/gherkin`; the `bdd`-phase gates run in `/bdd`.

## Outputs
- `stories/<story-name>/formal/invariants.qnt` — **the formal specification**,
  machine-checked. There is no Markdown transcription: a hand-written spec doc
  is guaranteed to drift, and agents will read the stale doc instead of the
  model. The `.qnt` model is the single source of truth for states,
  transitions, and behavioural invariants.
  - It contains **only invariants** and helper `pure def`/`def`s. Every
    top-level `val`/`temporal` in this file is treated as an invariant by the
    gate; do not put reachability or other helpers here as `val`.
- `stories/<story-name>/formal/reachability.qnt` — the reachability witnesses
  (top-level `val` booleans), importing the model. One per claimed state.
- `architecture/<context>/domain.als` — the **living context-level structural
  domain model**: cross-feature entities, relations, fixed mappings and
  append-only/unique-key invariants. Story work *edits* this model; it is not
  re-authored per story. Temporal models follow the replay conventions (one
  `State`, `lastAction'`, argument fields) — `architecture/rules.md` rule 8.
- `lexicon/<context>.yaml` —
  - `derivation` relations for every pure derived value (balance, projection,
    totals, …). **Derived arithmetic lives here, not in the model.**
  - a `quint:` section (keyed by `.qnt` path) declaring the model's `actions`,
    `invariants` (owned by terms), `witnesses`, and `vacuity.corruptions`.
  - an `alloy:` section (keyed by `.als` path) declaring the model's `sigs`,
    `checks`, `witnesses`, and MBT `conventions`.
- `stories/<story-name>/formal-report.md` containing:
  - Raw Quint/Apalache/TLC output (per spec).
  - Raw Alloy `exec` output (per context model) and the `alloy_check.py` result.
  - Consistency results (no invariant violations, no deadlock).
  - Reachability results.
  - Transition-property preservation.
  - Vacuity result (Quint perturbations; Alloy inhabitation witnesses).
  - Pass / Fail with contradictions and remediation steps.

## Environment
- `make` is the **user's** interface and is intentionally absent from the agent
  container — never invoke it. Gates are same-named `Makefile` targets: read the
  target and run its underlying commands directly. A non-zero exit is a gate failure.
- `quint` is on PATH (see `containers/Containerfile.pi`). `java` is present for
  Apalache. If `quint` is missing, the gate **cannot pass** — do not fall back
  to manual reasoning.
- **Quint exits non-zero on failure.** Rely on exit codes:
  - `quint typecheck` — parse + effect/type check.
  - `quint run` — simulation via the Rust evaluator; checks state invariants
    and `--witnesses`; writes ITF traces; used by `quint-connect` for MBT.
  - `quint verify` — exhaustive, via **Apalache** by default. Checks state
    invariants and **deadlock** (bounded by `--max-steps`).
  - `quint verify --backend tlc` — required for `temporal` transition
    properties (Apalache's temporal support is experimental and prompts
    interactively). TLC needs a **finite** state space: keep every command
    guarded/bounded and use a one-shot fault in vacuity.
- The vacuity gate (`tools/lexicon/quint_vacuity_check.py`) injects a one-shot
  fault action built from the lexicon's `quint.vacuity.corruptions` into a copy
  of the model and requires each invariant to be falsifiable (state via
  Apalache, temporal via TLC). A vacuous invariant must be rewritten or
  explicitly exempted with a reason.
- Alloy 6.2 is installed as `org.alloytools.alloy.dist.jar` (see
  `containers/Containerfile.pi`; `ALLOY_JAR` overrides the path). `java` runs
  `exec`.
- The Alloy vacuity gate (`tools/lexicon/alloy_vacuity_check.py`) injects the
  lexicon's `alloy.vacuity.corruptions` into a copy of the model at the
  `vacuity-injection-point` marker and requires every non-exempt check's
  violation to be SAT. Checks true by construction must be listed under
  `vacuity.exemptions` with a reason.
- **Alloy `exec` exits non-zero on `expect` mismatch.** Commands declare their
  expectation: `check … expect 0` (must be UNSAT), `run … expect 1` (must be
  SAT). A parse/syntax error also exits non-zero. Without `expect`, `exec`
  exits 0 even when a `check` finds a counterexample — the gate would silently
  pass, so `expect` is mandatory.
- The Alloy vocabulary/convention gate is `tools/lexicon/alloy_check.py`. It
  rejects `Int` arithmetic in a domain model and requires the replay
  conventions on temporal models.

## Encoding conventions (Quint)
- A model is `module <name> { … }`. Functions/actions are `def`/`action`;
  a `def` qualifier appears in the AST as `action`/`val`/`temporal`/`pureval`.
- **Group all observable state under one `state` record.** Command actions then
  update a single variable, which keeps the effect system happy when they are
  combined under `any` (Quint requires all `any` branches to update the same
  variable set). Per-action frame conditions disappear.
  ```quint
  type ViewState = { expenses: List[Expense], selected_month: int, view_mode: str }
  var state: ViewState
  ```
- `action init` assigns `state'` to the initial value.
- Each command / navigation step is `action <camelCaseName>` assigning `state'`:
  ```quint
  action recordMarchExpense = all {
    state.expenses.length() < 5,
    state' = { ...state, expenses: state.expenses.append({ month: 202403, … }) },
  }
  ```
- `action step = any { <command>, …, noOp }`. Include an always-enabled
  `action noOp = state' = state` so legitimately terminating flows do not
  deadlock (Apalache reports deadlock as a violation).
- Invariants:
  - **State predicate** — `val <name> = …` (e.g. a bound).
  - **Transition property** (append-only history, etc.) —
    `temporal <name> = always((<P(next, cur)>).orKeep(Set(state)))`.
    `orKeep(Set(state))` compiles to `[][P]_state`, the stuttering-insensitive
    form **TLC requires**; plain `always(next(...))` compiles to `[]P` where P
    is an action, which TLC rejects as malformed. Because all state lives in
    `state`, `Set(state)` is homogeneous; `orKeep` cannot take a set of
    differently-typed variables.
  - Make transition properties total: `next(list).slice(0, list.length())` is
    undefined if the next list is shorter. Falsify append-only by **rewriting an
    element in place** (`replaceAt`), not by truncating.
- Reachability: in `reachability.qnt`, `import <model>.* from "./invariants"` and
  declare `val reach<X> = …` witnesses. They are observed with
  `quint run --witnesses` (evidence, not proof; use `quint verify` on the
  negation when a proof is needed). Module `reachability` matches the filename.
- Never use `next()` in an `action`; `next`/`always`/`eventually`/`orKeep` are
  temporal and only valid in a `temporal` definition.

## Process
1. Derive the **observable behaviour** from the Gherkin: commands, navigation,
   reachability, history invariants. Do not model storage or computation.
2. Identify behavioural invariants (e.g. "recording appends to history") and the
   derived values the read side must produce.
3. Declare a `derivation` relation in the lexicon for each derived value, using
   the closed set in `app/lexicon/relations.py`.
4. **Write the Quint models** (`stories/<story-name>/formal/*.qnt`):
   - `invariants.qnt` — the state machine + behavioural invariants.
   - `reachability.qnt` — the claimed reachable states as `val` witnesses.
5. **Declare ownership in the lexicon** under `quint.specs[<path>]` (only when
   the context enables `model_behaviour`):
   - `actions`: every action → `{step: <approved template>}` or `{system: true}`
     (include `init` and `step` as `system`).
   - `invariants`: every invariant → `{term: <term>}`.
   - `witnesses`: the reachability names.
   - `vacuity.corruptions`: domain-meaningful Quint actions that corrupt `state`.
     Add one whenever a new invariant needs a perturbation; mark invariants that
     are true by construction with `vacuity.exemptions` and a reason.
6. **Extend the Alloy domain model** (`architecture/<context>/domain.als`):
   - add the structural entities/relations/fixed mappings the story introduces;
   - add `check … expect 0` invariants and at least one `run … expect 1`
     inhabitation witness;
   - declare ownership in the lexicon under `alloy.specs[<path>]` (`sigs`,
     `checks`, `witnesses`, and MBT `conventions`);
   - keep arithmetic out (the vocabulary gate rejects it).
7. **Run the Quint gate** — mandatory and machine-checked; manual tracing is
   not sufficient. `make lexicon-check-quint` is `scripts/lexicon-check-quint.sh`,
   which discovers `${APP}/stories/*/formal/invariants.qnt` and resolves each
   spec's owning context from the lexicon (so a new model joins the gate without
   editing the script):
   - vocabulary conformance (`quint_check.py`) on `invariants.qnt` and
     `reachability.qnt`;
   - `quint typecheck` both;
   - `quint verify --max-steps <N> --invariants <emitted>` (Apalache safety +
     deadlock);
   - `quint verify --backend tlc --temporal <emitted>` (transition properties);
   - `quint run --witnesses <emitted>` (reachability);
   - `quint_vacuity_check.py` (vacuity);
   - scenario traceability (`make scenario-coverage` =
     `scripts/scenario-coverage.sh`, i.e. `quint_check.py --coverage --trace`):
     every non-`system` action must map to a step template that some scenario
     in the story's `features/` exercises (so the model cannot quietly invent
     behaviour), and every scenario must replay as an enabled model path
     (`quint test`: `init` then its matched actions). Model-internal setup
     actions are exempted under `quint.specs[<path>].coverage.exemptions` and
     scenarios the model cannot yet admit under `.trace.exemptions`, each with
     a reason; stale exemptions fail.
     - **Action bindings** (`actions[<name>].args`, placeholder → regex) select
       the intended action when several share a step template. A term the
       scenario never captures is a wildcard; a value it does capture must
       match. A step whose captured values contradict every candidate is
       reported as *not modelled* (a coverage note), not a trace failure. Give
       each action on a shared template its own `args`; use field-specific terms
       (e.g. `DueDate`, not the generic `Date`) when the generic one would
       otherwise be captured by an unrelated step.
8. **Run the Alloy gate** — `make alloy-check` is `scripts/alloy-check.sh`:
   - the generated catalog is current
     (`render_alloy_catalog.py --check`; regenerate with `make alloy-catalog`);
   - vocabulary/convention conformance (`alloy_check.py`) on the `.als`,
     including that the category catalog matches the conformance oracle and that
     every `check`/`run` declares its `expect`;
   - `alloy exec -t none -f <model>` (the `expect` annotations make the exit
     code the result);
   - vacuity (`alloy_vacuity_check.py`): a temporary copy of the model has the
     lexicon corruptions OR-ed in at the `vacuity-injection-point` marker and
     runs each declared violation; a check that cannot be falsified is vacuous
     and must be fixed or exempted with a reason.
9. Capture the full raw output — including any counterexample state sequences —
   into `formal-report.md`. If any check fails, report the counterexample and
   halt. The Gherkin must be revised and re-approved.
10. **Gate:** `formal-report.md` must be PASS, `make lexicon-check-quint`,
    `make scenario-coverage`, and `make alloy-check` must PASS before
    proceeding to /explain.

## Alloy domain encoding conventions
- One model per bounded context at `architecture/<context>/domain.als`.
- Static structure first: `abstract sig Group`, `abstract sig Category { group:
  one Group }`, fixed `one sig` catalog with appended facts, `abstract sig
  Ownership` with `one sig Household` / `sig Personal { of: one Member }` (totality
  by construction).
- The category catalog lives between `BEGIN/END alloy-catalog` markers and is
  generated by `render_alloy_catalog.py` from the oracle — do not hand-edit it.
- One `one sig State` holds all observable mutable state
  (`var expenses: set ExpenseRow`, `var lastAction: Action`, argument fields).
- Commands are `pred`s that update `State'` and set `lastAction'` plus any
  argument field; combine under `fact behaviour { init and always (… or stutter) }`.
- Invariants are `check Name { … } for <scope> steps expect 0`; inhabitation
  witnesses are `run Name { eventually … } … expect 1`.
- Keep the `// vacuity-injection-point` marker inside `fact behaviour`; the
  vacuity gate needs it to OR in corruption predicates.
- Declare `vacuity.violations` for every non-exempt check and
  `vacuity.corruptions` (a `pred` body setting `State'` to a bad state, with the
  checks it `corrupts`); exempt only checks that restate a global fact or are
  type-level, with a reason.
- Do **not** use `plus`/`minus`/`mul`/`div`/`rem`/`sum`/`int` — arithmetic is
  the lexicon's job. `+`/`-` on sets are allowed.
- Field labels are not unique across sigs; the runner scopes fields to their
  parent sig (do not rely on a bare field name in tooling).

## MBT (when the story warrants it)
- **Quint MBT** — observable view state. `quint-connect` replays generated ITF
  traces against the real app:
  `#[quint_run(spec = "…invariants.qnt", max_samples = N, max_steps = M)]` and
  a `Driver` in `app/tests/mbt_<story>.rs`.
- `init` must **reset** the driver's state (quint-connect reuses one driver
  across every trace).
- `Driver::config` sets `state: &["state"]` when the model groups state in a
  record, so the compared state is the record itself.
- Run with `make mbt-quint` (= `scripts/mbt-quint.sh`), which discovers the
  `stories/*/formal/invariants.qnt` models and runs the registered
  `app/tests/mbt_<story>.rs` driver for each (registration by convention, like
  Alloy MBT).
- **Alloy MBT** — structural domain state. `alloy-connect` replays Alloy XML
  traces against the real store/handlers, comparing the entity/relation
  projection after every step:
  - `app/tests/mbt_<context>.rs` implements `Driver`/`State`; `switch!`
    dispatches on `step.action`; `from_spec` projects the `Instance` and
    `from_driver` projects the SUT into the same shape.
  - `#[alloy_run(spec = "…domain.als", command = "ReachX", repeat = N)]`
    turns a driver factory into a test, the twin of `#[quint_run]`.
  - Read action arguments from the post-state's argument fields (`lastRow`,
    `lastRecurring`, …) — Alloy has no `mbt::nondetPicks`.
  - Keep the projection structural: no balances/totals/derived values (those
    are `lexicon-conformance`). Do not duplicate the Quint view projection.
  - Run with `make mbt-alloy` (= `scripts/mbt-alloy.sh`), which discovers
    `architecture/*/domain.als` and requires a driver named
    `app/tests/mbt_<context>.rs` for each — registration is by convention.

## Gate
- `make lexicon-check-quint` PASS, `make scenario-coverage` PASS (static
  coverage **and** scenario trace replay), `make alloy-check` PASS, and the
  formal report PASS before /explain. Alloy `make mbt-alloy` runs in /bdd.
