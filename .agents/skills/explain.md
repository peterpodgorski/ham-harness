# Skill: /explain

## Purpose
Maintain the **living C4 model** of the whole system, and run the pre/post class
diff for a slice. The model is not per-story: story work *edits* the living
model before implementation, so inconsistencies surface early instead of living
in a disjointed per-story diagram.

## When to Use
- **Plan entry:** `explain-plan <story>` — when the story's Gherkin (and the
  enabled formal artifacts) exist and the design must be captured before /bdd.
- **As-built entry:** `explain-as-built <story>` — when code exists and the
  living model must be reconciled with what was built.
- Both are legal entry points. Name the stage explicitly (`explain-plan` or
  `explain-as-built`) so the anchor is unambiguous; the other mode is not a
  precondition.

## Living model layout
| File | View |
|---|---|
| `architecture/c4/context.md` | System context (whole system) |
| `architecture/c4/container.md` | Containers (whole system) |
| `architecture/<context>/component.md` | C4 components for the bounded context |
| `architecture/<context>/state.md` | Behavioural state machine (agrees with `.qnt`) |
| `architecture/<context>/sequence.md` | Key end-to-end flows |
| `architecture/<context>/class.md` | As-built class model (generated) |
| `architecture/<context>/database.md` | As-built database schema, one ER diagram per context (generated) |

## Inputs
- Approved `stories/<story-name>/features/*.feature`.
- The `.qnt` model and `formal-report.md` (from /formalize).
- The current living model, including the as-built class and database views.

## Outputs
- **Plan:** edits to the living model (`architecture/c4/*`, `architecture/<context>/*`)
  and a transient `stories/<story-name>/class-plan.yaml`, including any proposed
  schema changes in its `tables:` section.
- **As-built:** a regenerated `architecture/<context>/class.md`, a regenerated
  `architecture/<context>/database.md`, the class diff, and the schema drift.

## Running gates
`make` is the **user's** interface and is intentionally absent from the agent
container — never invoke it. Each gate is a same-named `Makefile` target: read
that target and run its underlying commands directly. A non-zero exit is a gate
failure.

## Process
### Plan
1. Read the approved Gherkin and the `.qnt` model.
2. Update the living C4 model for the new/changed context, containers,
   components, states, and sequences. If a new bounded context appears, add it at
   the context and container levels **first**.
3. Decide persistence explicitly. Read models derive on read (rules.md rule 5);
   a table is only justified by a measurement that demands it, and never as the
   source of truth. For every proposed table, column, key, and its read/write
   owner, record the intent in the plan's `tables:` section, mirroring the shape
   of `database-asbuilt.json` (`name`, `columns[]` with
   `name`/`type`/`primary_key`/`not_null`/`unique`).
4. Write `stories/<story-name>/class-plan.yaml`: the classes and relations you
   intend to introduce or change, in the shared class-model schema.
5. Present the class model, the proposed schema, and the plan for approval.
   **Gate:** user approves before code.

### As-built
1. Regenerate the class model: the `arch-class` gate.
2. Run the diff: the `arch-class-diff` gate, passing `PLAN=stories/<story-name>/class-plan.yaml` as the target's recipe does.
3. Regenerate the database model: the `arch-db` gate. Diff the built
   `database.md` against the plan's `tables:` section and surface drift: tables
   added, changed, or dropped that the plan did not name. The schema view is the
   database counterpart of the class model.
4. Reconcile the living C4 docs (component/state/sequence) with what was built.
5. Present the delta, the class diff, and the schema drift. **The gate is the
   decision**, not "code matches plan": record refactoring directions, then
   **discard `class-plan.yaml`**. The generated `class.md` and `database.md`
   become the living truth.

## Notes
- Do not create per-story C4 diagrams; a story *changes* the living model.
- The class and database models are the deterministic views: the class model is
  extracted from code by `tools/arch/extract-classes`; the database model is
  extracted from the adapter DDL by `tools/arch/extract_schema.py` and rendered
  by `tools/arch/schema_render.py`. The other views are authored and reviewed.
- The pre/post class diff exists to surface what we learned during
  implementation, not to force the code into the plan; the schema drift plays the
  same role for persistence.
