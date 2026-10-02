#!/usr/bin/env python3
"""Alloy <-> lexicon conformance gate.

The Alloy domain model is a second projection of the ubiquitous language. This
tool checks that the two projections have not drifted apart, mirroring
`quint_check.py` for the structural side:

  * every `sig` in the model is declared in `lexicon.alloy.sigs` and maps to a
    known term (or is explicitly `system: true`);
  * every `check`/`run` command is declared under `checks`/`witnesses`, is owned
    by a known term, and every declared command exists in the model;
  * temporal models (those with `var` fields) declare and set the MBT
    conventions (`action_field`, `arg_fields`) the runner depends on;
  * no `Int` arithmetic leaks into a domain model. Alloy `Int` is a bounded
    bitvector and arithmetic belongs to the lexicon relations.

Usage:
    alloy_check.py --context expense_tracking \
        --spec architecture/expense_tracking/domain.als

Exit codes: 0 conform, 1 conformance failures, 2 config/spec error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

import app_paths
from relations_loader import load_relations

# The category -> group mapping is owned by the app's conformance oracle
# (`app/lexicon/relations.py`). The Alloy catalog is a projection of it and must
# not drift. Loaded from --lexicon-dir in main().
CATEGORY_GROUPS: dict[str, str] = {}


class ConfigError(Exception):
    pass


def die(msg: str) -> None:
    print(f"lexicon-alloy: error: {msg}", file=sys.stderr)
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
        "alloy": context_doc.get("alloy") or {},
    }


# ---------------------------------------------------------------------------
# A deliberately small Alloy reader: we only need names, not semantics.
# ---------------------------------------------------------------------------

# Int arithmetic function names. `+`/`-` are set operations in Alloy and are
# allowed; these are not.
ARITHMETIC = re.compile(r"\b(plus|minus|mul|div|rem|sum|int)\s*\[")


def _braced_body(source: str) -> str:
    """Return the text inside the first balanced `{...}` in `source`."""
    start = source.find("{")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : i]
    return source[start + 1 :]


# Domain types are: abstract sigs (extension bases), enums, and sigs whose body
# declares fields. Leaf value atoms (`one sig Rent extends Category`) and enum
# variants are not lexicon terms; they inherit their owner. This mirrors how
# `quint_check.py` treats actions vs. helpers.
SIG_DECL = re.compile(
    r"(\babstract\s+)?\b(sig|enum)\s+"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)(\s+extends\s+\w+)?"
)

# The fixed category catalog, e.g.
#   one sig Cat_Rent, Cat_Bills extends Category {} { group = Periodic }
CATEGORY_DECL = re.compile(
    r"one sig\s+([A-Za-z_][\w\s,]*?)\s+extends\s+Category\s*"
    r"\{\s*\}\s*\{\s*group\s*=\s*(\w+)\s*\}"
)


def read_spec(spec: Path) -> dict:
    if not spec.exists():
        die(f"spec not found: {spec}")
    src = spec.read_text()
    # Strip comments so declarations inside them do not count.
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)

    domain_sigs: set[str] = set()
    leaf_sigs: set[str] = set()
    fields: dict[str, set[str]] = {}
    for m in SIG_DECL.finditer(src):
        is_abstract = bool(m.group(1))
        kind = m.group(2)
        names = [n.strip() for n in m.group(3).split(",")]
        if kind == "enum":
            domain_sigs.update(names)
            continue
        # A body counts only when it follows the declaration directly (i.e.
        # is not an appended fact on a leaf sig).
        after = src[m.end() :]
        body = ""
        brace = after.find("{")
        if brace != -1:
            between = after[:brace]
            if re.fullmatch(r"\s*", between):
                body = _braced_body(after[brace:])
        declared_fields = set(re.findall(r"\b([A-Za-z_]\w*)\s*:", body))
        if is_abstract or declared_fields:
            domain_sigs.update(names)
            for name in names:
                fields[name] = declared_fields
        else:
            leaf_sigs.update(names)

    sigs = domain_sigs

    checks = set(re.findall(r"\bcheck\s+([A-Za-z_]\w*)\s*\{", src))
    runs = set(re.findall(r"\brun\s+([A-Za-z_]\w*)\s*\{", src))

    # `expect` annotations are what make the CLI exit code a gate: without
    # them `alloy exec` exits 0 even on a counterexample (a silent pass).
    expects: dict[str, str | None] = {}
    scopes: dict[str, str | None] = {}
    for m in re.finditer(r"\b(?:check|run)\s+([A-Za-z_]\w*)\s*\{", src):
        # Bound to the command: its body has no `}`, so the first `}` closes it,
        # and the `expect` is on the same line as that closing brace.
        close = src.find("}", m.end())
        if close == -1:
            expects[m.group(1)] = None
            scopes[m.group(1)] = None
            continue
        line_end = src.find("\n", close)
        if line_end == -1:
            line_end = len(src)
        closing = src[close:line_end]
        em = re.search(r"expect\s+([01])", closing)
        expects[m.group(1)] = em.group(1) if em else None
        sm = re.search(r"(for\s+[^\n]*?steps)", closing)
        scopes[m.group(1)] = sm.group(1) if sm else None

    var_fields = set(re.findall(r"\bvar\s+([A-Za-z_]\w*)\s*:", src))
    primed = set(re.findall(r"\b([A-Za-z_]\w*)'", src))

    arithmetic = sorted({m.group(1) for m in ARITHMETIC.finditer(src)})

    category_groups: dict[str, str] = {}
    for m in CATEGORY_DECL.finditer(src):
        group = m.group(2)
        for raw in m.group(1).split(","):
            sig = raw.strip()
            if not sig:
                continue
            name = sig.removeprefix("Cat_").replace("_", " ")
            category_groups[name] = group

    return {
        "sigs": sigs,
        "fields": fields,
        "checks": checks,
        "runs": runs,
        "expects": expects,
        "scopes": scopes,
        "var_fields": var_fields,
        "primed": primed,
        "arithmetic": arithmetic,
        "category_groups": category_groups,
    }


def check_entry(entry: dict, lex: dict, spec_info: dict) -> list[str]:
    problems: list[str] = []

    declared_sigs = entry.get("sigs") or {}
    for name in sorted(spec_info["sigs"]):
        if name not in declared_sigs:
            problems.append(f"sig {name!r} is not declared in lexicon alloy.sigs")
    for name, decl in declared_sigs.items():
        if name not in spec_info["sigs"]:
            problems.append(
                f"lexicon declares sig {name!r} that does not exist in the model"
            )
            continue
        if decl.get("system"):
            continue
        term = decl.get("term")
        if not term:
            problems.append(f"sig {name!r} must declare either `system: true` or `term:`")
        elif term not in lex["terms"]:
            problems.append(f"sig {name!r} maps to unknown term {term!r}")

    # The fixed category catalog must match the conformance oracle exactly.
    if "Category" in lex["terms"] and spec_info["category_groups"]:
        # Lexicon names are the third projection; keep all three in lockstep.
        lex_values = (lex["terms"]["Category"] or {}).get("values")
        if lex_values and set(lex_values) != set(CATEGORY_GROUPS):
            missing = sorted(set(CATEGORY_GROUPS) - set(lex_values))
            extra = sorted(set(lex_values) - set(CATEGORY_GROUPS))
            if missing:
                problems.append(
                    f"lexicon Category.values is missing oracle categories: {missing}"
                )
            if extra:
                problems.append(
                    f"lexicon Category.values has categories not in the oracle: {extra}"
                )

        alloy_catalog = spec_info["category_groups"]
        for cname, group in CATEGORY_GROUPS.items():
            if cname not in alloy_catalog:
                problems.append(
                    f"category {cname!r} is in the lexicon oracle but missing from the Alloy catalog"
                )
            elif alloy_catalog[cname] != group:
                problems.append(
                    f"category {cname!r} is {alloy_catalog[cname]!r} in Alloy "
                    f"but {group!r} in the oracle"
                )
        for cname in alloy_catalog:
            if cname not in CATEGORY_GROUPS:
                problems.append(
                    f"category {cname!r} is in the Alloy catalog but not the lexicon oracle"
                )

    # Field ownership, scoped per sig (field labels are not unique across sigs).
    declared_fields = entry.get("fields") or {}
    for sig, fnames in spec_info["fields"].items():
        sig_decl = declared_fields.get(sig) or {}
        for fname in sorted(fnames):
            if fname not in sig_decl:
                problems.append(
                    f"field {sig}.{fname} is not declared in lexicon alloy.fields"
                )
        for fname, decl in sig_decl.items():
            if fname not in fnames:
                problems.append(
                    f"lexicon declares field {sig}.{fname} that does not exist in the model"
                )
                continue
            if decl.get("system"):
                continue
            term = decl.get("term")
            if not term:
                problems.append(
                    f"field {sig}.{fname} must declare either `system: true` or `term:`"
                )
            elif term not in lex["terms"]:
                problems.append(
                    f"field {sig}.{fname} maps to unknown term {term!r}"
                )
    for sig in declared_fields:
        if sig not in spec_info["fields"]:
            problems.append(
                f"lexicon declares fields for sig {sig!r} that has no fields in the model"
            )

    for name in sorted(spec_info["checks"]):
        if spec_info["expects"].get(name) != "0":
            problems.append(
                f"check {name!r} must declare `expect 0` (otherwise a counterexample exits 0)"
            )
    for name in sorted(spec_info["runs"]):
        if spec_info["expects"].get(name) != "1":
            problems.append(
                f"run {name!r} must declare `expect 1` (otherwise an unreachable witness exits 0)"
            )

    declared_checks = entry.get("checks") or {}
    for name in sorted(spec_info["checks"]):
        if name not in declared_checks:
            problems.append(f"check {name!r} is not declared in lexicon alloy.checks")
    for name, decl in declared_checks.items():
        if name not in spec_info["checks"]:
            problems.append(
                f"lexicon declares check {name!r} that does not exist in the model"
            )
            continue
        term = decl.get("term")
        if not term:
            problems.append(f"check {name!r} is not owned by any term")
        elif term not in lex["terms"]:
            problems.append(f"check {name!r} is owned by unknown term {term!r}")

    declared_witnesses = entry.get("witnesses") or {}
    for name in sorted(spec_info["runs"]):
        if name not in declared_witnesses:
            problems.append(f"run {name!r} is not declared in lexicon alloy.witnesses")
    for name, decl in declared_witnesses.items():
        if name not in spec_info["runs"]:
            problems.append(
                f"lexicon declares witness {name!r} that does not exist in the model"
            )
            continue
        term = decl.get("term")
        if not term:
            problems.append(f"witness {name!r} is not owned by any term")
        elif term not in lex["terms"]:
            problems.append(f"witness {name!r} is owned by unknown term {term!r}")

    # MBT conventions, only meaningful for a temporal model.
    if spec_info["var_fields"]:
        conv = entry.get("conventions") or {}
        action_field = conv.get("action_field")
        if not action_field:
            problems.append(
                "temporal model must declare conventions.action_field "
                "(Alloy XML records states, not actions)"
            )
        elif action_field not in spec_info["var_fields"]:
            problems.append(
                f"action_field {action_field!r} is not a `var` field in the model"
            )
        elif action_field not in spec_info["primed"]:
            problems.append(
                f"action_field {action_field!r} is never assigned (no {action_field}' in any transition)"
            )
        for arg_field in conv.get("arg_fields") or []:
            if arg_field not in spec_info["var_fields"]:
                problems.append(
                    f"arg_field {arg_field!r} is not a `var` field in the model"
                )
            elif arg_field not in spec_info["primed"]:
                problems.append(
                    f"arg_field {arg_field!r} is never assigned (no {arg_field}' in any transition)"
                )

    for fn in spec_info["arithmetic"]:
        problems.append(
            f"Int arithmetic `{fn}[` is not allowed in a domain model "
            "(Alloy Int is bounded; arithmetic belongs to lexicon relations)"
        )

    return problems


def main() -> int:
    global CATEGORY_GROUPS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lexicon-dir", default="app/lexicon", type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--spec", required=True, type=Path)
    args = parser.parse_args()

    CATEGORY_GROUPS = load_relations(args.lexicon_dir).CATEGORY_GROUPS
    lex = load_lexicon(args.lexicon_dir, args.context)
    alloy = lex["alloy"]
    if not alloy:
        die(f"lexicon for {args.context!r} has no `alloy:` mapping section")

    specs = alloy.get("specs") or {}
    key = app_paths.spec_key(args.spec, args.lexicon_dir, specs)
    entry = specs.get(key) if key else None
    if entry is None:
        die(f"lexicon has no alloy.specs entry for {args.spec!r}")

    info = read_spec(args.spec)
    problems = check_entry(entry, lex, info)

    print(f"spec: {args.spec}")
    print("sigs:    " + ", ".join(sorted(info["sigs"])))
    print("checks:  " + ", ".join(sorted(info["checks"])))
    print("witnesses: " + ", ".join(sorted(info["runs"])))

    if problems:
        print()
        for p in problems:
            print(f"FAIL: {p}")
        print(f"\nFAIL: {len(problems)} Alloy<->lexicon conformance problem(s).")
        return 1

    print(f"\nPASS: {args.context} Alloy domain model conforms to the lexicon.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ConfigError as e:
        die(str(e))
    except yaml.YAMLError as e:
        die(f"invalid YAML: {e}")