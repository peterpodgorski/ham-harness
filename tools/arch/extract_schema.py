#!/usr/bin/env python3
"""Extract the SQLite schema from the adapter's DDL into a database model.

The schema is defined by the `CREATE TABLE` statements in
`app/src/expense_tracking/adapters/sqlite_store.rs`. This tool parses
those statements (no database connection required) and emits the shared
database-model JSON consumed by `schema_render.py`.

Usage:
    extract_schema.py --src app/src/expense_tracking/adapters/sqlite_store.rs \
        --context expense_tracking > architecture/expense_tracking/database-asbuilt.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)

# Definitions that start with one of these are table-level constraints, not
# columns. This schema declares no foreign keys, so they are skipped.
TABLE_CONSTRAINTS = {"PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT"}

COLUMN_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)(.*)$", re.DOTALL
)


def _matching_paren(text: str, open_at: int) -> int:
    """Return the index just past the ')' matching the '(' at `open_at`."""
    depth = 0
    for i in range(open_at, len(text)):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced parentheses in CREATE TABLE")


def _split_top_level(body: str) -> list[str]:
    """Split a DDL body on commas that are not nested in parentheses."""
    parts: list[str] = []
    depth = 0
    current = ""
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current)
    return parts


def _parse_column(definition: str) -> dict | None:
    text = " ".join(definition.split())
    if not text:
        return None
    head = text.split(" ", 1)[0].rstrip("(").upper()
    if head in TABLE_CONSTRAINTS:
        return None
    match = COLUMN_RE.match(text)
    if not match:
        return None
    name, sql_type, rest = match.groups()
    upper = rest.upper()
    return {
        "name": name,
        "type": sql_type.upper(),
        "primary_key": "PRIMARY KEY" in upper,
        "not_null": "NOT NULL" in upper,
        "unique": "UNIQUE" in upper,
    }


def extract(sql: str, context: str) -> dict:
    tables: dict[str, dict] = {}
    for match in CREATE_RE.finditer(sql):
        name = match.group(1).lower()
        # The same table can appear twice during migrations; first wins.
        if name in tables:
            continue
        open_at = match.end() - 1
        end = _matching_paren(sql, open_at)
        body = sql[open_at + 1 : end - 1]
        columns = [
            column
            for definition in _split_top_level(body)
            if (column := _parse_column(definition))
        ]
        tables[name] = {"name": name, "columns": columns}
    return {"context": context, "tables": [tables[key] for key in sorted(tables)]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--context", required=True)
    args = parser.parse_args()

    model = extract(args.src.read_text(), args.context)
    json.dump(model, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
