#!/usr/bin/env python3
"""Lexicon -> derivation conformance harness.

Verifies pure derivations against the lexicon relations that specify them. The
implementation is a black box behind a language-neutral `derive` boundary:
this harness generates inputs, calls the command with JSON on stdin, and
compares stdout against the relation evaluated over the same input.

See architecture/lexicon-conformance.md.

Usage:
    derive_check.py --context expense_tracking \
        --derive-cmd /path/to/derive --runs 100

Exit codes: 0 conform, 1 mismatch(es), 2 configuration error.
"""
from __future__ import annotations

import argparse
import json
import random
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from relations_loader import load_relations


def die(msg: str) -> None:
    print(f"lexicon-conformance: error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_terms(lexicon_dir: Path, context: str) -> dict:
    context_path = lexicon_dir / f"{context}.yaml"
    if not context_path.exists():
        die(f"no lexicon for context {context!r} at {context_path}")
    doc = yaml.safe_load(context_path.read_text()) or {}
    terms: dict = {}
    for imported in doc.get("imports") or []:
        imported_doc = yaml.safe_load((lexicon_dir / f"{imported}.yaml").read_text()) or {}
        terms.update(imported_doc.get("terms") or {})
    terms.update(doc.get("terms") or {})
    return terms


def call_derive(cmd: list[str], data: dict) -> int:
    proc = subprocess.run(cmd, input=json.dumps(data), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"derive command exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return int(json.loads(proc.stdout)["amount_minor"])
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"invalid derive output {proc.stdout!r}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--derive-cmd", required=True, help="the derive command (path to the app's derive binary)")
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    relations = load_relations(args.lexicon_dir)
    try:
        relations_for = relations.relations_for_lexicon(load_terms(args.lexicon_dir, args.context))
    except relations.RelationError as e:
        die(str(e))
    if not relations_for:
        print("no derivations declared in lexicon")
        return 0

    cmd = shlex.split(args.derive_cmd)
    failures = 0
    for name, relation in relations_for.items():
        rng = random.Random(f"{args.seed}:{name}")
        mismatches: list[tuple[int, dict, int, int]] = []
        error: str | None = None
        for i in range(args.runs):
            data = relation.generate(rng)
            expected = relation.evaluate(data)
            try:
                actual = call_derive(cmd, data)
            except RuntimeError as e:
                error = str(e)
                break
            if actual != expected and len(mismatches) < 3:
                mismatches.append((i, data, expected, actual))
        if error:
            print(f"FAIL: {name}: {error}")
            failures += 1
            continue
        if mismatches:
            print(f"FAIL: {name}: {len(mismatches)} mismatch(es) in {args.runs} run(s)")
            for i, data, expected, actual in mismatches:
                print(f"  #{i}: expected {expected}, got {actual}")
                print(f"      input: {json.dumps(data, sort_keys=True)}")
            failures += 1
        else:
            print(f"PASS: {name}: {args.runs} generated input(s) conform")

    if failures:
        print(f"\nFAIL: {failures} relation(s) failed conformance.")
        return 1
    print(f"\nPASS: {args.context}: all {len(relations_for)} relation(s) conform.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except yaml.YAMLError as e:
        die(f"invalid YAML: {e}")
