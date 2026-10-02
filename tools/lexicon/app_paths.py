"""Resolve app artifact paths against an app-relative lexicon key.

The lexicon is an **app** artifact, so its `quint.specs` / `alloy.specs` entries
are keyed by paths relative to the app repository root (`stories/...`,
`architecture/...`). The harness may pass the same file with the app mount
prefix (`app/...`). Normalize before the lookup so neither side has to know the
other's convention.
"""
from __future__ import annotations

import os
from pathlib import Path


def spec_key(spec: Path, lexicon_dir: Path, entries: dict) -> str | None:
    """Return the lexicon key for `spec`, or None if it is not declared."""
    raw = str(spec)
    if raw in entries:
        return raw
    app_root = lexicon_dir.resolve().parent
    try:
        rel = os.path.relpath(spec.resolve(), app_root)
    except ValueError:
        return None
    return rel if rel in entries else None