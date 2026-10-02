# Skill: /story-map

## Purpose
Define the narrative of a feature or capability: who the actors are, what they do, and the flow of value through the system. Explicitly identify the threat narrative.

## When to Use
- **Entry point — any time.** Starting a new feature, epic, or capability, or a
  new bounded context / significant change to an existing one.
- **Anchor:** `story-map <new-story>`. This is the only stage that may anchor a
  story whose directory does not exist yet.
- No earlier stage is required; this is a legal first entry.

## Inputs
- Business context from the user (problem statement, domain, actors).

## Outputs
- A user story map (narrative flow, actor goals, activities, steps).
- A threat narrative: sensitive data identified, trust boundaries, attack surfaces.
- Saved as a markdown file under `stories/<story-name>/story-map.md`.

## Process
1. Ask clarifying questions if the business context is incomplete.
2. Draft the user story map with actors, goals, activities, and narrative flow.
3. Derive the threat narrative from the story map.
4. Present to the user for approval before proceeding to /gherkin.
