# Skill: /audit

## Purpose
Security audit of the transpiled artifact against the threat narrative and security Gherkin scenarios. This is a **hard gate** — the artifact is not "done" until this passes.

## When to Use
- **Entry point — any time** the implementation exists and the story's
  acceptance gates pass or their evidence is recorded.
- **Anchor:** `audit <story>`.
- A re-audit after remediation or refactor is a legal entry; /bdd need not be
  re-run first when the relevant evidence already exists.

## Inputs
- The implemented codebase.
- Approved `stories/<story-name>/story-map.md` (threat narrative).
- Approved `stories/<story-name>/features/*.feature` (security scenarios).
- The living architecture model (`architecture/c4/*`, `architecture/<context>/*`).

## Outputs
- `stories/<story-name>/audit-report.md` containing:
  - Dependency review (outdated/vulnerable packages).
  - Input validation findings.
  - Authentication and authorization enforcement review.
  - Secrets handling assessment.
  - Injection resistance (SQL, command, template, etc.).
  - Information leakage review.
  - Permission model review (over-permissioning).
  - Cryptography assessment.
  - Verification that all security Gherkin scenarios are satisfied by the implementation.
  - Formal equivalence review: the read module conforms to the lexicon relations (the `lexicon-conformance` gate), observable behaviour is consistent with the `.qnt` behavioural model (the `mbt-quint` gate), and the domain structure holds against the `.als` model (the `alloy-check` + `mbt-alloy` gates).
  - Property-based test invariant preservation under the actual codebase.
  - Pass / Fail with findings and remediation steps.

## Running gates
`make` is the **user's** interface and is intentionally absent from the agent
container — never invoke it. Each gate is a same-named `Makefile` target: read
that target and run its underlying commands directly. A non-zero exit is a gate
failure.

## Process
1. Run static and dependency security scans as appropriate for the stack.
2. Manually review critical paths against the threat narrative.
3. Verify each security Gherkin scenario is enforced in code, not just in tests.
4. Formal verification of implementation:
   - Verify the read module conforms to the lexicon relations (the `lexicon-conformance` gate).
   - Check that observable behaviour is consistent with the `.qnt` behavioural model (state transitions, guards, security boundaries) and the structural domain with the `.als` model (the `alloy-check` + `mbt-alloy` gates).
   - Re-run property-based tests with security-focused generators to probe for invariant violations.
5. Document findings.
6. If findings exist, present them. Remediate and re-audit until clean.
7. **Gate:** Audit report must be PASS before proceeding.
