#!/usr/bin/env python3
"""Quint <-> lexicon conformance gate.

The formal model is a second projection of the ubiquitous language. This tool
checks that the two projections have not drifted apart:

  * every action declared in the lexicon exists in the spec, and every action in
    the spec is declared and maps to an approved step template or is `system`;
  * every invariant declared in the lexicon exists in the spec, is owned by a
    known term, and every invariant in the spec is declared;
  * every reachability witness in the spec is declared (and vice versa).

It reads the AST directly from `quint parse --out` rather than a stale artifact,
so it always reflects the current `.qnt` source.

Two spec shapes are supported, selected by the lexicon entry:

  * an *invariants* spec (entry has `actions`/`invariants`): top-level
    `qualifier: action` defs are actions; `qualifier: val` and
    `qualifier: temporal` defs are invariants. Helper definitions must be
    `pure def`/`def`, not `val`.
  * a *witnesses* spec (entry has `witnesses`): top-level `qualifier: val` defs
    are reachability witnesses; `def` defs are helpers.

`--emit state|temporal|witnesses` prints the spec's declared names, so the gate
script can drive `quint verify`/`quint run` from the lexicon instead of
hard-coding names and letting them drift.

`--context` is optional: when omitted the owning context is resolved from the
lexicons' `quint.specs` entries, so the gate can discover models without a
hard-coded context. `--print-context` prints that resolution and exits.

`--coverage` joins the model against the story's Gherkin: every non-`system`
action must map to a step template that at least one scenario exercises. It is
per story (derived from the spec path; `coverage.features` overrides) and
operates at template granularity: when several actions share a template they are
reported as a diagnostic, not told apart.

`--trace` replays each scenario as a Quint test (`init` then its matched actions)
and requires the model to admit the path and its state invariants to hold.
An ambiguous step (several actions share one template) expands to the product of
concrete chains, one `run` each, so this checks ordering and guards without
binding concrete data.

Usage:
    quint_check.py --spec stories/view-month/formal/invariants.qnt
    quint_check.py --context expense_tracking --spec ... --emit temporal
    quint_check.py --spec ... --print-context

Exit codes: 0 conform, 1 conformance failures, 2 config/spec error.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import app_paths


class ConfigError(Exception):
    pass


def die(msg: str) -> None:
    print(f"lexicon-quint: error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_lexicon(lexicon_dir: Path, context: str) -> dict:
    terms: dict = {}
    context_path = lexicon_dir / f"{context}.yaml"
    if not context_path.exists():
        die(f"no lexicon for context {context!r} at {context_path}")
    context_doc = yaml.safe_load(context_path.read_text()) or {}
    for imported in context_doc.get("imports") or []:
        doc = yaml.safe_load((lexicon_dir / f"{imported}.yaml").read_text()) or {}
        terms.update(doc.get("terms") or {})
    terms.update(context_doc.get("terms") or {})
    return {
        "terms": terms,
        "step_templates": {s["template"] for s in context_doc.get("steps") or []},
        "quint": context_doc.get("quint") or {},
    }


def lexicon_contexts(lexicon_dir: Path) -> list[str]:
    """Every bounded context declared by a lexicon file."""
    return sorted(
        p.stem for p in lexicon_dir.glob("*.yaml") if not p.name.startswith("_")
    )


def find_context(spec: Path, lexicon_dir: Path) -> str:
    """The bounded context whose lexicon declares `spec` under `quint.specs`.

    Discovery is by ownership: the lexicon is the single source of truth that
    maps a story spec to its bounded context, so a spec that moves between
    contexts follows the lexicon instead of a hard-coded script. A spec may be
    owned by exactly one context.
    """
    matches: list[str] = []
    for context in lexicon_contexts(lexicon_dir):
        doc = yaml.safe_load((lexicon_dir / f"{context}.yaml").read_text()) or {}
        specs = (doc.get("quint") or {}).get("specs") or {}
        if app_paths.spec_key(spec, lexicon_dir, specs):
            matches.append(context)
    if not matches:
        die(f"no lexicon declares {spec!r} under quint.specs")
    if len(matches) > 1:
        die(f"{spec!r} is declared in multiple lexicons: {', '.join(matches)}")
    return matches[0]


def quint_ast(spec: Path) -> dict:
    if not spec.exists():
        die(f"spec not found: {spec}")
    workdir = Path(tempfile.mkdtemp(prefix="lexicon-quint-"))
    try:
        out = workdir / "spec.json"
        proc = subprocess.run(
            ["quint", "parse", str(spec), "--out", str(out)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not out.exists():
            die(f"quint parse failed for {spec}:\n{proc.stdout}\n{proc.stderr}")
        return json.loads(out.read_text())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main_module(ast_doc: dict) -> dict:
    """The module defined by the parsed file.

    `quint parse` lists imported modules first and the module defined in the
    file last, so the last entry is the one under test.
    """
    modules = ast_doc.get("modules") or []
    if not modules:
        die("quint parse produced no modules")
    return modules[-1]


def defs(module: dict) -> dict[str, set[str]]:
    """Group top-level `def` declarations by qualifier."""
    by_qualifier: dict[str, set[str]] = {}
    for decl in module.get("declarations", []):
        if decl.get("kind") != "def":
            continue
        by_qualifier.setdefault(decl.get("qualifier", "def"), set()).add(decl["name"])
    return by_qualifier


def check_invariants_spec(
    entry: dict, lex: dict, quals: dict[str, set[str]]
) -> tuple[list[str], dict[str, list[str]]]:
    problems: list[str] = []
    emitted = {
        "state": sorted(quals.get("val", set())),
        "temporal": sorted(quals.get("temporal", set())),
    }

    spec_actions = quals.get("action", set())
    spec_invariants = quals.get("val", set()) | quals.get("temporal", set())

    declared_actions = entry.get("actions") or {}
    for name in spec_actions:
        if name not in declared_actions:
            problems.append(f"action {name!r} is not declared in lexicon quint.actions")
    for name, spec in declared_actions.items():
        if name not in spec_actions:
            problems.append(
                f"lexicon declares action {name!r} that does not exist in the spec"
            )
            continue
        if spec.get("system"):
            continue
        step = spec.get("step")
        if not step:
            problems.append(f"action {name!r} must declare either `system: true` or `step:`")
        elif step not in lex["step_templates"]:
            problems.append(f"action {name!r} maps to unknown step template: {step!r}")

    declared_invariants = entry.get("invariants") or {}
    for name in spec_invariants:
        if name not in declared_invariants:
            problems.append(f"invariant {name!r} is not declared in lexicon quint.invariants")
    for name, spec in declared_invariants.items():
        if name not in spec_invariants:
            problems.append(
                f"lexicon declares invariant {name!r} that does not exist in the spec"
            )
            continue
        term = spec.get("term")
        if not term:
            problems.append(f"invariant {name!r} is not owned by any term")
        elif term not in lex["terms"]:
            problems.append(f"invariant {name!r} is owned by unknown term {term!r}")

    return problems, emitted


def check_witnesses_spec(
    entry: dict, lex: dict, quals: dict[str, set[str]]
) -> tuple[list[str], dict[str, list[str]]]:
    problems: list[str] = []
    spec_witnesses = quals.get("val", set())
    declared = set(entry.get("witnesses") or [])

    for name in spec_witnesses:
        if name not in declared:
            problems.append(f"witness {name!r} is not declared in lexicon quint.witnesses")
    for name in declared:
        if name not in spec_witnesses:
            problems.append(
                f"lexicon declares witness {name!r} that does not exist in the spec"
            )

    return problems, {"witnesses": sorted(spec_witnesses)}


def resolve_features(
    spec_key: str | None,
    entry: dict,
    lexicon_dir: Path,
    explicit: list[Path] | None,
) -> list[Path]:
    """The feature files a spec's actions must be traceable to.

    Explicit paths win; otherwise the lexicon may override with
    `coverage.features`; otherwise the story's `features/` directory is used.
    """
    if explicit is not None:
        return sorted(set(explicit))
    coverage = entry.get("coverage") or {}
    patterns = coverage.get("features") or []
    app_root = lexicon_dir.resolve().parent
    if patterns:
        found: list[Path] = []
        for pattern in patterns:
            found.extend(app_root.glob(pattern))
        return sorted(set(found))
    if spec_key:
        parts = Path(spec_key).parts
        if len(parts) >= 2 and parts[0] == "stories":
            return sorted((app_root / "stories" / parts[1] / "features").glob("*.feature"))
    return []


def action_candidates(entry: dict) -> dict[str, list[tuple[str, dict]]]:
    """template -> [(action name, declared `args`)] for non-system actions."""
    by_template: dict[str, list[tuple[str, dict]]] = {}
    for name, action in (entry.get("actions") or {}).items():
        if (action or {}).get("system"):
            continue
        template = action.get("step")
        if template:
            by_template.setdefault(template, []).append(
                (name, action.get("args") or {})
            )
    return by_template


def _matches_args(
    args: dict,
    step_captures: dict[str, str],
    capture_index: dict[str, list[str]],
) -> bool:
    for placeholder, pattern in args.items():
        pattern = str(pattern)
        value = step_captures.get(placeholder)
        if value is not None:
            if re.fullmatch(pattern, value) is None:
                return False
            continue
        captured = capture_index.get(placeholder)
        if captured is None:
            # The scenario never mentions this term, so it cannot contradict the
            # action; leave the action in the running and let the others decide.
            continue
        if not any(re.fullmatch(pattern, value) for value in captured):
            return False
    return True


def scenario_captures(scenario) -> dict[str, list[str]]:
    captured: dict[str, list[str]] = {}
    for step in scenario.steps:
        for placeholder, value in step.captures.items():
            captured.setdefault(placeholder, []).append(value)
    return captured


def resolve_step_actions(
    candidates: list[tuple[str, dict]],
    step_captures: dict[str, str],
    capture_index: dict[str, list[str]],
) -> tuple[list[str], bool]:
    """Resolve a step's candidate actions to the intended ones.

    Returns `(names, decisive)`. `decisive` is true when `args` selected the set
    (or the template is unambiguous); false means some candidate declares no
    `args`, so the caller keeps the whole set. A decisive empty set means every
    candidate's declared values were contradicted by a captured term; a term the
    scenario never mentions is treated as a wildcard.
    """
    if len(candidates) == 1 and not candidates[0][1]:
        return [candidates[0][0]], True
    if any(not args for _, args in candidates):
        return [name for name, _ in candidates], False
    matched = [
        name
        for name, args in candidates
        if _matches_args(args, step_captures, capture_index)
    ]
    return matched, True


def check_action_coverage(
    entry: dict, context: str, lexicon_dir: Path, features: list[Path]
) -> tuple[list[str], list[str]]:
    """Every non-`system` action must be exercised by the story's Gherkin.

    Template-level: an action sharing an exercised template is accepted unless it
    is exempted. Declared `args` additionally let the tool report which exercised
    actions no scenario actually binds to; that is a diagnostic, not a gate.
    """
    problems: list[str] = []
    notes: list[str] = []

    non_system = {
        name: spec
        for name, spec in (entry.get("actions") or {}).items()
        if not (spec or {}).get("system")
    }
    exemptions = (entry.get("coverage") or {}).get("exemptions") or {}

    try:
        import check  # local import: only coverage needs the Gherkin parser
    except ImportError as exc:  # pragma: no cover - gherkin is a container dep
        die(f"cannot import the Gherkin checker for --coverage: {exc}")
    try:
        used, gherkin_problems = check.collect_used_templates(
            lexicon_dir, context, features
        )
        scenarios, _ = check.collect_scenarios(lexicon_dir, context, features)
    except check.ConfigError as exc:
        die(str(exc))
    problems.extend(gherkin_problems)

    for name, spec in sorted(non_system.items()):
        template = spec.get("step")
        if template and template not in used and name not in exemptions:
            problems.append(
                f"action {name!r} maps to template {template!r} but no scenario "
                "in the story's features exercises it"
            )

    for name in sorted(exemptions):
        spec = non_system.get(name)
        if spec is None:
            problems.append(
                f"stale coverage exemption for {name!r} (not a non-system action)"
            )
        elif spec.get("step") in used:
            problems.append(
                f"stale coverage exemption for {name!r} (its template is exercised)"
            )

    by_template = action_candidates(entry)
    for template, candidates in sorted(by_template.items()):
        if len(candidates) > 1:
            names = ", ".join(name for name, _ in candidates)
            notes.append(
                f"template shared by {len(candidates)} actions: {template!r} -> {names}"
            )
    unmapped = sorted(t for t in used if t not in by_template)
    if unmapped:
        notes.append(
            f"{len(unmapped)} used template(s) have no model action "
            "(UI/setup/assertions; not a failure)"
        )

    resolved: set[str] = set()
    for scenario in scenarios:
        capture_index = scenario_captures(scenario)
        for step in scenario.steps:
            candidates = by_template.get(step.template)
            if not candidates:
                continue
            names, decisive = resolve_step_actions(
                candidates, step.captures, capture_index
            )
            if decisive and len(names) == 1:
                resolved.add(names[0])
    unbound = sorted(
        name
        for name, spec in non_system.items()
        if spec.get("step") in used and name not in resolved and name not in exemptions
    )
    if unbound:
        notes.append(
            f"{len(unbound)} exercised action(s) have no scenario binding to them "
            f"(declare `args`): {', '.join(unbound)}"
        )

    return problems, notes


def _trace_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower() or "scenario"


MAX_TRACE_PATHS = 256


def check_scenario_traces(
    spec: Path,
    story_module: str,
    val_invariants: list[str],
    scenarios: list,
    entry: dict,
) -> tuple[list[str], list[str]]:
    """Replay each scenario as a Quint test: `init`, then its intended actions.

    Declared `args` resolve a step to one action; where a template still has an
    action without `args`, the step keeps its candidate set and every concrete
    chain is tried. A scenario is admitted iff some chain is enabled and the
    state invariants hold; a step whose declared values match no candidate is a
    hard failure.
    """
    problems: list[str] = []
    notes: list[str] = []

    by_template = action_candidates(entry)
    for candidates in by_template.values():
        candidates.sort(key=lambda pair: pair[0])
    expectation = " and ".join(val_invariants) if val_invariants else "true"

    lines = [
        "// Generated by tools/lexicon/quint_check.py --trace; do not edit.",
        "module scenario_traces {",
        f'  import {story_module}.* from "./invariants"',
        "",
    ]
    scenario_runs: dict[int, tuple] = {}
    unmodelled: list[tuple] = []
    paths = 0
    for index, scenario in enumerate(scenarios, 1):
        capture_index = scenario_captures(scenario)
        chain: list[list[str]] = []
        for step in scenario.steps:
            candidates = by_template.get(step.template)
            if not candidates:
                continue
            names, decisive = resolve_step_actions(
                candidates, step.captures, capture_index
            )
            if decisive and not names:
                # The declared values contradict every candidate: the step is not
                # modelled by this spec, which coverage reports separately.
                unmodelled.append((scenario, step))
                continue
            chain.append(names)
        if not chain:
            continue
        combos = list(itertools.product(*chain))
        if len(combos) > MAX_TRACE_PATHS:
            notes.append(
                f"--trace: skipped {scenario.name!r}: {len(combos)} candidate paths"
            )
            continue
        slug = _trace_slug(scenario.name)
        runs: list[str] = []
        for k, combo in enumerate(combos):
            run_name = f"scenario_{index}_{slug}_c{k}"
            lines.append(f"  run {run_name} = init")
            for action in combo:
                lines.append(f"    .then({action})")
            lines.append(f"    .expect({expectation})")
            lines.append("")
            runs.append(run_name)
        scenario_runs[index] = (scenario, runs)
        paths += len(runs)
    lines.append("}")

    if not scenario_runs:
        if not problems:
            notes.append("--trace: no scenario maps to any action")
        return problems, notes

    work = Path(tempfile.mkdtemp(prefix="quint-trace-"))
    try:
        shutil.copy(spec, work / "invariants.qnt")
        test_file = work / "scenario_traces.qnt"
        test_file.write_text("\n".join(lines) + "\n")
        out_file = work / "result.json"
        proc = subprocess.run(
            [
                "quint",
                "test",
                str(test_file),
                "--match",
                "^scenario_",
                "--out",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            cwd=str(work),
        )
        if not out_file.exists():
            problems.append(
                "scenario trace replay could not run:\n"
                + (proc.stdout + proc.stderr).strip()
            )
            return problems, notes
        result = json.loads(out_file.read_text())
        passed = set(result.get("passed") or [])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    exemptions = (entry.get("trace") or {}).get("exemptions") or {}
    admitted: set[str] = set()
    for scenario, runs in (pair for _, pair in sorted(scenario_runs.items())):
        if any(run in passed for run in runs):
            admitted.add(scenario.name)
        elif scenario.name not in exemptions:
            problems.append(
                f"scenario {scenario.name!r} ({scenario.feature}:{scenario.line}) "
                f"is not admitted by the model: none of its {len(runs)} action "
                "path(s) is enabled"
            )
    known = {scenario.name for scenario, _ in scenario_runs.values()}
    for name in sorted(exemptions):
        if name not in known:
            problems.append(f"stale trace exemption for {name!r} (no such scenario)")
        elif name in admitted:
            problems.append(
                f"stale trace exemption for {name!r} (the scenario is admitted)"
            )

    if unmodelled:
        preview = "; ".join(
            f"{scenario.name!r}:{step.text!r}" for scenario, step in unmodelled[:3]
        )
        notes.append(
            f"--trace: {len(unmodelled)} step(s) are not modelled "
            f"(declared values match no action): {preview}"
        )
    notes.append(
        f"--trace: replayed {len(scenario_runs)} scenario(s), {paths} path(s)"
    )
    return problems, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument(
        "--context",
        help="bounded context; resolved from the lexicon when omitted",
    )
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument(
        "--print-context",
        action="store_true",
        help="print the context that owns --spec and exit",
    )
    parser.add_argument(
        "--emit",
        choices=["state", "temporal", "witnesses"],
        help="print the spec's declared names (space-separated) and exit",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="check every non-system action is exercised by the story's Gherkin",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="replay each scenario as a Quint path (ordering + guards + invariants)",
    )
    parser.add_argument(
        "--features",
        nargs="*",
        type=Path,
        default=None,
        help="feature files for --coverage (default: the story's features/)",
    )
    args = parser.parse_args()

    context = args.context or find_context(args.spec, args.lexicon_dir)
    if args.print_context:
        print(context)
        return 0

    lex = load_lexicon(args.lexicon_dir, context)
    quint = lex["quint"]
    if not quint:
        die(f"lexicon for {context!r} has no `quint:` mapping section")

    specs = quint.get("specs") or {}
    key = app_paths.spec_key(args.spec, args.lexicon_dir, specs)
    entry = specs.get(key) if key else None
    if entry is None:
        die(f"lexicon has no quint.specs entry for {args.spec!r}")

    module = main_module(quint_ast(args.spec))
    quals = defs(module)

    if "witnesses" in entry:
        problems, emitted = check_witnesses_spec(entry, lex, quals)
    else:
        problems, emitted = check_invariants_spec(entry, lex, quals)

    notes: list[str] = []
    if args.coverage and "witnesses" not in entry:
        features = resolve_features(key, entry, args.lexicon_dir, args.features)
        if not features:
            die(
                f"--coverage found no features for {args.spec!r}; "
                "declare coverage.features in the lexicon"
            )
        coverage_problems, notes = check_action_coverage(
            entry, context, args.lexicon_dir, features
        )
        problems.extend(coverage_problems)

    if args.trace and "witnesses" not in entry:
        features = resolve_features(key, entry, args.lexicon_dir, args.features)
        if not features:
            die(
                f"--trace found no features for {args.spec!r}; "
                "declare coverage.features in the lexicon"
            )
        try:
            import check  # local import: only trace replay needs the Gherkin parser
        except ImportError as exc:  # pragma: no cover - gherkin is a container dep
            die(f"cannot import the Gherkin checker for --trace: {exc}")
        scenarios, gherkin_problems = check.collect_scenarios(
            args.lexicon_dir, context, features
        )
        problems.extend(gherkin_problems)
        trace_problems, trace_notes = check_scenario_traces(
            args.spec,
            module["name"],
            sorted(quals.get("val", set())),
            scenarios,
            entry,
        )
        problems.extend(trace_problems)
        notes.extend(trace_notes)

    if args.emit:
        print(" ".join(emitted[args.emit]))
        return 0

    print(f"spec: {args.spec}")
    print(
        "actions: "
        + ", ".join(sorted(quals.get("action", set())))
    )
    print(
        "invariants: "
        + ", ".join(sorted(quals.get("val", set()) | quals.get("temporal", set())))
    )

    for note in notes:
        print(f"note: {note}")

    if problems:
        print()
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} Quint<->lexicon conformance problem(s).")
        return 1

    print(f"\nPASS: {context} Quint model conforms to the lexicon.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as e:
        die(str(e))
    except yaml.YAMLError as e:
        die(f"invalid YAML: {e}")
