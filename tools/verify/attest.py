#!/usr/bin/env python3
"""Verification attestation: bind the code to the spec it was checked against.

The verification gradient lets an engineer stop at the layer that matches the
risk — Gherkin, the lexicon, the formal models, or the code — instead of
choosing between "trust the generation" and "read everything". Whatever depth
is chosen, the *fact* of it should outlive the session: which spec, which
gates, reviewed how deep. This tool records that.

The **logic** is harness tooling and app-agnostic: it takes a bounded context
and reads the app mount, with no app-specific assumptions. The **configuration
and the result** belong to the app:

  * policy (the human-review depth and the threat-narrative minimum) lives at
    `app/architecture/<context>/attestation.yaml` — optional, overridden by the
    CLI;
  * the attestation itself is written where `--out` (or the policy's `out`)
    points, by convention `app/attestations/<context>.json`, so it travels with
    the artifact and can gate the app's CI.

`emit`:

  * hashes the context's semantic inputs — the lexicon and its imports, the
    story features, the formal models, the Alloy domain model, and the pipeline
    configuration that selects the gates — into one content digest;
  * records the resolved gate set and the deepest phase that actually ran;
  * optionally records the depth a human reviewed (`reviewed_through`) and the
    minimum the story's threat narrative demands (`minimum_from_threat`), so
    the gauge is a measurement rather than a private judgement.

`check` recomputes the attestation and fails if the digest or the gate set has
drifted, so a later spec edit that invalidates already-shipped code is
detectable rather than invisible. It is the same discipline `restructure-check`
applies by freezing the semantic inputs byte-for-byte.

Usage:
    attest.py emit  --context expense_tracking
    attest.py emit  --context expense_tracking --format trailer
    attest.py emit  --context expense_tracking --out app/attestations/expense_tracking.json
    attest.py check --context expense_tracking --attestation app/attestations/expense_tracking.json

Exit codes: 0 ok, 1 drift / missing attestation, 2 configuration error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
LEXICON_DIR = APP_DIR / "lexicon"
PIPELINE_DIR = ROOT / "tools" / "pipeline"

# The human-review gradient, shallowest first. A story may stop at any layer;
# the deeper the layer, the more of the chain a person actually read.
REVIEW_LAYERS = ["gherkin", "lexicon", "models", "code"]

# App-resident attestation policy (optional):
#   app/architecture/<context>/attestation.yaml
# Keys: reviewed_through, minimum_from_threat, out (relative to the app root).
POLICY_FILE = "attestation.yaml"
POLICY_FIELDS = {"reviewed_through", "minimum_from_threat", "out"}

# The verified depth is read off the pipeline: a phase that ran means its
# artifacts were machine-checked. `explain` (as-built extraction) and the
# manual `audit` gate are not semantic verification, so they do not set it.
VERIFY_PHASES = ["gherkin", "formalize", "bdd"]
PHASE_LAYER = {
    "gherkin": "gherkin",
    "formalize": "models",
    "bdd": "code",
}


class ConfigError(Exception):
    pass


def die(msg: str) -> None:
    print(f"attest: error: {msg}", file=sys.stderr)
    sys.exit(2)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def lexicon_files(context: str) -> list[Path]:
    """The context lexicon and its transitive imports."""
    context_path = LEXICON_DIR / f"{context}.yaml"
    if not context_path.exists():
        die(f"no lexicon for context {context!r} at {context_path}")
    seen: list[Path] = []
    queue = [context_path]
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.append(path)
        for imported in load_yaml(path).get("imports") or []:
            queue.append(LEXICON_DIR / f"{imported}.yaml")
    return seen


def policy_path(context: str) -> Path:
    return APP_DIR / "architecture" / context / POLICY_FILE


def load_policy(context: str) -> dict:
    """The app-resident attestation policy, if the context declares one."""
    path = policy_path(context)
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    unknown = set(doc) - POLICY_FIELDS
    if unknown:
        die(f"{rel(path)}: unknown field(s) {sorted(unknown)}; allowed {sorted(POLICY_FIELDS)}")
    for key in ("reviewed_through", "minimum_from_threat"):
        value = doc.get(key)
        if value is not None and value not in REVIEW_LAYERS:
            die(f"{rel(path)}: {key} {value!r} not in {REVIEW_LAYERS}")
    return doc


def resolve_policy(context: str, reviewed: str | None, minimum: str | None, out: Path | None):
    """Overlay CLI arguments on the app policy; CLI wins."""
    policy = load_policy(context)
    reviewed = reviewed or policy.get("reviewed_through")
    minimum = minimum or policy.get("minimum_from_threat")
    if out is None and policy.get("out"):
        out = APP_DIR / str(policy["out"])
    return policy, reviewed, minimum, out


def story_inputs(context: str) -> list[Path]:
    """Feature and formal files for the stories this context's lexicon owns."""
    doc = load_yaml(LEXICON_DIR / f"{context}.yaml")
    stories: set[str] = set()
    for spec_key in ((doc.get("quint") or {}).get("specs") or {}):
        parts = Path(spec_key).parts
        if len(parts) >= 2 and parts[0] == "stories":
            stories.add(parts[1])

    paths: list[Path] = []
    for story in sorted(stories):
        story_dir = APP_DIR / "stories" / story
        paths.extend(sorted((story_dir / "features").glob("*.feature")))
        paths.extend(sorted((story_dir / "formal").glob("*.qnt")))
    return paths


def alloy_inputs(context: str) -> list[Path]:
    doc = load_yaml(LEXICON_DIR / f"{context}.yaml")
    paths: list[Path] = []
    for spec_key in ((doc.get("alloy") or {}).get("specs") or {}):
        paths.append(APP_DIR / spec_key)
    return paths


def config_inputs(context: str) -> list[Path]:
    return [
        ROOT / "pipeline" / "gates.yaml",
        ROOT / "pipeline" / "profiles.yaml",
        APP_DIR / "architecture" / context / "pipeline.yaml",
    ]


def gather_inputs(context: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in [
        *lexicon_files(context),
        *story_inputs(context),
        *alloy_inputs(context),
        *config_inputs(context),
    ]:
        digest = sha256(path)
        if digest is None:
            continue
        hashes[rel(path)] = digest
    if not hashes:
        die(f"no semantic inputs found for context {context!r}")
    return hashes


def digest_of(hashes: dict[str, str]) -> str:
    canonical = "".join(f"{path}\n{sha}\n" for path, sha in sorted(hashes.items()))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def resolve_gates(context: str):
    sys.path.insert(0, str(PIPELINE_DIR))
    import pipeline  # noqa: E402  (path inserted above)

    registry = pipeline.load_yaml(pipeline.REGISTRY_PATH)
    profiles = pipeline.load_yaml(pipeline.PROFILES_PATH)
    resolved, problems = pipeline.resolve(context, registry, profiles)
    plan = pipeline.ordered_enabled(registry, resolved)
    sources = {gate: info["source"] for gate, info in resolved["gates"].items()}
    return registry, plan, sources, problems


def deepest_phase(registry: dict, plan: list[tuple]) -> str | None:
    deepest = None
    for phase in VERIFY_PHASES:
        if any(entry[2] == phase and entry[1].get("kind", "automated") == "automated" for entry in plan):
            deepest = phase
    return deepest


def layer_rank(layer: str) -> int:
    try:
        return REVIEW_LAYERS.index(layer)
    except ValueError:
        die(f"unknown review layer {layer!r}; expected one of {REVIEW_LAYERS}")


def build(context: str, reviewed: str | None, minimum: str | None) -> dict:
    hashes = gather_inputs(context)
    registry, plan, sources, problems = resolve_gates(context)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        die(f"cannot resolve pipeline for {context!r}")

    gates = [
        {
            "name": gate,
            "phase": phase,
            "kind": spec.get("kind", "automated"),
            "source": sources.get(gate),
        }
        for gate, spec, phase in plan
    ]

    deepest = deepest_phase(registry, plan)
    att: dict = {
        "version": 1,
        "context": context,
        "generated_by": "tools/verify/attest.py",
        "verified_through": deepest,
        "verified_layer": PHASE_LAYER.get(deepest) if deepest else None,
        "gates": gates,
        "inputs": hashes,
        "digest": digest_of(hashes),
    }
    if reviewed is not None:
        att["reviewed_through"] = reviewed
    if minimum is not None:
        att["minimum_from_threat"] = minimum
    if reviewed is not None and minimum is not None:
        att["review_depth_ok"] = layer_rank(reviewed) >= layer_rank(minimum)
    if policy_path(context).exists():
        att["policy"] = rel(policy_path(context))
    return att


def render_trailer(att: dict) -> str:
    lines = [
        f"Verified-Through: {att.get('verified_layer') or att.get('verified_through') or 'none'}",
        f"Spec-Digest: {att['digest']}",
        "Pipeline: " + ", ".join(g["name"] for g in att["gates"]),
    ]
    if "reviewed_through" in att:
        lines.append(f"Reviewed-Through: {att['reviewed_through']}")
    if "minimum_from_threat" in att:
        lines.append(f"Minimum-From-Threat: {att['minimum_from_threat']}")
    if "review_depth_ok" in att:
        lines.append(f"Review-Depth-OK: {str(att['review_depth_ok']).lower()}")
    return "\n".join(lines)


def cmd_emit(args) -> int:
    _, reviewed, minimum, out = resolve_policy(
        args.context, args.reviewed_through, args.minimum_from_threat, args.out
    )
    att = build(args.context, reviewed, minimum)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(att, indent=2, sort_keys=True) + "\n")
        print(f"attestation: {out}", file=sys.stderr if args.format == "json" else sys.stdout)

    if args.format == "trailer":
        print(render_trailer(att))
    else:
        print(json.dumps(att, indent=2, sort_keys=True))
    return 0


def cmd_check(args) -> int:
    if not args.attestation.is_file():
        print(f"FAIL: no attestation at {args.attestation}")
        return 1
    recorded = json.loads(args.attestation.read_text())
    current = build(args.context, None, None)

    problems: list[str] = []
    if recorded.get("context") != current["context"]:
        problems.append(
            f"context mismatch: attestation is for {recorded.get('context')!r}, "
            f"not {current['context']!r}"
        )
    if recorded.get("digest") != current["digest"]:
        problems.append(
            f"spec digest drifted: attestation {recorded.get('digest')} != current {current['digest']}"
        )
        changed = sorted(set(recorded.get("inputs", {})) | set(current["inputs"]))
        for path in changed:
            if recorded.get("inputs", {}).get(path) != current["inputs"].get(path):
                problems.append(f"  input changed: {path}")
    recorded_gates = [g["name"] for g in recorded.get("gates") or []]
    current_gates = [g["name"] for g in current["gates"]]
    if recorded_gates != current_gates:
        problems.append(
            "gate set drifted: "
            f"recorded [{', '.join(recorded_gates)}] != current [{', '.join(current_gates)}]"
        )
    if recorded.get("review_depth_ok") is False:
        problems.append("recorded review depth is below the threat-narrative minimum")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        print(f"\nFAIL: attestation does not match the current spec.")
        return 1

    print(f"PASS: attestation matches the current spec ({current['digest']}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    emit = sub.add_parser("emit", help="compute and print the attestation")
    emit.add_argument("--context", required=True)
    emit.add_argument("--format", choices=["json", "trailer"], default="json")
    emit.add_argument("--out", type=Path, help="write the JSON attestation here")
    emit.add_argument("--reviewed-through", choices=REVIEW_LAYERS)
    emit.add_argument("--minimum-from-threat", choices=REVIEW_LAYERS)

    check = sub.add_parser("check", help="verify a recorded attestation")
    check.add_argument("--context", required=True)
    check.add_argument("--attestation", required=True, type=Path)

    args = parser.parse_args()
    if args.cmd == "emit":
        return cmd_emit(args)
    return cmd_check(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except yaml.YAMLError as exc:
        die(f"invalid YAML: {exc}")
