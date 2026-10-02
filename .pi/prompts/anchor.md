---
description: Anchor this work in PROCESS.md (stage + stories, or a context)
argument-hint: "<stage> [story[,story]... | context[,context]...]"
---
Establish the PROCESS.md anchor for this task.

Arguments: stage = `$1`; stories = `${@:2}`.

- If the stage is missing, **do not** call the tool — ask me for it.
- If the stage is `harness`, call the tool with just the stage (no stories).
- If the stage is `restructure`, call the tool with the stage and the bounded
  context(s) from `${@:2}` (comma/space separated; the first is primary, and a
  split names the existing context plus any new ones), defaulting to
  `expense_tracking`; stories are not required — they are frozen for the whole
  task.
- Otherwise, if no story was given, **do not** call the tool — ask me for at
  least one story.

Otherwise call the `set_process_anchor` tool exactly once with:

- `stage`: `$1`
- `stories`: the story slugs from `${@:2}`, split on commas or spaces (omit for
  `harness` and `restructure`)
- `contexts`: for `restructure`, the bounded context slugs from `${@:2}`, split
  on commas or spaces (the first is primary; defaults to `expense_tracking`)

Name **every** story this task will touch; the first is primary. Use the
`context` argument only if I named a bounded context other than the default
`expense_tracking`.

Then report the anchor the tool resolved (including any
missing-upstream-artifact note) and proceed only within that stage. If the tool
rejects the anchor, show the rejection and ask me to correct the stage or story.

Do not write, edit, or run a mutating command before the tool reports the anchor
established. Valid stages: `story-map`, `gherkin`, `formalize`, `explain-plan`,
`bdd`, `audit`, `explain-as-built`, `refactor`, `restructure`, `harness`.
