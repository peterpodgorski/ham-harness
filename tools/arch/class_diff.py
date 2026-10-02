#!/usr/bin/env python3
"""Deterministic pre/post class diff.

Compares an authored `class-plan.yaml` (intent) with the generated
`class-asbuilt.json` (reality) and prints the delta. The **diff is the
learning**: it is not a compliance gate. The author reviews it, directs any
refactoring, and then discards the plan.

Usage:
    class_diff.py --plan class-plan.yaml --built class-asbuilt.json

Exit codes: 0 always (informational), unless --fail-on-diff is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def load_model(path: Path) -> dict:
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text) or {}
    return json.loads(text)


def class_shape(cls: dict) -> dict:
    return {
        "kind": cls.get("kind", "class"),
        "fields": {f["name"]: f.get("type", "") for f in cls.get("fields", [])},
        "methods": {m["name"]: m.get("signature", m["name"]) for m in cls.get("methods", [])},
        "variants": set(cls.get("variants", [])),
    }


def compare(plan: dict, built: dict) -> list[str]:
    report: list[str] = []
    plan_classes = {c["name"]: class_shape(c) for c in plan.get("classes", [])}
    built_classes = {c["name"]: class_shape(c) for c in built.get("classes", [])}

    planned_only = sorted(set(plan_classes) - set(built_classes))
    built_only = sorted(set(built_classes) - set(plan_classes))
    if planned_only:
        report.append("Planned but NOT built:")
        report += [f"  - {n}" for n in planned_only]
    if built_only:
        report.append("Emergent (built but not planned):")
        report += [f"  + {n}" for n in built_only]

    for name in sorted(set(plan_classes) & set(built_classes)):
        p, b = plan_classes[name], built_classes[name]
        deltas = []
        if p["kind"] != b["kind"]:
            deltas.append(f"kind {p['kind']} -> {b['kind']}")
        for f in sorted(set(p["fields"]) - set(b["fields"])):
            deltas.append(f"field -{f}")
        for f in sorted(set(b["fields"]) - set(p["fields"])):
            deltas.append(f"field +{f}: {b['fields'][f]}")
        for f in sorted(set(p["fields"]) & set(b["fields"])):
            if p["fields"][f] != b["fields"][f]:
                deltas.append(f"field {f}: {p['fields'][f]} -> {b['fields'][f]}")
        for m in sorted(set(p["methods"]) - set(b["methods"])):
            deltas.append(f"method -{m}")
        for m in sorted(set(b["methods"]) - set(p["methods"])):
            deltas.append(f"method +{m}")
        for v in sorted(p["variants"] - b["variants"]):
            deltas.append(f"variant -{v}")
        for v in sorted(b["variants"] - p["variants"]):
            deltas.append(f"variant +{v}")
        if deltas:
            report.append(f"Changed: {name}")
            report += [f"  {d}" for d in deltas]

    p_rel = {(r["from"], r["to"], r["kind"]) for r in plan.get("relations", [])}
    b_rel = {(r["from"], r["to"], r["kind"]) for r in built.get("relations", [])}
    # A planned `dependency` is satisfied by a stronger edge of the same pair:
    # composition (a part) and implementation (an is-a) both imply depends-on.
    b_strong = {(f, t) for (f, t, k) in b_rel if k in ("composition", "implementation")}
    for r in sorted(p_rel - b_rel):
        if r[2] == "dependency" and (r[0], r[1]) in b_strong:
            continue
        report.append(f"Relation planned, not built: {r[0]} --{r[2]}--> {r[1]}")
    for r in sorted(b_rel - p_rel):
        if r[2] in ("composition", "implementation") and (r[0], r[1], "dependency") in p_rel:
            continue
        report.append(f"Relation emergent: {r[0]} --{r[2]}--> {r[1]}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--built", required=True, type=Path)
    parser.add_argument("--fail-on-diff", action="store_true")
    args = parser.parse_args()

    report = compare(load_model(args.plan), load_model(args.built))
    print(f"# Class diff: {args.plan} -> {args.built}\n")
    if not report:
        print("No differences.")
        return 0
    for line in report:
        print(line)
    print("\nReview the delta, direct any refactoring, then discard the plan.")
    return 1 if args.fail_on_diff else 0


if __name__ == "__main__":
    sys.exit(main())
