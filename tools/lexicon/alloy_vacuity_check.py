#!/usr/bin/env python3
"""Alloy vacuity gate.

A `check` that holds only because its subject never occurs is vacuous. This
gate falsifies each non-exempt check: it makes a copy of the model, OR-s the
lexicon's corruption predicates into the transition relation at the
`vacuity-injection-point` marker, and appends a `run Vacuity<Check>` for each
declared violation. Each run must be SAT (`expect 1`); an UNSAT run means the
check cannot be falsified — it is vacuous.

Checks that are true by construction (type-level, or a direct restatement of a
global `fact`) cannot be falsified without deleting a fact; they must be listed
under `vacuity.exemptions` with a reason.

The lexicon supplies the Alloy snippets:

    alloy.specs[<path>].vacuity:
      violations:
        <Check>: "<temporal predicate that violates it>"
      corruptions:
        - name: corruptX
          corrupts: [<Check>, ...]
          body: |
            <Alloy predicate body setting State' to a bad state>
      exemptions:
        <Check>: "<why it cannot be falsified>"

Usage:
    alloy_vacuity_check.py --context expense_tracking \
        --spec architecture/expense_tracking/domain.als

Exit codes: 0 non-vacuous, 1 vacuity failures, 2 config/spec error.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml

import app_paths

# Import the sibling gate for the shared lexicon/spec readers.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import alloy_check  # noqa: E402

MARKER = re.compile(r"[ \t]*//\s*vacuity-injection-point[^\n]*")


def die(msg: str) -> None:
    print(f"lexicon-alloy-vacuity: error: {msg}", file=sys.stderr)
    sys.exit(2)


def build_corrupted_model(spec: Path, vacuity: dict, info: dict) -> tuple[str, list[str]]:
    problems: list[str] = []
    src = spec.read_text()

    if not MARKER.search(src):
        die(
            f"{spec} has no `vacuity-injection-point` marker; the model cannot "
            "be corrupted for the vacuity gate"
        )

    corruptions = vacuity.get("corruptions") or []
    violations = vacuity.get("violations") or {}
    exemptions = vacuity.get("exemptions") or {}
    checks = info["checks"]

    for name, reason in exemptions.items():
        if not reason:
            problems.append(f"exemption for {name!r} has no reason")
        if name not in checks:
            problems.append(f"exemption {name!r} does not name a check in the model")

    for name in sorted(checks):
        if name in exemptions:
            continue
        if name not in violations:
            problems.append(
                f"check {name!r} is neither exempt nor given a vacuity violation"
            )

    for name, violation in violations.items():
        if name not in checks:
            problems.append(f"vacuity violation {name!r} does not name a check in the model")
        if not violation.strip():
            problems.append(f"vacuity violation {name!r} is empty")
        if not any(name in (c.get("corrupts") or []) for c in corruptions):
            problems.append(
                f"check {name!r} has a violation but no corruption declares it in `corrupts`"
            )
        if not info["scopes"].get(name):
            problems.append(f"check {name!r} has no `for ... steps` scope to reuse")

    for c in corruptions:
        if not c.get("name"):
            problems.append("corruption without a name")
        if not (c.get("body") or "").strip():
            problems.append(f"corruption {c.get('name')!r} has an empty body")
        for target in c.get("corrupts") or []:
            if target not in checks:
                problems.append(
                    f"corruption {c.get('name')!r} targets unknown check {target!r}"
                )

    if problems:
        return "", problems

    injection = " or ".join(c["name"] for c in corruptions)
    src = MARKER.sub(f"    or {injection}" if injection else "", src, count=1)

    preds = "\n\n".join(
        f"pred {c['name']} {{\n{textwrap.indent(c['body'].strip(), '  ')}\n}}"
        for c in corruptions
    )
    runs = "\n\n".join(
        f"run Vacuity{name} {{\n  {violation.strip()}\n}} {info['scopes'][name]} expect 1"
        for name, violation in violations.items()
    )
    return src + "\n\n" + preds + "\n\n" + runs + "\n", []


def run_alloy(model: Path) -> int:
    jar = Path(
        __import__("os").environ.get(
            "ALLOY_JAR", "/usr/local/lib/alloy/org.alloytools.alloy.dist.jar"
        )
    )
    out = Path(tempfile.mkdtemp(prefix="alloy-vacuity-"))
    try:
        proc = subprocess.run(
            [
                "java",
                "-jar",
                str(jar),
                "exec",
                "-t",
                "none",
                "-o",
                str(out),
                "-f",
                "-c",
                "Vacuity*",
                str(model),
            ],
            capture_output=True,
            text=True,
        )
        output = proc.stdout + proc.stderr
        # Keep the command status lines; drop the aarch64 native-solver noise.
        for line in output.splitlines():
            if "findPlatform unknown" in line or line.startswith("[main] INFO"):
                continue
            print(line)
        return proc.returncode
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()

    lex = alloy_check.load_lexicon(args.lexicon_dir, args.context)
    alloy = lex["alloy"]
    if not alloy:
        die(f"lexicon for {args.context!r} has no `alloy:` mapping section")
    specs = alloy.get("specs") or {}
    key = app_paths.spec_key(args.spec, args.lexicon_dir, specs)
    entry = specs.get(key) if key else None
    if entry is None:
        die(f"lexicon has no alloy.specs entry for {args.spec!r}")

    vacuity = entry.get("vacuity")
    if not vacuity:
        die(f"lexicon alloy entry for {args.spec!r} has no `vacuity:` section")

    info = alloy_check.read_spec(args.spec)
    model_text, problems = build_corrupted_model(args.spec, vacuity, info)

    print(f"spec: {args.spec}")
    exempt = ", ".join(sorted((vacuity.get("exemptions") or {}).keys())) or "<none>"
    falsifiable = ", ".join(sorted((vacuity.get("violations") or {}).keys())) or "<none>"
    print(f"exempt:      {exempt}")
    print(f"falsifiable: {falsifiable}")

    if problems:
        print()
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} Alloy vacuity configuration problem(s).")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="alloy-vacuity-src-"))
    try:
        corrupted = tmp / "corrupted.als"
        corrupted.write_text(model_text)
        print("--- falsification runs (each must be SAT)")
        code = run_alloy(corrupted)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if code != 0:
        print()
        print("FAIL: at least one check could not be falsified (vacuous).")
        return 1

    print(f"\nPASS: every non-exempt {args.context} Alloy check is falsifiable.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except yaml.YAMLError as e:
        die(f"invalid YAML: {e}")