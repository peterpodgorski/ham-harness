#!/usr/bin/env python3
"""Lexicon gate — verify Gherkin features against a context's controlled vocabulary.

This tool is deliberately *tooling*, not semantics. The lexicon (YAML) is the
language-agnostic source of truth for the ubiquitous language: terms, approved
step templates, and table shapes. This checker only verifies that the Gherkin
text actually speaks that language. It does not, and must not, become a place
where domain meaning lives.

Usage:
    check.py --context expense_tracking [features...]

Exit codes:
    0  all features conform
    1  conformance problems found
    2  lexicon/configuration error
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner

# Closed set of surface shapes. A term names one or more of these; the checker
# knows how to read each. Users cannot supply raw regex here.
SHAPES = {
    "word": r"\S+",
    "quoted": r'"[^"]*"',
    "number": r"-?\d+(?:\.\d+)?",
    "date": r'"[0-9]{4}-[0-9]{2}-[0-9]{2}"',
    "month": r'"[A-Z][a-z]+ [0-9]{4}"',
    "month_name": r"[A-Z][a-z]+",
    "timestamp": r'"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}"',
}

# gherkin-official reports And/But as Conjunction; resolve them to the
# preceding Given/When/Then within the same Background/Scenario.
KEYWORD_TYPE = {"Context": "given", "Action": "when", "Outcome": "then"}
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


class StepSpec:
    __slots__ = ("type", "template", "table", "regex", "bindings")

    def __init__(self, type_, template, table, regex, bindings):
        self.type = type_
        self.template = template
        self.table = table
        self.regex = regex
        self.bindings = bindings  # list[(placeholder, term, group_name)]


def die(msg: str) -> None:
    print(f"lexicon: error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        die(f"missing file: {path}")
    except yaml.YAMLError as e:
        die(f"invalid YAML in {path}: {e}")


def compile_template(template: str, terms: dict) -> tuple[re.Pattern, list]:
    parts: list[str] = []
    bindings: list[tuple[str, dict, str]] = []
    group = 0
    pos = 0
    for m in PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[pos:m.start()]))
        name = m.group(1)
        term = terms.get(name)
        if term is None:
            raise ConfigError(f"template references unknown term {{{name}}}: {template!r}")
        shapes = term.get("shapes") or []
        if not shapes:
            raise ConfigError(f"term {name!r} declares no shapes")
        for shape in shapes:
            if shape not in SHAPES:
                raise ConfigError(f"term {name!r} uses unknown shape {shape!r}")
        group += 1
        sub = "|".join(SHAPES[s] for s in shapes)
        parts.append(f"(?P<g{group}>{sub})")
        bindings.append((name, term, f"g{group}"))
        pos = m.end()
    parts.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(parts) + "$"), bindings


def load_lexicon(lexicon_dir: Path, context: str) -> dict:
    terms: dict = {}
    tables: dict = {}
    steps_raw: list = []

    def absorb(doc: dict) -> None:
        terms.update(doc.get("terms") or {})
        tables.update(doc.get("tables") or {})

    context_path = lexicon_dir / f"{context}.yaml"
    if not context_path.exists():
        die(f"no lexicon for context {context!r} at {context_path}")
    context_doc = load_yaml(context_path)
    for imported in context_doc.get("imports") or []:
        absorb(load_yaml(lexicon_dir / f"{imported}.yaml"))
    absorb(context_doc)
    steps_raw = context_doc.get("steps") or []

    compiled: list[StepSpec] = []
    for spec in steps_raw:
        type_ = spec.get("type")
        if type_ not in KEYWORD_TYPE.values():
            raise ConfigError(f"step has invalid type {type_!r}: {spec.get('template')!r}")
        regex, bindings = compile_template(spec["template"], terms)
        compiled.append(StepSpec(type_, spec["template"], spec.get("table"), regex, bindings))

    return {
        "terms": terms,
        "tables": tables,
        "context": context,
        "compiled": compiled,
        "steps_raw": steps_raw,
    }


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def check_table(lex: dict, spec_table: str | None, table: dict | None, where: str) -> list[str]:
    problems: list[str] = []
    if spec_table is None:
        if table is not None:
            problems.append(f"{where}: step carries a data table but no table shape is declared")
        return problems
    if table is None:
        problems.append(f"{where}: step requires table shape {spec_table!r} but has no table")
        return problems
    schema = lex["tables"].get(spec_table)
    if schema is None:
        problems.append(f"{where}: unknown table shape {spec_table!r}")
        return problems

    rows = table.get("rows") or []
    if not rows:
        problems.append(f"{where}: table shape {spec_table!r} is empty")
        return problems

    def cells(row: dict) -> list[str]:
        return [c["value"] for c in row.get("cells", [])]

    if schema.get("header", True):
        header = cells(rows[0])
        allowed = schema.get("columns") or []
        for col in header:
            if col not in allowed:
                problems.append(f"{where}: unknown column {col!r} (allowed: {', '.join(allowed)})")
        for req in schema.get("required") or []:
            if req not in header:
                problems.append(f"{where}: missing required column {req!r}")
        width = len(header)
        for row in rows[1:]:
            if len(cells(row)) != width:
                problems.append(
                    f"{where}: row has {len(cells(row))} cells, header has {width}"
                )
    else:
        width = len(schema.get("columns") or [])
        labels = schema.get("first_column_values")
        for row in rows:
            row_cells = cells(row)
            if width and len(row_cells) != width:
                problems.append(f"{where}: row has {len(row_cells)} cells, expected {width}")
            if labels and row_cells and row_cells[0] not in labels:
                problems.append(
                    f"{where}: unexpected label {row_cells[0]!r} (allowed: {', '.join(labels)})"
                )
    return problems


def resolve_step(
    lex: dict, step: dict, effective_type: str | None, where: str
) -> tuple[int | None, dict[str, str], list[str]]:
    """Match one Gherkin step to a unique template; return (index, captures, problems).

    A `None` index means the step did not match, which is already reported as a
    problem by the caller, so no step is ever silently dropped from validation.
    `captures` maps a placeholder name to the concrete surface value (quotes
    stripped); a repeated placeholder keeps its first value.
    """
    problems: list[str] = []
    captures: dict[str, str] = {}
    text = step["text"]
    if effective_type is None:
        problems.append(f"{where}: step appears before any Given/When/Then: {text!r}")
        return None, captures, problems

    matches = [
        i
        for i, spec in enumerate(lex["compiled"])
        if spec.type == effective_type and spec.regex.match(text)
    ]
    if not matches:
        problems.append(f"{where}: no {effective_type} template matches: {text!r}")
        return None, captures, problems
    if len(matches) > 1:
        templates = ", ".join(repr(lex["compiled"][i].template) for i in matches)
        problems.append(
            f"{where}: ambiguous step, matches {len(matches)} templates: {text!r} -> {templates}"
        )
        return None, captures, problems

    index = matches[0]
    spec = lex["compiled"][index]
    m = spec.regex.match(text)
    for name, term, group in spec.bindings:
        value = strip_quotes(m.group(group))
        captures.setdefault(name, value)
        values = term.get("values")
        if values and value not in values:
            problems.append(
                f"{where}: {name} {value!r} is not a declared {name} "
                f"(allowed: {', '.join(values)})"
            )
    problems.extend(check_table(lex, spec.table, step.get("dataTable"), where))
    return index, captures, problems


@dataclass
class ScenarioStep:
    type: str
    text: str
    template: str
    captures: dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    name: str
    feature: str
    line: int
    steps: list[ScenarioStep] = field(default_factory=list)


def check_feature(
    lex: dict, path: Path
) -> tuple[list[str], set[int], list[Scenario]]:
    doc = Parser().parse(TokenScanner(path.read_text()))
    feature = doc.get("feature")
    problems: list[str] = []
    used: set[int] = set()
    scenarios: list[Scenario] = []
    if not feature:
        return problems, used, scenarios

    for child in feature["children"]:
        for kind in ("background", "scenario"):
            container = child.get(kind)
            if not container:
                continue
            current_type: str | None = None
            steps: list[ScenarioStep] = []
            for step in container["steps"]:
                keyword_type = step.get("keywordType")
                if keyword_type in KEYWORD_TYPE:
                    current_type = KEYWORD_TYPE[keyword_type]
                where = f"{path}:{step['location']['line']}"
                index, captures, step_problems = resolve_step(
                    lex, step, current_type, where
                )
                problems.extend(step_problems)
                if index is None:
                    continue
                used.add(index)
                if kind == "scenario":
                    steps.append(
                        ScenarioStep(
                            type=current_type or "when",
                            text=step["text"],
                            template=lex["compiled"][index].template,
                            captures=captures,
                        )
                    )
            if kind == "scenario":
                scenarios.append(
                    Scenario(
                        name=container.get("name", "<unnamed>"),
                        feature=str(path),
                        line=container["location"]["line"],
                        steps=steps,
                    )
                )

    return problems, used, scenarios


def collect_used_templates(
    lexicon_dir: Path, context: str, features: list[Path]
) -> tuple[set[str], list[str]]:
    """Matched step templates across `features`, plus the Gherkin problems.

    This is the reusable half of the gate for callers that need to join the
    Gherkin against another artifact (see `quint_check.py --coverage`). Indices
    are resolved back to template strings so callers never depend on the
    compiled-regex ordering.
    """
    lex = load_lexicon(lexicon_dir, context)
    problems: list[str] = []
    used: set[int] = set()
    for feature in features:
        feature_problems, feature_used, _ = check_feature(lex, feature)
        problems.extend(feature_problems)
        used |= feature_used
    return {lex["compiled"][i].template for i in used}, problems


def collect_scenarios(
    lexicon_dir: Path, context: str, features: list[Path]
) -> tuple[list[Scenario], list[str]]:
    """Per-scenario, ordered, matched steps across `features`, plus problems.

    Background steps are validated but not attributed to a scenario: a scenario
    trace is `init` (which embodies the setup) followed by the scenario's own
    matched steps.
    """
    lex = load_lexicon(lexicon_dir, context)
    problems: list[str] = []
    scenarios: list[Scenario] = []
    for feature in features:
        feature_problems, _, feature_scenarios = check_feature(lex, feature)
        problems.extend(feature_problems)
        scenarios.extend(feature_scenarios)
    return scenarios, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument(
        "--show-unused",
        action="store_true",
        help="list declared step templates not exercised by the checked features",
    )
    parser.add_argument("features", nargs="+", type=Path)
    args = parser.parse_args()

    lex = load_lexicon(args.lexicon_dir, args.context)

    all_problems: list[str] = []
    used: set[int] = set()
    for feature in args.features:
        problems, feature_used, _ = check_feature(lex, feature)
        all_problems.extend(problems)
        used |= feature_used

    if args.show_unused:
        unused = [i for i in range(len(lex["compiled"])) if i not in used]
        if unused:
            print(f"-- {len(unused)} declared step template(s) unused across the checked features:")
            for i in unused:
                spec = lex["compiled"][i]
                print(f"   [{spec.type}] {spec.template!r}")

    if all_problems:
        print()
        for p in all_problems:
            print(p)
        print(f"\nFAIL: {len(all_problems)} conformance problem(s).")
        return 1

    print(f"PASS: {args.context} — {len(args.features)} feature(s) conform to the lexicon.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as e:
        die(str(e))
