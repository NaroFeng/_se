"""Static analysis: every JS module import must resolve to an existing file."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "static" / "js"

IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"\n]+\s+from\s+)?|import\(\s*|export\s+(?:[^'"\n]+\s+from\s+)?)['"]([^'"]+)['"]"""
)


def _walk_js_files():
    yield from ROOT.rglob("*.js")


def test_all_relative_imports_resolve():
    missing = []
    for f in _walk_js_files():
        text = f.read_text(encoding="utf-8")
        for match in IMPORT_RE.findall(text):
            if not match.startswith("."):
                continue  # bare specifier / absolute path
            target = (f.parent / match).resolve()
            # strip query/hash (none expected here, but be safe)
            target = Path(str(target).split("?")[0].split("#")[0])
            if not target.exists():
                missing.append(f"{f.relative_to(ROOT.parent)} -> {match}  (resolved {target})")
    assert not missing, "Unresolved JS imports:\n  " + "\n  ".join(missing)


def test_no_module_uses_illegal_double_dot():
    bad = []
    for f in _walk_js_files():
        text = f.read_text(encoding="utf-8")
        for match in IMPORT_RE.findall(text):
            if not match.startswith("."):
                continue
            # compute how many levels we go up and how many segments remain
            parts = match.replace("\\", "/").split("/")
            ups = sum(1 for p in parts if p == "..")
            downs = [p for p in parts if p not in (".", "..")]
            file_depth = len(f.relative_to(ROOT).parts) - 1  # -1 for the file itself
            if ups > file_depth:
                bad.append(f"{f.relative_to(ROOT.parent)} -> {match}")
    assert not bad, "Import escapes its directory:\n  " + "\n  ".join(bad)


def test_all_js_files_parse():
    """Smoke-test: every .js file must be valid ECMAScript (catches stray
    top-level `return` statements etc.)."""
    import subprocess
    bad = []
    for f in _walk_js_files():
        try:
            r = subprocess.run(
                ["node", "--check", str(f)],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pytest.skip("node executable not found on PATH")
        if r.returncode != 0:
            bad.append(f"{f.relative_to(ROOT.parent)}:\n  {r.stderr.strip()}")
    assert not bad, "JS syntax errors:\n" + "\n".join(bad)