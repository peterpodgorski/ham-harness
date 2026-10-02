# Process Gate — the anchor

`PROCESS.md` is the workflow. This document explains the **gate** that makes the
agent use it: no change to the repository happens until the work is *anchored*
in the process.

The gate is deliberately narrow. It does **not** force you to start at the
story map or the Gherkin. It forces every task to name **which stage** it is in
and **which story** it belongs to. Any stage may be the entry point; an
unanchored prompt is refused.

## The rule

> **No mutation without an anchor.** A write, edit, or mutating command requires
> a resolved anchor `(stage, context, stories[], artifact)`. Read-only work never
> does.

"Read-only" means exactly what it says: inspecting files and running read-only
commands (`ls`, `cat`, `rg`, `git status`, `git diff`, …) is always allowed, so
the agent can look around and work out the anchor.

## Repositories

The harness (this repository: `PROCESS.md`, `scripts/`, `tools/`, `pipeline/`,
`containers/`, `.pi/`), the app (`src/`, `tests/`, `architecture/`, `lexicon/`,
`stories/`) and the **alloy-connect** MBT crate are **separate git
repositories**. Inside the container the app is mounted at `app/` and
alloy-connect at `alloy-connect/`, so every path in PROCESS.md and in the gate is
app-relative. `scripts/restructure-check.sh` verifies the app's invariant with
`git -C app`. Their names and locations are configuration: set `PI_APP` /
`APP_REPO` for the app and `ALLOY_REPO` for alloy-connect (there are no
defaults). Both entry points load a gitignored `.env` at the harness root, so the
values can live there.

## The stages

Any one of these is a legal entry point.

| stage | meaning | characteristic artifact |
|---|---|---|
| `story-map` | narrative + threat narrative | `app/stories/<story>/story-map.md` |
| `gherkin` | acceptance DSL | `app/stories/<story>/features/*.feature` |
| `formalize` | Quint + Alloy + lexicon gate | `app/stories/<story>/formal/invariants.qnt`, `app/architecture/<context>/domain.als` |
| `explain-plan` | living C4 + class plan | `app/stories/<story>/class-plan.yaml` |
| `bdd` | implement + verification battery | `app/stories/<story>/bdd-report.md` |
| `audit` | security / refinement gate | `app/stories/<story>/audit-report.md` |
| `explain-as-built` | as-built diff + reconcile | `app/architecture/<context>/class.md` |
| `refactor` | internal change, semantics fixed | `app/stories/<story>/audit-report.md` |
| `restructure` | architecture-scope refactor (split contexts, layering, persistence); stories + lexicon frozen | `app/architecture/<context>/restructure-report.md` |
| `harness` | `PROCESS.md`, `scripts/`, `tools/`, `pipeline/`, `containers/` | `PROCESS.md` |

Which gates actually run inside a stage comes from the context's
`app/architecture/<context>/pipeline.yaml`, resolved against
`pipeline/gates.yaml`. The context defaults to `expense_tracking` when unstated.

## How to use it

Activate once with `/reload` (project trust is already granted for this repo).

- **`/process`** — show the current anchor (or that none is set).
- **`/process clear`** — drop the anchor; mutations are blocked again.
- **`/anchor <stage> <story> [context]`** — establish one, e.g.
  `/anchor audit adding-expenses`, `/anchor harness`, or
  `/anchor restructure expense_tracking[,other]` (context-scoped, no story).
- The agent can also set it by calling the `set_process_anchor` tool when your
  request already names a stage and story.

**Multiple stories are allowed.** The first named is *primary*; the rest are
stories the work also touches:

- `/anchor audit adding-expenses` — one story.
- `/anchor gherkin adding-expenses,view-projection` — cross-story work.
- `/anchor harness` — repository tooling only.
- `/anchor restructure expense_tracking` — an architecture-scope refactor of a
  bounded context; the context defaults to `expense_tracking` when omitted.
- `/anchor restructure expense_tracking,investments` — a refactor that spans
  contexts; the first is primary. A context that does not exist yet is reported
  as a warning and treated as new.

You do not have to start at the beginning:

- `new story: <name>` anchors `story-map` and may create the story directory.
- A failing gate is anchored to the artifact that owns it; the agent enters that
  stage.
- Changing the stage, or touching a story not in the anchor, requires a new
  anchor (`/process clear`, then set it).

### Cross-story work

Realising one story often demands a change to another. That is one task with one
anchor, not two runs: name **both** stories in the same anchor. A write under
`app/stories/<X>/` is refused while `<X>` is not in the anchor, so an undeclared
story cannot be edited by accident. If a further story emerges mid-task,
`/process clear` and re-anchor with the full set before touching it.

## What the gate does

Three layers, from soft to hard:

1. **`AGENTS.md`** (repo root, always loaded) states the law, the stage menu, and
   the refusal wording. This is what makes refusing the default.
2. **`.pi/prompts/anchor.md`** gives you the `/anchor` command.
3. **`.pi/extensions/process-gate.ts`** enforces it at the tool boundary:
   - `set_process_anchor` **validates against the repo** — unknown stages,
     unknown bounded contexts, and unknown stories are rejected, and missing
     upstream artifacts are reported. A new story is only accepted at
     `story-map`. Multiple stories are accepted; the first is primary.
   - `tool_call` blocks unanchored `write`/`edit` and mutating `bash`, fail-safe.
   - A `write`/`edit` under `app/stories/<X>/` is also blocked when `<X>` is not
     in the anchor (and neither `harness` nor `restructure` ever covers story
     paths). Under `restructure`, `app/lexicon/` is frozen as well, and a
     mutating bash command that names a frozen path is blocked.
   - `before_agent_start` puts the current anchor in the system prompt.
   - The anchor is persisted as a session entry, so it survives compaction and
     follows the active branch.

The stage skills (`.agents/skills/*.md`) were rewritten to describe themselves as
entry points rather than a mandatory linear order.

## What is blocked, what is allowed

With no anchor set (verified against this repo):

| command | result |
|---|---|
| `ls -la`, `cat …`, `rg …`, `git status`, `git diff` | allowed |
| `find … 2>/dev/null \| head` | allowed |
| `rm -rf app` | **blocked** |
| `cargo test` | **blocked** |
| `git commit -m x` | **blocked** |
| `echo hi > foo` | **blocked** |
| `write` / `edit` | **blocked** |
| `read` | allowed |

The bash check is deliberately conservative. Commands that are stage work
(`cargo`, `quint`, `python3 tools/…`, `xargs`, `sed`) require an anchor; extend
the read-only allowlist in the extension if that becomes noisy.

## Honest limits

- Prompt-level instructions make refusal *likely*; the extension makes it a wall.
  Neither is a proof against a hostile operator.
- A fabricated anchor must still name a real story and a legal stage, which
  closes the obvious laundering path.
- `/anchor` is model-mediated: it expands to an instruction that tells the agent
  to call the validated tool. If a fully deterministic user path is wanted, an
  extension command that sets the anchor directly can be added (for example
  under the existing `/process` command).

## Files

| File | Role |
|---|---|
| `PROCESS.md` | the workflow itself |
| `AGENTS.md` | always-on anchor protocol read by the agent |
| `.pi/prompts/anchor.md` | the `/anchor` command |
| `.pi/extensions/process-gate.ts` | validation, blocking, prompt injection, persistence |
| `.agents/skills/*.md` | the stage skills, now entry-point oriented |
