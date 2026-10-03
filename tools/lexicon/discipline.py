#!/usr/bin/env python3
"""Escape-hatch and residual-risk gate.

The formal models cannot describe everything. A Quint model needs `init`,
navigation scaffolding and fixture-seeding actions that no Gherkin step
exercises; a scenario may legitimately not be modelled yet; a structural check
may be true by construction. Each such construct is a declared *escape hatch*
from the traceability chain — and every escape hatch is residual risk, not a
silent pass.

This tool makes that risk explicit and keeps the escape hatches honest:

  * the `system` declaration has a closed shape — either `true` (an
    un-justified escape hatch) or `{kind, reason}` with `kind` from a closed
    set and a non-empty `reason`;
  * a `system` action that also maps to a step is rejected: the two are
    mutually exclusive, and silently ignoring a stepped action is the hole
    this closes;
  * every coverage / trace / vacuity exemption must carry a non-empty reason;
  * the tool emits a manifest of every escape hatch and exemption, so the
    residual risk can be recorded (for example in a commit) instead of
    disappearing behind a green gate.

It reads the lexicon only, never the `.qnt`/`.als` source, so it can run
before the models and cannot be fooled by them. It is a *shape* check: it does
not judge whether an action is really infrastructure, only that the claim is
declared and consistent.

`--require-reason` and `--strict-exemptions` let a context raise the bar from
"declared" to "justified" without changing this tool.

Usage:
    discipline.py --context expense_tracking
    discipline.py --context expense_tracking --require-reason --strict-exemptions
    discipline.py --context expense_tracking --json --out /tmp/risk.json

Exit codes: 0 conform, 1 unjustified/invalid declaration, 2 config error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml


# A closed set of model-internal reasons. An action declared `system` must be
# one of these (or justify itself with a reason the reviewer can read).
SYSTEM_KINDS = ("init", "noop", "fixture")


class ConfigError(Exception):
    pass


def die(msg: str) -> None:
    print(f"lexicon-discipline: error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_doc(lexicon_dir: Path, context: str) -> dict:
    path = lexicon_dir / f"{context}.yaml"
    if not path.exists():
        die(f"no lexicon for context {context!r} at {path}")
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        die(f"invalid YAML in {path}: {exc}")


def check_system(where: str, decl: dict, require_reason: bool) -> tuple[list[str], dict | None]:
    """Validate one `system` declaration; return (problems, risk entry).

    A `system` declaration is either the bare `true` (an escape hatch with no
    stated reason) or a `{kind, reason}` mapping. Anything else is a config
    error. `risk` is None when the declaration is honestly a `term`/`step`.
    """
    problems: list[str] = []
    system = decl.get("system")
    if not system:
        return problems, None

    if decl.get("step"):
        problems.append(f"{where}: declares both `system` and `step` (mutually exclusive)")

    if system is True:
        if require_reason:
            problems.append(f"{where}: `system: true` without a `reason` (require_reason)")
        return problems, {"kind": "unspecified", "reason": None, "justified": False}

    if isinstance(system, dict):
        unknown = set(system) - {"kind", "reason"}
        if unknown:
            problems.append(f"{where}: unknown system field(s) {sorted(unknown)}")
        kind = system.get("kind")
        if kind not in SYSTEM_KINDS:
            problems.append(f"{where}: system kind {kind!r} not in {list(SYSTEM_KINDS)}")
        reason = system.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            problems.append(f"{where}: `system` requires a non-empty `reason`")
        return problems, {
            "kind": kind if kind in SYSTEM_KINDS else "invalid",
            "reason": reason if isinstance(reason, str) else None,
            "justified": True,
        }

    problems.append(f"{where}: `system` must be `true` or a mapping")
    return problems, {"kind": "invalid", "reason": None, "justified": False}


def check_exemption(where: str, value: object) -> tuple[list[str], dict | None]:
    """Validate one exemption value; return (problems, risk entry).

    Accepted forms: a non-empty reason string, or a `{reason, owner?, review?}`
    mapping. A bare `None` is an un-justified (but tolerated) exemption.
    """
    problems: list[str] = []
    if isinstance(value, str):
        if not value.strip():
            problems.append(f"{where}: empty reason")
        return problems, {"reason": value, "owner": None, "justified": bool(value.strip())}
    if isinstance(value, dict):
        unknown = set(value) - {"reason", "owner", "review"}
        if unknown:
            problems.append(f"{where}: unknown exemption field(s) {sorted(unknown)}")
        reason = value.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            problems.append(f"{where}: requires a non-empty `reason`")
        return problems, {
            "reason": reason if isinstance(reason, str) else None,
            "owner": value.get("owner"),
            "review": value.get("review"),
            "justified": isinstance(reason, str) and bool(reason.strip()),
        }
    if value is None:
        return problems, {"reason": None, "owner": None, "justified": False}
    problems.append(f"{where}: exemption must be a reason string or a {{reason, owner}} mapping")
    return problems, {"reason": None, "owner": None, "justified": False}


def strict_exemption_problem(where: str, risk: dict | None, strict: bool) -> list[str]:
    if strict and risk and not risk["justified"]:
        return [f"{where}: no reason declared (strict_exemptions)"]
    return []


def scan_quint_spec(spec_key: str, entry: dict, require_reason: bool, strict_exemptions: bool):
    problems: list[str] = []
    system_actions: list[dict] = []
    coverage_exemptions: list[dict] = []
    trace_exemptions: list[dict] = []

    for name, decl in (entry.get("actions") or {}).items():
        decl = decl or {}
        where = f"quint {spec_key}: action {name!r}"
        if not decl.get("system") and not decl.get("step"):
            problems.append(f"{where}: must declare `step` or `system`")
            continue
        p, risk = check_system(where, decl, require_reason)
        problems += p
        if risk:
            system_actions.append({"name": name, **risk})

    declared = {n for n, d in (entry.get("actions") or {}).items() if (d or {}).get("system")}
    for name, value in ((entry.get("coverage") or {}).get("exemptions") or {}).items():
        where = f"quint {spec_key}: coverage exemption {name!r}"
        if name in declared:
            problems.append(f"{where}: exempts a `system` action (already outside coverage)")
        p, risk = check_exemption(where, value)
        problems += p
        problems += strict_exemption_problem(where, risk, strict_exemptions)
        if risk:
            coverage_exemptions.append({"name": name, **risk})

    raw = (entry.get("trace") or {}).get("exemptions")
    if isinstance(raw, list):
        for name in raw:
            where = f"quint {spec_key}: trace exemption {name!r}"
            if not (isinstance(name, str) and name.strip()):
                problems.append(f"{where}: invalid scenario name")
                continue
            risk = {"reason": None, "justified": False}
            problems += strict_exemption_problem(where, risk, strict_exemptions)
            trace_exemptions.append({"name": name, **risk})
    elif isinstance(raw, dict):
        for name, value in raw.items():
            where = f"quint {spec_key}: trace exemption {name!r}"
            p, risk = check_exemption(where, value)
            problems += p
            problems += strict_exemption_problem(where, risk, strict_exemptions)
            if risk:
                trace_exemptions.append({"name": name, **risk})
    elif raw is not None:
        problems.append(f"quint {spec_key}: trace.exemptions must be a list or a mapping")

    return problems, system_actions, coverage_exemptions, trace_exemptions


def scan_alloy_spec(spec_key: str, entry: dict, require_reason: bool, strict_exemptions: bool):
    problems: list[str] = []
    system_sigs: list[dict] = []
    system_fields: list[dict] = []
    vacuity_exemptions: list[dict] = []

    for name, decl in (entry.get("sigs") or {}).items():
        decl = decl or {}
        where = f"alloy {spec_key}: sig {name!r}"
        if not decl.get("system") and not decl.get("term"):
            problems.append(f"{where}: must declare `term` or `system`")
        p, risk = check_system(where, decl, require_reason)
        problems += p
        if risk:
            system_sigs.append({"name": name, **risk})

    for sig, fields in (entry.get("fields") or {}).items():
        for fname, decl in (fields or {}).items():
            decl = decl or {}
            where = f"alloy {spec_key}: field {sig}.{fname}"
            if not decl.get("system") and not decl.get("term"):
                problems.append(f"{where}: must declare `term` or `system`")
            p, risk = check_system(where, decl, require_reason)
            problems += p
            if risk:
                system_fields.append({"sig": sig, "field": fname, **risk})

    for name, value in ((entry.get("vacuity") or {}).get("exemptions") or {}).items():
        where = f"alloy {spec_key}: vacuity exemption {name!r}"
        p, risk = check_exemption(where, value)
        problems += p
        problems += strict_exemption_problem(where, risk, strict_exemptions)
        if risk:
            vacuity_exemptions.append({"name": name, **risk})

    return problems, system_sigs, system_fields, vacuity_exemptions


def build_manifest(lexicon_dir: Path, context: str, require_reason: bool, strict_exemptions: bool):
    doc = load_doc(lexicon_dir, context)
    quint = doc.get("quint") or {}
    alloy = doc.get("alloy") or {}

    problems: list[str] = []
    quint_manifest: dict = {}
    alloy_manifest: dict = {}

    specs = quint.get("specs") or {}
    if not specs:
        problems.append(f"lexicon {context!r} declares no `quint.specs` entries")
    for spec_key, entry in specs.items():
        entry = entry or {}
        p, system_actions, coverage, trace = scan_quint_spec(
            spec_key, entry, require_reason, strict_exemptions
        )
        problems += p
        if "witnesses" in entry:
            continue
        quint_manifest[spec_key] = {
            "system_actions": system_actions,
            "coverage_exemptions": coverage,
            "trace_exemptions": trace,
        }

    for spec_key, entry in (alloy.get("specs") or {}).items():
        entry = entry or {}
        p, sigs, fields, vacuity = scan_alloy_spec(
            spec_key, entry, require_reason, strict_exemptions
        )
        problems += p
        alloy_manifest[spec_key] = {
            "system_sigs": sigs,
            "system_fields": fields,
            "vacuity_exemptions": vacuity,
        }

    system_actions = [a for spec in quint_manifest.values() for a in spec["system_actions"]]
    coverage = [e for spec in quint_manifest.values() for e in spec["coverage_exemptions"]]
    trace = [e for spec in quint_manifest.values() for e in spec["trace_exemptions"]]
    sigs = [s for spec in alloy_manifest.values() for s in spec["system_sigs"]]
    fields = [f for spec in alloy_manifest.values() for f in spec["system_fields"]]
    vacuity = [e for spec in alloy_manifest.values() for e in spec["vacuity_exemptions"]]

    summary = {
        "system_actions": len(system_actions),
        "unjustified_system_actions": sum(1 for a in system_actions if not a["justified"]),
        "coverage_exemptions": len(coverage),
        "unjustified_coverage_exemptions": sum(1 for e in coverage if not e["justified"]),
        "trace_exemptions": len(trace),
        "unjustified_trace_exemptions": sum(1 for e in trace if not e["justified"]),
        "alloy_system_decls": len(sigs) + len(fields),
        "unjustified_alloy_system_decls": sum(
            1 for d in [*sigs, *fields] if not d["justified"]
        ),
        "vacuity_exemptions": len(vacuity),
        "unjustified_vacuity_exemptions": sum(1 for e in vacuity if not e["justified"]),
    }

    return {
        "version": 1,
        "context": context,
        "quint": quint_manifest,
        "alloy": alloy_manifest,
        "summary": summary,
        "problems": problems,
    }


def render_text(manifest: dict) -> None:
    context = manifest["context"]
    for spec_key, spec in manifest["quint"].items():
        for action in spec["system_actions"]:
            reason = action["reason"] or "<no reason>"
            print(
                f"note: quint {spec_key}: system action {action['name']!r} "
                f"[{action['kind']}] — {reason}"
            )
        for exemption in [*spec["coverage_exemptions"], *spec["trace_exemptions"]]:
            reason = exemption["reason"] or "<no reason>"
            print(f"note: quint {spec_key}: exemption {exemption['name']!r} — {reason}")
    for spec_key, spec in manifest["alloy"].items():
        for decl in [*spec["system_sigs"], *spec["system_fields"]]:
            label = decl.get("field") or decl["name"]
            print(f"note: alloy {spec_key}: system declaration {label!r}")
        for exemption in spec["vacuity_exemptions"]:
            reason = exemption["reason"] or "<no reason>"
            print(f"note: alloy {spec_key}: vacuity exemption {exemption['name']!r} — {reason}")

    s = manifest["summary"]
    print(
        f"note: residual risk in {context}: "
        f"{s['unjustified_system_actions']}/{s['system_actions']} system action(s) un-justified, "
        f"{s['unjustified_coverage_exemptions']}/{s['coverage_exemptions']} coverage exemption(s) un-justified, "
        f"{s['unjustified_trace_exemptions']}/{s['trace_exemptions']} trace exemption(s) un-justified, "
        f"{s['unjustified_alloy_system_decls']}/{s['alloy_system_decls']} alloy system declaration(s) un-justified, "
        f"{s['unjustified_vacuity_exemptions']}/{s['vacuity_exemptions']} vacuity exemption(s) un-justified"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument("--context", help="bounded context (defaults to CONTEXT)")
    parser.add_argument(
        "--require-reason",
        action="store_true",
        help="fail on `system: true` without a declared reason",
    )
    parser.add_argument(
        "--strict-exemptions",
        action="store_true",
        help="fail on an exemption without a declared reason",
    )
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON")
    parser.add_argument("--out", type=Path, help="write the JSON manifest to this path")
    args = parser.parse_args()

    context = (
        args.context
        or os.environ.get("PIPELINE_CONTEXT")
        or os.environ.get("CONTEXT")
    )
    if not context:
        die("no context: pass --context or set CONTEXT/PIPELINE_CONTEXT")

    manifest = build_manifest(
        args.lexicon_dir, context, args.require_reason, args.strict_exemptions
    )

    # JSON is a machine interface: keep stdout pure and report status on stderr.
    stream = sys.stderr if args.json else sys.stdout

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"manifest: {args.out}", file=stream)

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        render_text(manifest)

    if manifest["problems"]:
        print(file=stream)
        for problem in manifest["problems"]:
            print(f"FAIL: {problem}", file=stream)
        print(f"\nFAIL: {len(manifest['problems'])} escape-hatch problem(s).", file=stream)
        return 1

    print(f"\nPASS: {context} escape hatches and exemptions are declared.", file=stream)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        die(str(exc))
    except yaml.YAMLError as exc:
        die(f"invalid YAML: {exc}")
