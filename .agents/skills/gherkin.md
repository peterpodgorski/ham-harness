# Skill: /gherkin

## Purpose
Write executable acceptance criteria in Gherkin for a specific story. The Gherkin acts as the declarative source code (DSL) for the transpiler.

## When to Use
- **Entry point — any time** `stories/<story-name>/story-map.md` exists and the
  acceptance DSL must be authored or revised.
- **Anchor:** `gherkin <story>`.
- Normally follows an approved /story-map, but entering here directly is legal;
  do not demand a fresh /story-map unless the story has no `story-map.md`.

## Inputs
- Approved `stories/<story-name>/story-map.md`.
- User may specify which slice or scenario to focus on.

## Outputs
- A `.feature` file under `stories/<story-name>/features/`.
- Scenarios must include both functional and security acceptance criteria (e.g., unauthenticated access denied, input validation enforced).
- The `.feature` file is the single source of truth for the /explain and /bdd steps.
- The feature must speak the approved vocabulary: steps, enum values, and table
  shapes come from `lexicon/<context>.yaml`. The `lexicon-check` gate must pass.

## Running gates
`make` is the **user's** interface and is intentionally absent from the agent
container — never invoke it. Each gate is a same-named `Makefile` target: read
that target and run its underlying commands directly (e.g. `python3
tools/lexicon/check.py …`). A non-zero exit is a gate failure.

## Process
1. Read the approved story map and the context lexicon.
2. Identify the specific scenarios to cover for the current slice.
3. Write `Feature`, `Background`, `Scenario`, `Scenario Outline` with `Given/When/Then`, using only approved lexicon steps, terms, and table shapes.
4. Include explicit security scenarios derived from the threat narrative.
5. Run the `lexicon-check` gate; add missing vocabulary to the lexicon deliberately rather than inventing steps ad hoc.
6. Present the Gherkin to the user for approval.
