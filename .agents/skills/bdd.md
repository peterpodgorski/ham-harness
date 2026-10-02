# Skill: /bdd

## Purpose
Implement the approved Gherkin scenarios using BDD (outside-in), with the `.feature` files **executed for real by a Cucumber runner** (cucumber-rs) — never hand-transcribed into tests. Then run mutation testing to prove the test suite is semantically bound to the Gherkin.

## When to Use
- **Entry point — any time** the story's `features/` exist and code must be
  implemented, changed, or a `bdd`-phase gate re-run.
- **Anchor:** `bdd <story>`.
- Do not require that /explain ran in this session; require only the artifacts
  the enabled gates consume.

## Inputs
- Approved `stories/<story-name>/features/*.feature`.
- The approved living architecture model (`architecture/`).
- `architecture/<context>/pipeline.yaml` — which gates this context runs.

## Which gates to run

Resolve the context's pipeline and run only its **`bdd`-phase** enabled gates:

```sh
python3 tools/pipeline/pipeline.py plan --context <context>
```

`acceptance` and `derived_conformance` are required for every context. Of the
optional ones, run exactly those the plan lists (`property`, `mbt_behaviour`,
`mbt_structure`, `mutation`). Do not run a disabled gate; do not skip an
enabled one. `audit` and `as_built` run in their own phases.

## Outputs
- Working code under `src/` or the bounded context package.
- A Cucumber runner test (e.g., `tests/cucumber.rs`) that loads the story's `.feature` files, plus `#[given]` / `#[when]` / `#[then]` step definitions.
- Property-based tests for invariants.
- Conformance of the lexicon relations against the read module through the
  language-neutral `derive` boundary (the `lexicon-conformance` gate).
- **Domain MBT** (`make mbt-alloy` = `alloy-connect`): Alloy-generated
  structural traces replayed against the real store/handlers, comparing the
  entity/relation projection after every step. This complements Quint MBT
  (`make mbt-quint`, observable view state); the lexicon owns arithmetic.
- A test report including the **raw Cucumber run output** showing every scenario executed and passed.
- A property-based + conformance report showing invariants hold and derived values match the lexicon relations.
- A mutation testing report meeting the project threshold.

## Environment
- `make` is the **user's** interface and is intentionally absent from the agent
  container — never invoke it. Gates are same-named `Makefile` targets: read the
  target and run its underlying commands directly. A non-zero exit is a gate failure.
- `cucumber` (cucumber-rs) must be a dev-dependency of the app crate; step definitions and the runner are plain `#[test]`s executed by `cargo test`.
- If the Cucumber runner is missing or the feature files are not loaded by it, the gate **cannot pass** — hand-written tests that merely "mirror" the scenarios do not count.

## Cucumber setup conventions
1. The runner test (a `[[test]]` with `harness = false`) loads the actual feature directory via `World::run("../stories/<story-name>/features")` — a plain path relative to the **package root** (the test binary's cwd), not the `tests/` directory.
2. Shared scenario state lives in a `#[derive(cucumber::World)]` struct; cucumber gives each scenario a fresh `World`. Step functions are `async fn` taking `&mut World` plus captures; the runner `main` is `#[tokio::main]`.
3. Cucumber-expression notes (verified against cucumber-rs 0.21): patterns with placeholders need `expr = "..."` (a bare string attribute is an exact literal); built-in parameters are `int`, `float`, `word`, `string` (no `decimal`) — `{float}` yields `f64`, and unquoted numbers in Gherkin won't match `{string}`.
4. Resetting form state in a step (e.g. "taps Add Expense") must preserve Background context (members, lists, pinned dates) — reset only the draft fields.
5. **Gate loophole (verified):** cucumber exits 0 when a step is undefined (it counts as *skipped*, not failed). The gate therefore requires the summary lines to read `N scenarios (N passed)` and `N steps (N passed)` with **zero** skipped/failed — anything else is FAIL, and the full runner output must be pasted into the BDD report. (the `test-bdd` gate enforces this.)
3. Step definitions must call the application's real handlers / ports / stores (the same code the production path uses). Steps that re-implement business logic inline, or that assert against mocks standing in for the system under test, are forbidden — the runner must exercise the actual implementation outside-in.
4. If a step's Gherkin phrasing doesn't map cleanly to one step definition, revise the step definitions (or, if the Gherkin itself is the problem, stop and send the story back to /gherkin for re-approval) — do not special-case it in a test.

## Process
1. Set up the Cucumber runner, step definitions, property-based testing, and mutation testing tooling.
2. For the first scenario, write its step definitions and make the Cucumber run pass, driving inward with unit tests (TDD) as needed.
3. Repeat until the Cucumber run reports **every** scenario in the story's feature files as executed and passed — including functional and security scenarios.
4. Run the conformance harness (the `lexicon-conformance` gate): each lexicon relation is checked against the read module across generated inputs. Read models derive on read (`architecture/rules.md` rule 5); do not introduce a persisted projection without a measurement.
5. Run property-based tests; ensure no invariant violations or shrinking failures.
6. Run domain MBT (`make mbt-alloy`, i.e. `scripts/mbt-alloy.sh` →
   `app/tests/mbt_<context>.rs`). Add/extend the driver if the story's
   structural actions are not yet modelled; keep the projection structural —
   no derived values. If the Alloy model needs a new command or invariant, that
   belongs in `/formalize` (edit `architecture/<context>/domain.als` and the
   lexicon `alloy:` section), not in the test.
7. Run mutation testing; ensure mutants are killed.
8. **Gate:** Cucumber run reports all scenarios green (raw runner output pasted into the BDD report) + property-based tests pass + the `lexicon-conformance` gate passes + `make mbt-alloy` passes + mutation score meets threshold.
9. Do not proceed to /audit until this gate passes.
