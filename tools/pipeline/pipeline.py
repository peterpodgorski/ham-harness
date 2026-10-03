#!/usr/bin/env python3
"""Deterministic per-context pipeline: validate, resolve, plan, run.

The registry (`pipeline/gates.yaml`) is the closed catalogue of gates; profiles
(`pipeline/profiles.yaml`) are named bundles; each bounded context selects with
`architecture/<context>/pipeline.yaml`. A gate set is a pure function of those
three inputs:

    resolve(registry, profiles, context_config) -> enabled gates + params

Required gates are injected, unknown fields are rejected, dependencies must be
closed, and an enabled gate whose `applies` glob matches nothing fails. There is
no bypass: a context either runs its configured gates or the config is wrong.

Usage:
    pipeline.py check [--context CTX]      validate registry + all/one config
    pipeline.py plan  --context CTX        print the resolved gate set
    pipeline.py run   --context CTX [--report PATH]
    pipeline.py contexts                   list discovered bounded contexts

Exit codes: 0 ok, 1 gate failure / validation problems, 2 configuration error.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
# The harness assumes one mount point for the app under construction. The app
# repository (code + its `architecture/`, `lexicon/`, `stories/`) lives here.
APP_DIR = ROOT / "app"
REGISTRY_PATH = ROOT / "pipeline" / "gates.yaml"
PROFILES_PATH = ROOT / "pipeline" / "profiles.yaml"
LEXICON_DIR = APP_DIR / "lexicon"
ARCH_DIR = APP_DIR / "architecture"

KINDS = {"automated", "manual"}
COSTS = {"fast", "medium", "slow"}
PARAM_TYPES = {"number", "integer", "string", "boolean"}
ALLOWED_GATE_FIELDS = {
    "phase",
    "description",
    "required",
    "kind",
    "cost",
    "depends",
    "applies",
    "params",
    "command",
}
ALLOWED_CONFIG_FIELDS = {"context", "extends", "gates"}
ALLOWED_CONFIG_GATE_FIELDS = {"enabled", "reason", "params"}


class ConfigError(Exception):
    pass


def die(msg: str) -> None:
    print(f"pipeline: error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        die(f"missing {path}")
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        die(f"invalid YAML in {path}: {exc}")


def validate_registry(doc: dict) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    phases = doc.get("phases")
    if not isinstance(phases, list) or not phases:
        die("registry must declare a non-empty `phases` list")
    gates = doc.get("gates")
    if not isinstance(gates, dict) or not gates:
        die("registry must declare a non-empty `gates` map")

    for gate, spec in gates.items():
        where = f"gate {gate!r}"
        if not isinstance(spec, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        unknown = set(spec) - ALLOWED_GATE_FIELDS
        if unknown:
            problems.append(f"{where}: unknown field(s) {sorted(unknown)}")
        phase = spec.get("phase")
        if phase not in phases:
            problems.append(f"{where}: phase {phase!r} not in {phases}")
        kind = spec.get("kind", "automated")
        if kind not in KINDS:
            problems.append(f"{where}: kind {kind!r} not in {sorted(KINDS)}")
        cost = spec.get("cost", "medium")
        if cost not in COSTS:
            problems.append(f"{where}: cost {cost!r} not in {sorted(COSTS)}")
        if kind == "automated" and not spec.get("command"):
            problems.append(f"{where}: automated gate needs a `command`")
        for dep in spec.get("depends") or []:
            if dep not in gates:
                problems.append(f"{where}: depends on unknown gate {dep!r}")
            if dep == gate:
                problems.append(f"{where}: depends on itself")
        for pname, pspec in (spec.get("params") or {}).items():
            ptype = (pspec or {}).get("type")
            if ptype not in PARAM_TYPES:
                problems.append(
                    f"{where}: param {pname!r} type {ptype!r} not in {sorted(PARAM_TYPES)}"
                )
    return problems, phases


def validate_profiles(doc: dict, gates: dict) -> list[str]:
    problems: list[str] = []
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        die("profiles file must declare a `profiles` map")
    for name, entries in profiles.items():
        if not isinstance(entries, dict):
            problems.append(f"profile {name!r}: must be a mapping of gate -> bool")
            continue
        for gate, value in entries.items():
            if gate not in gates:
                problems.append(f"profile {name!r}: unknown gate {gate!r}")
            if not isinstance(value, bool):
                problems.append(f"profile {name!r}: gate {gate!r} must be a boolean")
    return problems


def discover_contexts() -> list[str]:
    return sorted(
        p.stem for p in LEXICON_DIR.glob("*.yaml") if not p.name.startswith("_")
    )


def config_path(context: str) -> Path:
    return ARCH_DIR / context / "pipeline.yaml"


def load_context_config(context: str) -> tuple[dict, list[str]]:
    path = config_path(context)
    problems: list[str] = []
    if not path.exists():
        return {}, [f"{context}: missing {path.relative_to(ROOT)}"]
    doc = load_yaml(path)
    unknown = set(doc) - ALLOWED_CONFIG_FIELDS
    if unknown:
        problems.append(f"{context}: unknown config field(s) {sorted(unknown)}")
    if doc.get("context") != context:
        problems.append(
            f"{context}: config declares context {doc.get('context')!r}"
        )
    return doc, problems


def matches(glob: str) -> bool:
    return any(ROOT.glob(glob))


def resolve(context: str, registry: dict, profiles: dict) -> tuple[dict, list[str]]:
    gates: dict = registry["gates"]
    cfg, problems = load_context_config(context)

    enabled = {g: False for g in gates}
    sources = {g: "default-off" for g in gates}

    profile_name = cfg.get("extends")
    if profile_name is not None:
        profile = (profiles.get("profiles") or {}).get(profile_name)
        if profile is None:
            problems.append(f"{context}: unknown profile {profile_name!r}")
        else:
            for g, on in profile.items():
                enabled[g] = on
                sources[g] = f"profile:{profile_name}"

    for g, spec in gates.items():
        if spec.get("required"):
            enabled[g] = True
            sources[g] = "required"

    for g, decl in (cfg.get("gates") or {}).items():
        if g not in gates:
            problems.append(f"{context}: unknown gate {g!r} in config")
            continue
        if not isinstance(decl, dict):
            problems.append(f"{context}: gate {g!r} must be a mapping")
            continue
        unknown = set(decl) - ALLOWED_CONFIG_GATE_FIELDS
        if unknown:
            problems.append(f"{context}: gate {g!r} unknown field(s) {sorted(unknown)}")
        if "enabled" not in decl:
            problems.append(f"{context}: gate {g!r} must set `enabled`")
            continue
        if gates[g].get("required") and not decl["enabled"]:
            problems.append(f"{context}: required gate {g!r} cannot be disabled")
        enabled[g] = bool(decl["enabled"])
        sources[g] = "config"

    # Dependencies and applicability.
    for g, on in enabled.items():
        if not on:
            continue
        for dep in gates[g].get("depends") or []:
            if not enabled.get(dep):
                problems.append(
                    f"{context}: gate {g!r} is enabled but depends on disabled {dep!r}"
                )
        applies = gates[g].get("applies")
        if applies:
            pattern = applies.replace("{context}", context)
            if not matches(pattern):
                problems.append(
                    f"{context}: gate {g!r} applies to {pattern!r} but nothing matches"
                )

    # Parameters: defaults overlaid with context overrides, type-checked.
    params: dict[str, dict] = {}
    for g, spec in gates.items():
        if not enabled[g]:
            continue
        resolved: dict = {}
        schema = spec.get("params") or {}
        for pname, pspec in schema.items():
            resolved[pname] = (pspec or {}).get("default")
        override = ((cfg.get("gates") or {}).get(g) or {}).get("params") or {}
        for pname, value in override.items():
            if pname not in schema:
                problems.append(f"{context}: gate {g!r} has unknown param {pname!r}")
                continue
            ptype = schema[pname]["type"]
            if ptype in ("number", "integer") and not isinstance(value, (int, float)):
                problems.append(f"{context}: param {g}.{pname} must be a {ptype}")
            elif ptype == "string" and not isinstance(value, str):
                problems.append(f"{context}: param {g}.{pname} must be a string")
            elif ptype == "boolean" and not isinstance(value, bool):
                problems.append(f"{context}: param {g}.{pname} must be a boolean")
            resolved[pname] = value
        params[g] = resolved

    resolved_gates = {
        g: {"enabled": on, "source": sources[g], "params": params.get(g, {})}
        for g, on in enabled.items()
    }
    return {"context": context, "gates": resolved_gates}, problems


def ordered_enabled(registry: dict, resolved: dict) -> list[tuple[str, dict, str]]:
    gates = registry["gates"]
    out = []
    for phase in registry["phases"]:
        for g, spec in gates.items():
            if spec.get("phase") == phase and resolved["gates"][g]["enabled"]:
                out.append((g, spec, phase))
    return out


def cmd_check(registry: dict, profiles: dict, only: str | None) -> int:
    problems: list[str] = []
    contexts = [only] if only else discover_contexts()
    if only and only not in discover_contexts():
        die(f"unknown context {only!r} (no lexicon/{only}.yaml)")
    for ctx in contexts:
        _, probs = resolve(ctx, registry, profiles)
        problems.extend(probs)

    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} pipeline configuration problem(s).")
        return 1

    print(f"registry: {len(registry['gates'])} gate(s), profiles: "
          f"{', '.join(sorted((profiles.get('profiles') or {}).keys()))}")
    print(f"contexts: {', '.join(contexts)}")
    print(f"\nPASS: pipeline configuration is valid for {len(contexts)} context(s).")
    return 0


def cmd_plan(registry: dict, profiles: dict, context: str) -> int:
    resolved, problems = resolve(context, registry, profiles)
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: cannot resolve {context}.")
        return 1

    print(f"pipeline: {context}")
    print(f"extends:  {load_context_config(context)[0].get('extends') or '<none>'}")
    print()
    print(f"{'PHASE':<10} {'GATE':<20} {'KIND':<10} {'COST':<7} SOURCE")
    for gate, spec, phase in ordered_enabled(registry, resolved):
        kind = spec.get("kind", "automated")
        cost = spec.get("cost", "medium")
        print(f"{phase:<10} {gate:<20} {kind:<10} {cost:<7} {resolved['gates'][gate]['source']}")
    disabled = sorted(
        g for g, r in resolved["gates"].items() if not r["enabled"]
    )
    print()
    print("disabled: " + (", ".join(disabled) or "<none>"))
    return 0


def cmd_run(
    registry: dict,
    profiles: dict,
    context: str,
    report: Path | None,
    log: Path | None,
) -> int:
    resolved, problems = resolve(context, registry, profiles)
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: cannot resolve {context}.")
        return 1

    # The terminal is volatile: a closed window loses a 20-minute run. Tee the
    # whole run to a file so the failure detail is always on disk.
    log_path = log or (ROOT / "pipeline-logs" / f"{context}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")

    def emit(text: str = "") -> None:
        print(text)
        log_file.write(text + "\n")
        log_file.flush()

    gates = registry["gates"]
    plan = ordered_enabled(registry, resolved)
    results: list[tuple[str, str, float, int | None]] = []

    emit(f"pipeline: {context}")
    emit(f"phases:   {' -> '.join(registry['phases'])}")
    emit(f"log:      {log_path}")

    for gate, spec, phase in plan:
        kind = spec.get("kind", "automated")
        header = f"[{phase}] {gate}"
        if kind == "manual":
            emit(f"\n=== {header} — MANUAL (a skill must produce the evidence) ===")
            results.append((gate, "manual", 0.0, None))
            continue

        env = os.environ.copy()
        env["PIPELINE_CONTEXT"] = context
        env["PIPELINE_GATE"] = gate
        env["PIPELINE_PHASE"] = phase
        for pname, value in resolved["gates"][gate]["params"].items():
            env[f"PIPELINE_PARAM_{pname.upper()}"] = str(value)

        emit(f"\n=== {header} — {spec.get('description', '')} ===")
        started = time.monotonic()
        # Stream the gate's output live to the terminal *and* the log. Capturing
        # (rather than inheriting) is what lets us tee; reading line by line
        # keeps a long gate observable instead of buffering until it exits.
        proc = subprocess.Popen(
            ["bash", "-c", spec["command"]],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
            log_file.flush()
        returncode = proc.wait()
        elapsed = time.monotonic() - started
        status = "pass" if returncode == 0 else "FAIL"
        emit(f"--- {header}: {status} ({elapsed:.1f}s)")
        results.append((gate, status, elapsed, returncode))

    failed = [r for r in results if r[1] == "FAIL"]
    emit("\n=== pipeline summary ===")
    for gate, status, elapsed, _ in results:
        suffix = f"{elapsed:.1f}s" if status != "manual" else "manual"
        emit(f"  {status:<5} {gate:<20} {suffix}")

    if report:
        report.write_text(render_report(context, results))
        emit(f"\nreport: {report}")
    emit(f"log: {log_path}")

    if failed:
        emit(f"\nFAIL: {len(failed)} gate(s) failed for {context}.")
        code = 1
    else:
        emit(f"\nPASS: pipeline for {context} completed.")
        code = 0
    log_file.close()
    return code


def render_report(context: str, results: list[tuple]) -> str:
    lines = [
        f"# Pipeline report: {context}",
        "",
        f"- Context: `{context}`",
        f"- Generated: deterministic gate run",
        "",
        "| Gate | Status | Time |",
        "|---|---|---|",
    ]
    for gate, status, elapsed, _ in results:
        time_cell = "manual" if status == "manual" else f"{elapsed:.1f}s"
        lines.append(f"| `{gate}` | {status} | {time_cell} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="validate registry and context configs")
    p_check.add_argument("--context")

    p_plan = sub.add_parser("plan", help="print the resolved gate set")
    p_plan.add_argument("--context", required=True)

    p_run = sub.add_parser("run", help="run the resolved automated gates")
    p_run.add_argument("--context", required=True)
    p_run.add_argument("--report", type=Path)
    p_run.add_argument(
        "--log",
        type=Path,
        help="tee the full run here (default pipeline-logs/<context>.log)",
    )

    sub.add_parser("contexts", help="list discovered bounded contexts")

    args = parser.parse_args()

    registry_doc = load_yaml(REGISTRY_PATH)
    problems, _ = validate_registry(registry_doc)
    profiles_doc = load_yaml(PROFILES_PATH)
    problems += validate_profiles(profiles_doc, registry_doc["gates"])
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} registry/profile problem(s).")
        return 1

    if args.cmd == "contexts":
        print("\n".join(discover_contexts()))
        return 0
    if args.cmd == "check":
        return cmd_check(registry_doc, profiles_doc, args.context)
    if args.cmd == "plan":
        return cmd_plan(registry_doc, profiles_doc, args.context)
    if args.cmd == "run":
        return cmd_run(registry_doc, profiles_doc, args.context, args.report, args.log)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as exc:
        die(str(exc))