# Development Process

## Purpose

This document defines the single, repeatable workflow for translating business narrative into verified, secure, documented software.

Paths in this document are relative to the **app repository root** — the
artifact under construction. The app is a **separate git repository**; its
location is configuration, not an assumption (`PI_APP` for the container,
`APP_REPO` for `make`). It is mounted at `app/` inside the harness container, so
the code, `architecture/`, `lexicon/` and `stories/` all live there. The
harness (`scripts/`, `tools/`, `pipeline/`, `containers/`, this document) is its
own repository outside it and assumes the `app/` mount point. The app's tests
also depend on the separate **alloy-connect** MBT crate, mounted at
`alloy-connect/` (`ALLOY_REPO`).

## Metaphor

- **Gherkin** is the source code (declarative DSL): the acceptance behaviour.
- **The lexicon** (`lexicon/*.yaml`) is the ubiquitous language: the approved step vocabulary, the domain terms, and the pure relations that define derived values. It is *data*, not prose, so it cannot drift from what is checked.
- **Quint** (`stories/<name>/formal/*.qnt`) is the behavioural model: a black-box specification of what the system does at its interface. It must not encode how a value is stored or computed — it is identical whether the value is a stored projection, derived on read, or cached (`architecture/rules.md` rule 6).
- **Alloy** (`architecture/<context>/domain.als`) is the structural domain model: the cross-feature entities, relations, cardinalities and fixed mappings that must hold in every state (category→group partition, ownership/member totality, recurring-only-periodic, append-only version logs, key uniqueness). It specifies *structure*, never behaviour, navigation or arithmetic.
- **I (the agent)** am the transpiler.
- **C4 + UML diagrams** are `EXPLAIN` / `EXPLAIN ANALYZE` — introspection outputs you review without reading implementation details.
- **The conformance harness** verifies pure derivations (lexicon relations) against the read module through a language-neutral `derive` boundary.
- **Mutation testing** proves the test suite is semantically bound to the Gherkin.
- **Property-based testing** verifies that invariants hold across generated inputs.
- **Lightweight formal methods** prove the behavioural specification is consistent before a single line of code is written.
- **The C4 model** (`architecture/`) is the system's living map. Story work *edits* it rather than drawing a new per-story diagram, so inconsistencies surface early. The pre/post class diff is the learning loop.

## Skill Names

| # | Skill | Role |
|---|-------|------|
| 1 | `/story-map` | Narrative + threat narrative |
| 2 | `/gherkin` | Declarative acceptance criteria (the DSL) |
| 3 | `/formalize` | Behavioural model + domain model + lexicon relations; the configured model gates |
| 4 | `/explain` | C4 + UML `EXPLAIN PLAN` / `EXPLAIN ANALYZE` |
| 5 | `/bdd` | Transpile: BDD + the configured verification gates |
| 6 | `/audit` | Security hard gate + formal equivalence check |
| 7 | `/refactor` | Post-impl cleanup per your direction |

Each skill runs the gates its phase has enabled for the context
(`make pipeline-plan CONTEXT=…` to see them); it must not run a gate the context
has disabled, and must not skip a required one.

## The lexicon (cross-cutting)

`lexicon/` owns the ubiquitous language: the term list, the approved step
templates, the table shapes, and the relations for derived values. It is
checked at three gates:

| Gate | Command | Checks |
|---|---|---|
| `/gherkin` | `make lexicon-check` | features speak the approved vocabulary (steps, enum values, table shapes) |
| `/formalize` | `make lexicon-check-quint` | every Quint action maps to a step or is `system`; every invariant is owned by a term and is falsifiable (not vacuous) |
| `/formalize` | `make scenario-coverage` | every non-`system` Quint action is exercised by some scenario in its story's features, and every scenario replays as an enabled model path (`quint test`); template-level, with reasoned exemptions for model-internal actions and not-yet-modelled scenarios |
| `/formalize` | `make alloy-check` | every Alloy sig/field/check/witness maps to a term; the category catalog is rendered from the conformance oracle (`make alloy-catalog`) and current; no `Int` arithmetic; invariants hold and witnesses are reachable (`expect`); every non-exempt check is falsifiable |
| `/formalize` | `make model-discipline` | every `system` declaration and every coverage/trace/vacuity exemption is declared and shaped (a `system` action may not also map to a step; a `system` mapping needs a closed `kind` and a non-empty `reason`); each is reported as residual risk |
| `/bdd` | `make lexicon-conformance` | every declared relation matches the read module across generated inputs |

`make` targets are the **user's** interface. The agent must not invoke `make`
(it is intentionally absent from the agent container); for any gate it reads the
same-named `Makefile` target and runs its underlying commands directly.

A term may own a `derivation` relation. **Derived arithmetic lives in the
lexicon, not in the Quint model** (`architecture/rules.md` rules 5–6,
`architecture/lexicon-conformance.md`).

## The pipeline (per bounded context)

The workflow below is the ideal. Which gates actually run is selected **per
bounded context** by `architecture/<context>/pipeline.yaml`, resolved against
the gate registry (`pipeline/gates.yaml`) and named profiles
(`pipeline/profiles.yaml`). Gate ids are **mechanism-level**, not tool names:
the registry binds a mechanism to the tool that implements it, so a project can
swap tools without renaming a gate.

**Required gates (cannot be disabled):** `vocabulary`, `acceptance` (BDD),
`derived_conformance`, `audit`, `as_built`. Everything else is opt-in:
`model_behaviour`, `model_structure`, `property`, `mbt_behaviour`,
`mbt_structure`, `mutation`.

Selection is **deterministic**: the registry is a closed catalogue; profiles
and context overrides merge with no hidden defaults; required gates are
injected; a context may not disable a required gate; every enabled gate's
`depends` must be enabled; an enabled gate whose `applies` artifact is absent
fails; and unknown gates, fields or params are rejected. Manual gates (audit)
are always listed and are enforced by their skill.

`make` targets:

| Target | Purpose |
|---|---|
| `make pipeline-check` | validate the registry, profiles and every context config |
| `make pipeline-plan CONTEXT=<context>` | print the resolved gate set (phase, kind, cost, source) |
| `make pipeline-run CONTEXT=<context>` | run the enabled automated gates in phase order |
| `make model-discipline` | validate and report every escape hatch / exemption (residual risk) |
| `make attest` | write the verification attestation for the context (`ATTEST=path`) |
| `make attest-check` | fail if the recorded attestation drifted from the spec (`ATTEST=path`) |

Registered gates:

| Gate | Phase | Required | Kind | Depends | Tool |
|---|---|---|---|---|---|
| `vocabulary` | gherkin | yes | auto | — | lexicon checker |
| `model_behaviour` | formalize | no | auto | vocabulary | Quint + lexicon checker |
| `model_structure` | formalize | no | auto | vocabulary | Alloy + lexicon checker |
| `model_discipline` | formalize | no | auto | vocabulary | lexicon escape-hatch checker |
| `acceptance` | bdd | yes | auto | vocabulary | Cucumber |
| `derived_conformance` | bdd | yes | auto | vocabulary | conformance harness |
| `property` | bdd | no | auto | — | property engine |
| `mbt_behaviour` | bdd | no | auto | model_behaviour | quint-connect |
| `mbt_structure` | bdd | no | auto | model_structure | alloy-connect |
| `mutation` | bdd | no | auto | — | mutation engine |
| `audit` | audit | yes | manual | acceptance, derived_conformance | `/audit` skill |
| `as_built` | explain | yes | auto | — | C4 / UML extractor |

## Workflow (Hard Gates)

### 1. `/story-map`
- Define the narrative: actors, value flow, boundaries.
- Explicitly identify the **threat narrative**: sensitive data, trust boundaries, attack surfaces.
- **Output:** `stories/<name>/story-map.md`

### 2. `/gherkin`
- You write the executable specification in `Given / When / Then`.
- This is **the program**. It must include functional *and* security scenarios.
- **Output:** `stories/<name>/features/*.feature`
- **Gate:** You approve the Gherkin, and `make lexicon-check` passes.

### 3. `/formalize` (Hard Gate)
- I derive the **observable behaviour** from the approved Gherkin: commands,
  navigation, reachability, and history invariants. The model is a black-box
  interface spec; it does not say how anything is stored or derived.
- I declare, in the lexicon, the **relations** for every pure derived value
  (balance, projection, month totals, attribution, …). Derived arithmetic is
  not modelled in Quint.
- I write **Quint specifications** (`stories/<name>/formal/*.qnt`) and run
  machine-checked model checking plus the vacuity gate:
  - consistency checks across all scenarios (no contradictions);
  - reachability analysis (all claimed states are reachable);
  - deadlock / livelock detection;
  - vacuity: every invariant must be falsifiable by a state perturbation.
- I extend the **context-level Alloy domain model**
  (`architecture/<context>/domain.als`) with any new structural facts this story
  introduces, and declare the sigs/checks/witnesses in the lexicon. I run the
  structure gate (`make alloy-check`): machine-checked invariants
  (`check … expect 0`), reachable witnesses (`run … expect 1`), vocabulary
  conformance, catalog/oracle agreement, no `Int` arithmetic, and a vacuity
  gate that falsifies every non-exempt check with a lexicon corruption.
- I record every **escape hatch** from the traceability chain — a `system`
  action no step exercises, a scenario exemption, an Alloy system field, a
  vacuity exemption — and run the discipline gate (`make model-discipline`).
  The shape is always enforced (a `system` action may not also map to a step; a
  `system` mapping needs a closed `kind` and a non-empty `reason`; an exemption
  needs a non-empty reason), and each escape hatch is reported as residual risk,
  so a green gate never hides an undeclared skip. A context may raise the bar to
  require a reason on every Quint `system` action and every exemption via the
  gate params `require_reason` / `strict_exemptions`. (Alloy `system`
  declarations are structural placeholders — `State` fields and MBT bookkeeping —
  so they are shape-checked and reported, but a per-field reason would be noise.)
- **Output:** `stories/<name>/formal/*.qnt` (**the** formal spec — there is no
  Markdown transcription), `stories/<name>/formal-report.md` (raw
  Quint/Apalache/TLC output), edits to `architecture/<context>/domain.als`.
- **Gate:** `formal-report.md` PASS, `make lexicon-check-quint` PASS,
  `make scenario-coverage` PASS, `make alloy-check` PASS **and**
  `make model-discipline` PASS, before architecture or code is generated.

### 4. `/explain` — `EXPLAIN PLAN` (Pre-Implementation)
- I update the **living C4 model** (`architecture/c4/context.md`,
  `architecture/c4/container.md`, and `architecture/<context>/{component,state,sequence}.md`),
  informed by the behavioural model. If a new bounded context appears, it is added
  at the context and container levels first.
- I write a transient `stories/<name>/class-plan.yaml`: the classes and relations
  intended for this slice.
- You review the model changes and the class plan.
- Security aspect: trust boundaries, auth flows, sensitive data movement, and **invariant enforcement points** are highlighted.
- **Output:** edits to the living model + `stories/<name>/class-plan.yaml`
- **Gate:** You approve the plan before code generation begins.

### 5. `/bdd`
- I implement strictly against the approved Gherkin, which is **executed for real by a Cucumber runner** (cucumber-rs) — the `.feature` files are the running tests, not a transcription source.
- Outside-in: step definitions + acceptance scenarios first, then driving inward with unit tests.
- **Read models derive on read** (`architecture/rules.md` rule 5). No persisted
  projection is introduced without a measurement that demands it, and never as
  the source of truth.
- **Property-based tests** verify invariants across generated / edge-case inputs.
- **The conformance harness** (`make lexicon-conformance`) verifies each lexicon
  relation against the real read module through the `derive` boundary.
- **Mutation testing** validates that the suite actually asserts Gherkin semantics.
- **Domain MBT** (`make mbt-alloy` = `alloy-connect`) replays Alloy-generated
  structural traces against the real store/handlers and compares the
  entity/relation projection after every step. It is the structural twin of the
  Quint MBT run (`make mbt-quint`): Quint compares observable *view* state, Alloy
  compares *domain structure*, and the lexicon owns arithmetic.
- **Output:** Working code, Cucumber run report (raw runner output), property-based and conformance reports, mutation report, domain MBT run.
- **Gate:** All scenarios green in the Cucumber run + property tests pass + conformance passes + `make mbt-alloy` passes + mutation score meets threshold.

### 6. `/audit` (Hard Gate)
- I audit the transpiled artifact against the threat narrative and security Gherkin scenarios.
- Checks include: dependency review, input validation, authn/authz enforcement, secrets handling, injection resistance, information leakage, over-permissioning, weak crypto.
- **Formal equivalence review:** the read module conforms to the lexicon
  relations (`make lexicon-conformance`), the implementation's observable
  behaviour is consistent with the `.qnt` model (`make mbt-quint`), and the structural
  domain invariants hold against the `.als` model (`make alloy-check` +
  `make mbt-alloy`).
- Re-run **property-based tests** with security-focused generators to probe for invariant violations.
- **Output:** `stories/<name>/audit-report.md`
- **Gate:** Must PASS before refactoring or delivery.

### 7. `/explain` — `EXPLAIN ANALYZE` (As-Built)
- I regenerate the **as-built class model** deterministically from the code
  (`make arch-class`) and diff it against the plan
  (`make arch-class-diff PLAN=stories/<name>/class-plan.yaml`).
- You compare planned vs built. **The gate is your decision**, not "code matches
  plan": record any refactoring directions, then the `class-plan.yaml` is
  **discarded** so it cannot drift or confuse later work.
- I reconcile the living C4 model (`component`/`state`/`sequence`) with what was built.
- Security aspect: as-built trust boundaries and data flows are verified.
- **Output:** regenerated `architecture/<context>/class.md` + the class diff

### 8. `/refactor`
- You direct what to change (e.g., "simplify the adapter layer", "reduce duplication in read models").
- I optimize internals (performance, clarity, patterns) without changing Gherkin semantics.
- The full suite protects against regression: Gherkin scenarios + property tests + conformance + mutation-tested suite + security scenarios.
- Re-run `/audit` checks relevant to the refactored area; verify formal invariants are preserved.
- Update as-built diagrams if the structure changed.

### 9. `/restructure` (Architecture-Scope Refactor)
- You direct a change to the system's *shape*, not its behaviour: splitting one
  bounded context into several, changing the layering (for example layer-first
  to package-by-feature), changing persistence, or re-cutting the adapters. The
  anchor names every context in scope, primary first (e.g.
  `restructure expense_tracking,investments`).
- **The semantic inputs are frozen.** `stories/**` (story maps, `features/`,
  `formal/*.qnt`, reports) and `lexicon/**` must be byte-identical for the whole
  task. The refactor may change `src/`, `tests/`, `architecture/` and the build
  manifests (`Cargo.toml`, `Cargo.lock`) — imports and structure move, but the
  acceptance spec, the behavioural/structural models and the ubiquitous language
  stay put. Keeping the inputs fixed is what makes the green gates a proof of
  *preservation* rather than a licence to change meaning.
- Re-run the affected context's enabled pipeline gates: Gherkin + property +
  conformance/MBT against the frozen inputs, and the as-built extraction against
  the new structure. Update the living C4 model to match.
- **Output:** refactored `src/`/`tests/`, reconciled `architecture/`, and
  `architecture/<context>/restructure-report.md` for each context in scope —
  recording the before/after and the invariant evidence.
- **Gate:** `make restructure-check` PASS (stories + lexicon unchanged) and the
  context's enabled gates PASS.

## Verification attestation

The pipeline selects a verification *depth* per context — the resolved gate
set. A story may stop at any rung of the gradient (Gherkin, the lexicon, the
formal models, the code), but the choice should be a recorded fact, not a
private judgement.

`make attest` computes a content digest over the context's semantic inputs
(the lexicon and its imports, the story features, the formal models, the Alloy
domain model, and the pipeline configuration that selects the gates), records
the resolved gate set and the deepest machine-checked layer, and writes a JSON
attestation into the **app** at `ATTEST` (default
`app/attestations/<context>.json`), so the record travels with the artifact and
can gate the app's CI. The **logic is harness tooling and app-agnostic**; the
app owns the policy and the result. An optional policy file at
`app/architecture/<context>/attestation.yaml` declares `reviewed_through` and
`minimum_from_threat` (CLI flags override it). The trailer form
(`scripts/attest.sh emit --format trailer`) is what a commit can cite:
`Verified-Through`, `Spec-Digest`, `Pipeline`. `make attest-check` recomputes
the attestation and fails if the digest or the gate set drifted, so a later
spec edit that invalidates already-shipped code is detectable. It is the same
discipline `/restructure` applies by freezing the semantic inputs
byte-for-byte.

The human-review depth can be recorded too (`--reviewed-through`) and compared
with the minimum a story's threat narrative demands (`--minimum-from-threat`);
the result is the `review_depth_ok` field. The gauge can be ignored, but it can
no longer be silent.

## Principles

- **No anonymous complexity.** Everything is named and narrated before it exists.
- **Stochastic generation, deterministic verification.** The agent proposes the
  lexicon, the models and the code; the checkers dispose. Because verification is
  deterministic, a failed candidate is regenerated rather than patched, and a
  passing model is a *filter* — a consistent completion, not a proof of fidelity
  to intent. Fidelity to intent stays a human gate at the Gherkin and the
  lexicon.
- **The code is a rebuildable projection.** The implementation is a derived
  artifact; the spec, the models and the lexicon are the source of truth. When
  the code drifts from the anchor, regenerate it under the fixed spec and the
  deterministic checks rather than moving the anchor to match the code.
  Regeneration is safe only because the checks exist, and discoveries are folded
  back into the spec so the anchor's known-knowns grow.
- **Executable artifacts are the source of truth.** The `.qnt` model is the
  behavioural spec, the `.als` model is the structural spec, and the Gherkin is
  the acceptance spec; there is no hand-written transcription to drift. Prose
  and diagrams are derived and pruned aggressively — if it is not executed, it
  is not authoritative.
- **One owner per fact.** Behaviour → `.qnt`; domain structure → `.als`;
  ubiquitous language and derived arithmetic → `lexicon/`; acceptance → Gherkin;
  security → threat narrative + audit.
- **Tests define behavior, not verify implementation.** BDD + mutation testing + property-based testing keeps us honest.
- **Architecture is a verb.** We design (from a proven spec), then build, then reconcile.
- **Security is a hard gate, not a checkbox.** The artifact is not "done" until the security audit passes.
- **Formal methods are not optional.** The behavioural spec is proven consistent before architecture, the structural domain model is proven consistent and inhabited, the lexicon relations are checked against the read module, and the implementation is checked for refinement (behaviour via Quint MBT, structure via Alloy MBT) before delivery.
- **Residual risk is declared, not hidden.** Every escape hatch from the
  traceability chain is reported by `make model-discipline`, and every
  verification run can be attested (`make attest`), so a green gate means
  "checked", not "nothing was skipped".
