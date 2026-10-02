# Skill: /restructure

## Purpose
Change the system's **shape** — how bounded contexts are cut, how the code is
layered, how persistence is arranged — without changing what the system *means*.
This is the architecture-scope sibling of `/refactor`: broader than optimizing
one feature's internals, narrower than `/harness` (which changes the process,
not the app).

## When to Use
- **Entry point — any time** code and architecture exist and the user directs a
  structural change: split one bounded context into several, move from
  layer-first to package-by-feature, change persistence, re-cut adapters.
- **Anchor:** `restructure <context>[,<context>...]` (context-scoped; the first
  context is primary, and the rest are contexts this refactor also re-cuts). A
  new context named before it exists is reported as a warning, not rejected —
  creating it is part of the work. Story slugs may be named as scope notes only.

## The invariant (the whole point)
The **semantic inputs are frozen** for the entire task:

- `stories/**` — story maps, `features/*.feature`, `formal/*.qnt`, reports;
- `lexicon/**` — the ubiquitous language, step vocabulary and derived relations.

They must be **byte-identical** to `HEAD`. The refactor may change:

- `src/**` — the implementation;
- `tests/**` — tests and step drivers necessarily move as imports change;
- `architecture/**` — the living C4/domain model, re-cut to the new shape.

Because the inputs are fixed, the green gates prove the refactor **preserved**
behaviour rather than redefined it. If a story or lexicon relation genuinely must
change, stop and re-anchor to that story's own stage (`/gherkin`, `/formalize`,
…); it is no longer a restructure.

## Inputs
- The current codebase and the living architecture model (`architecture/`).
- The frozen acceptance and formal specs (read-only here).
- User direction on the target shape.

## Outputs
- Refactored `src/`, `tests/`, and reconciled `architecture/`.
- `architecture/<context>/restructure-report.md` — before/after and the evidence
  (one per context in scope).
- Re-run gate reports (BDD, property, conformance/MBT, as-built).

## Running gates
`make` is the **user's** interface and is intentionally absent from the agent
container — never invoke it. Each gate is a same-named `Makefile` target: read
that target and run its underlying commands directly. A non-zero exit is a gate
failure.

## Process
1. Confirm the target shape with the user and record it.
2. Move `src/` and `tests/` to the new structure; keep behaviour identical.
3. Run `scripts/restructure-check.sh` (target: `make restructure-check`) — it must
   PASS, proving `stories/` and `lexicon/` are unchanged.
4. Re-run the context's enabled pipeline gates against the frozen inputs (BDD,
   property, conformance, and the model/MBT gates the context enables). They must
   stay green.
5. Regenerate the as-built class/database model (`scripts/arch-class.sh`,
   `scripts/arch-db.sh`) and reconcile the living C4 model.
6. Write `architecture/<context>/restructure-report.md`: the target shape, the
   files moved, the gate results, and the `restructure-check` output.
7. Present the delta to the user.

## Hard boundary
A write under `app/stories/**` or `app/lexicon/**` is **refused** while the
anchor is `restructure`. Do not work around the block; re-anchor if the inputs
must change.
