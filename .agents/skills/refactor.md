# Skill: /refactor

## Purpose
Optimize the implementation's internals — performance, clarity, patterns — without changing Gherkin semantics. Done after the post-impl /explain is reviewed and the user directs what to change.

## When to Use
- **Entry point — any time** code exists and the user directs an internal change
  that must preserve Gherkin semantics.
- **Anchor:** `refactor <story>`.
- For a change to the system's *shape* — splitting bounded contexts, changing
  layering or persistence — use `/restructure` instead: the same
  semantics-preserving intent at architecture scope, with `stories/` and
  `lexicon/` frozen.
- /explain (as-built) and /audit inform the direction but are not preconditions;
  re-run the checks relevant to the refactored area.

## Inputs
- The current codebase.
- Approved `stories/<story-name>/features/*.feature` (must remain unchanged).
- User direction on what to refactor (e.g., "simplify the adapter layer", "reduce duplication in read models").
- The living architecture model (`architecture/`).

## Outputs
- Refactored codebase.
- Updated living architecture model if structural changes occur.
- Updated test, property-based test, and mutation reports confirming no regression.
- Updated conformance/formal verification confirming behavioural equivalence (the `lexicon-conformance` gate).

## Running gates
`make` is the **user's** interface and is intentionally absent from the agent
container — never invoke it. Each gate is a same-named `Makefile` target: read
that target and run its underlying commands directly. A non-zero exit is a gate
failure.

## Process
1. Review the user's refactoring direction and the as-built diagrams.
2. Identify targets: naming, duplication, complexity, performance, patterns.
3. Refactor with the full test suite running continuously.
4. Re-run all Gherkin scenarios — must remain green.
5. Re-run property-based tests — invariants must still hold; no new shrinking failures.
6. Re-run the conformance harness (the `lexicon-conformance` gate) — lexicon relations must still match the read module.
7. Re-run mutation testing — score must not drop.
8. Re-run /audit checks relevant to the refactored area; verify formal invariants and lexicon-relation conformance are preserved.
9. Update the living architecture model if the structure changed.
10. Present the delta to the user.
