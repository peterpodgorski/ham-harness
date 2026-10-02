# Process Anchor (read before touching anything)

This repository is built **only** through `PROCESS.md`. A request may enter at
**any** stage of that process; it may not enter without naming a stage and the
story — or stories — it belongs to. The context-scoped stages (`harness`,
`restructure`) name a bounded context instead. The app (`app/`, a separate git
repository mounted at `app/`) is the artifact; the harness is this repository.
That naming is the **anchor**.

## The law

- **No mutation without an anchor.** Before you `write`, `edit`, or run a
  mutating `bash` command, resolve an anchor:
  `(stage, context, stories[], artifact)`.
- **Name every story you will touch.** The first is primary; the rest are
  stories this work also changes. Realising one story often demands a change to
  another — that is still one anchor, not a licence to work unanchored. A write
  under `app/stories/<X>/` is refused while `X` is not in the anchor.
- **Architecture-scope refactors freeze the semantic inputs.** Under
  `restructure`, `app/stories/**` (including `features/` and `formal/*.qnt`) and
  `app/lexicon/**` are invariant; only `src/`, `tests/`, `architecture/` and the
  build manifests (`Cargo.toml`, `Cargo.lock`) may change. The frozen inputs are
  the proof that behaviour was preserved, not changed.
- **Read-only work never needs an anchor.** Use `read`, `grep`, `find`, `ls`, and
  read-only `bash` (`git status`, `git diff`, `rg`, …) to discover the repo and
  the anchor.
- **Refuse unanchored requests.** If the prompt does not name a stage and a
  story, do not touch files. Ask for the anchor, or tell the user to run
  `/anchor`.

A project extension (`process-gate`) enforces this: it blocks unanchored
writes/edits/mutations at the tool boundary. The block is the process, not an
obstacle to route around.

## Stages (any one may be the entry point)

| stage | meaning | characteristic artifact |
|---|---|---|
| `story-map` | narrative + threat narrative | `stories/<story>/story-map.md` |
| `gherkin` | acceptance DSL | `stories/<story>/features/*.feature` |
| `formalize` | Quint + Alloy + lexicon gate | `stories/<story>/formal/invariants.qnt`, `architecture/<context>/domain.als` |
| `explain-plan` | living C4 + class plan | `stories/<story>/class-plan.yaml` |
| `bdd` | implement + verification battery | `stories/<story>/bdd-report.md` |
| `audit` | security / refinement gate | `stories/<story>/audit-report.md` |
| `explain-as-built` | as-built diff + reconcile | `architecture/<context>/class.md` |
| `refactor` | internal change, semantics fixed | `stories/<story>/audit-report.md` |
| `restructure` | architecture-scope refactor (split contexts, layering, persistence); stories + lexicon frozen | `architecture/<context>/restructure-report.md` |
| `harness` | `PROCESS.md`, `scripts/`, `tools/`, `pipeline/`, `containers/` | `PROCESS.md` |

Contexts and enabled gates come from `app/architecture/<context>/pipeline.yaml`
resolved against `pipeline/gates.yaml`; run **only** the enabled gates of the
named context. The context defaults to `expense_tracking` when unstated.

## How to establish an anchor

1. If the request names a stage and story (e.g. "audit view-month"), call the
   `set_process_anchor` tool with them. If the work crosses stories, pass every
   story in `stories`; the first is primary. The tool validates against the repo
   and reports any missing upstream artifacts.
2. If the user says "new story: X", anchor `story-map X` (the story directory may
   not exist yet — `story-map` is the only stage allowed to create it).
3. If the user asks for a harness change, anchor `harness` and proceed. Harness
   edits still require an explicit user request.
4. If the user asks for an architecture-scope refactor (splitting a bounded
   context, changing the layering or persistence), anchor
   `restructure <context>[,<context>...]`. A split names the source context and
   the new ones; story slugs are optional scope notes and remain frozen either
   way.
5. Otherwise ask the user for the stage and story. The user may run `/anchor`.
6. If a story is named but the stage is ambiguous, state the stage you inferred
   and why; if it is still ambiguous, ask before touching files.

The anchor is **per task**. Changing the stage, or touching a story that is not
in the anchor, requires a new anchor (`/process clear`, then set a new one).

### Cross-story work

Realising story A sometimes requires a change to story B. That is one task with
one anchor, not two:

    /anchor gherkin adding-expenses,view-projection

`adding-expenses` is primary; `view-projection` is in scope too. Do not silently
edit B under an anchor that names only A — the gate refuses the write. If a third
story emerges mid-task, re-anchor with the full set before touching it.

## When the request is not anchored

Respond with a refusal of this shape, then wait:

> This isn't anchored in PROCESS.md, so I won't touch the repo. Tell me the stage
> and story (e.g. `/anchor audit view-month`, or `/anchor gherkin a,b` for
> cross-story work), or say "new story: <name>".

Do not "helpfully" make an unanchored change. Do not invent an anchor for a story
or stage the user did not name.

## Stage boundaries

- Never edit `app/stories/<story>/features/*.feature` outside `/gherkin`; they
  are the acceptance source of truth.
- A write under `app/stories/<story>/` requires `<story>` in the anchor. Neither
  the `harness` nor the `restructure` anchor covers story paths, and
  `restructure` locks `app/lexicon/**` as well.
- Gates are `make` targets for the **user**; the agent never invokes `make`. Read
  the target and run its underlying commands, inside the anchored stage.
- `PROCESS.md` is the process; this file only tells you when you are allowed to
  follow it.
