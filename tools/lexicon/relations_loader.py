#!/usr/bin/env python3
"""Load the app's lexicon relation oracle.

The relation oracle (`relations.py`) encodes the app's derived-value semantics,
so it is **app-owned** and lives in the app's lexicon directory. Harness tools
load it from `--lexicon-dir` rather than keeping their own copy.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_relations(lexicon_dir: Path):
    """Import `<lexicon_dir>/relations.py` and return the module."""
    path = Path(lexicon_dir) / "relations.py"
    if not path.is_file():
        raise FileNotFoundError(f"relations.py not found in {lexicon_dir}")
    spec = importlib.util.spec_from_file_location("app_lexicon_relations", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load relation oracle from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
