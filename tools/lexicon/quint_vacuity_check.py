#!/usr/bin/env python3
"""Quint vacuity gate — detect invariants that no declared perturbation can falsify.

An invariant that survives arbitrary corruption of the financial state is a
tautology over the model: it cannot catch an implementation regression. This
tool generates a copy of the model with a one-shot fault action built from the
perturbations the lexicon declares under `quint.vacuity.corruptions`, then asks
the model checker to falsify each invariant:

  * a state invariant (`val`) is checked with Apalache;
  * a transition property (`temporal`) is checked with TLC.

If a counterexample is found, the invariant is sensitive. If none of the
declared perturbations can falsify it, it is vacuous and must be explicitly
exempted in the lexicon, with a reason. Stale exemptions fail.

The perturbations live in the lexicon because "what counts as a meaningful
corruption of this domain" is ubiquitous-language material, not tooling.

Usage:
    quint_vacuity_check.py --context expense_tracking --spec <path.qnt>
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import app_paths

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quint_check import (  # noqa: E402
    ConfigError,
    defs,
    find_context,
    load_lexicon,
    main_module,
    quint_ast,
)


# Injected into a copy of the model. `__vacuityFault` corrupts `state` exactly
# once (guarded by `__vacuityFaulted`), then stutters, so the state space stays
# finite for TLC.
INJECT = """
  // --- injected by quint_vacuity_check.py ---
  var __vacuityFaulted: bool

  action __vacuityInit = all {{
    init,
    __vacuityFaulted' = false,
  }}

  action __vacuityFault = any {{
{corruptions}    all {{ __vacuityFaulted, state' = state, __vacuityFaulted' = true }},
  }}
"""


def inject(source: str, corruptions: list[str]) -> str:
    body = source.rstrip()
    if not body.endswith("}"):
        raise ConfigError("cannot find the module's closing brace")
    idx = body.rfind("}")
    branches = "".join(
        "    all {\n"
        "      not(__vacuityFaulted),\n"
        f"      {c},\n"
        "      __vacuityFaulted' = true,\n"
        "    },\n"
        for c in corruptions
    )
    return body[:idx] + INJECT.format(corruptions=branches) + body[idx:] + "\n"


def falsifiable(
    source: str, name: str, temporal: bool, corruptions: list[str], module: str
) -> bool:
    """True if some declared corruption can falsify `name`; raises on tool error."""
    work = Path(tempfile.mkdtemp(prefix="quint-vacuity-"))
    try:
        variant = work / "vacuity.qnt"
        variant.write_text(inject(source, corruptions))
        cmd = [
            "quint", "verify", str(variant),
            "--main", module,
            "--init", "__vacuityInit",
            "--step", "__vacuityFault",
        ]
        if temporal:
            cmd += ["--backend", "tlc", "--temporal", name]
        else:
            cmd += ["--invariant", name, "--max-steps", "3"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        violated = proc.returncode != 0 and "[violation]" in out
        if proc.returncode != 0 and not violated:
            raise ConfigError(
                f"quint verify failed while testing {name!r}:\n{out[-1500:]}"
            )
        return violated
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument(
        "--context",
        help="bounded context; resolved from the lexicon when omitted",
    )
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()

    context = args.context or find_context(args.spec, args.lexicon_dir)
    lex = load_lexicon(args.lexicon_dir, context)
    quint = lex["quint"]
    if not quint:
        print(f"lexicon-vacuity: error: no `quint:` section for {context!r}", file=sys.stderr)
        return 2
    specs = quint.get("specs") or {}
    key = app_paths.spec_key(args.spec, args.lexicon_dir, specs)
    entry = specs.get(key) if key else None
    if entry is None:
        print(f"lexicon-vacuity: error: no quint.specs entry for {args.spec!r}", file=sys.stderr)
        return 2
    vacuity = entry.get("vacuity") or {}
    corruptions = vacuity.get("corruptions") or []
    if not corruptions:
        print(
            f"lexicon-vacuity: error: {args.spec} has no quint.vacuity.corruptions",
            file=sys.stderr,
        )
        return 2

    module = main_module(quint_ast(args.spec))
    quals = defs(module)
    state_invs = sorted(quals.get("val", set()))
    temporal_invs = sorted(quals.get("temporal", set()))
    source = args.spec.read_text()

    sensitive: list[str] = []
    vacuous: list[str] = []
    for name in state_invs + temporal_invs:
        temporal = name in temporal_invs
        try:
            found = falsifiable(source, name, temporal, corruptions, module["name"])
        except ConfigError as e:
            print(f"lexicon-vacuity: error: {e}", file=sys.stderr)
            return 2
        if found:
            sensitive.append(name)
            print(f"  sensitive  {name}")
        else:
            vacuous.append(name)
            print(f"  VACUOUS    {name} (no declared corruption falsifies it)")

    exemptions = vacuity.get("exemptions") or {}
    reason = exemptions.get("reason")
    exempt_names = set(exemptions.get("invariants") or [])

    problems: list[str] = []
    if vacuous and not reason:
        problems.append("lexicon has vacuous invariants but no quint.vacuity.exemptions.reason")
    for name in vacuous:
        if name not in exempt_names:
            problems.append(
                f"invariant {name!r} is vacuous (no declared corruption falsifies it); "
                "add a corruption or exempt it with a reason"
            )
    for name in sorted(exempt_names - set(vacuous)):
        problems.append(f"stale vacuity exemption for {name!r} (it is no longer vacuous)")

    if problems:
        print()
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} vacuity problem(s).")
        return 1

    print(f"\nPASS: {len(sensitive)} sensitive, {len(vacuous)} vacuous (all exempted).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except yaml.YAMLError as e:
        print(f"lexicon-vacuity: error: invalid YAML: {e}", file=sys.stderr)
        sys.exit(2)
