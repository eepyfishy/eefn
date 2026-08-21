#!/usr/bin/env python3
"""Regenerate the flat standalone node bundle (`node/`) from the eefn package.

The `eefn/` package modules are the single source of truth. A fresh node runs
flat, self-contained modules (stdlib + cryptography) with no package install, so
this tool rewrites `from eefn.X import ...` into `from node_X import ...` and
copies the result — plus the static run_node.py / start.cmd — into `node/`.

Usage:  python tools/emit_node.py
        python tools/emit_node.py --check   # verify committed node/ is in sync
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PKG = HERE / "eefn"
NODE = HERE / "node"

# package module -> flat filename (no extension)
MODULES = {"crypto": "node_crypto", "protocol": "node_protocol", "engine": "node_engine", "client": "node_client"}

STATIC = ["run_node.py", "start.cmd"]

# rewrite `from eefn.crypto import X` -> `from node_crypto import X`
_IMPORT_RE = re.compile(r"^(\s*from\s+)eefn\.([a-z_]+)(\s+import\b.*)$")


def _rewrite(body: str, flat_name: str) -> str:
    out = []
    for line in body.splitlines():
        match = _IMPORT_RE.match(line)
        if match:
            line = f"{match.group(1)}{MODULES.get(match.group(2), match.group(2))}{match.group(3)}"
        out.append(line)
    return "\n".join(out) + ("\n" if body.endswith("\n") else "")


def emit(dest: Path = NODE) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for pkg_name, flat_name in MODULES.items():
        source = (PKG / f"{pkg_name}.py").read_text(encoding="utf-8")
        (dest / f"{flat_name}.py").write_text(_rewrite(source, flat_name), encoding="utf-8")
    for name in STATIC:
        (dest / name).write_text((HERE / name).read_text(encoding="utf-8"), encoding="utf-8")


def emit_into(tmp: Path) -> None:
    """Emit into a temp dir (used by tests to compare against committed node/)."""
    emit(tmp)


def check_sync() -> bool:
    """Return True if emitting into a temp dir matches the committed node/."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        emit_into(Path(td))
        for name in [f"{flat}.py" for flat in MODULES.values()] + STATIC:
            if (Path(td) / name).read_bytes() != (NODE / name).read_bytes():
                print(f"OUT OF SYNC: {name} — run tools/emit_node.py", file=sys.stderr)
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify node/ is in sync (exit 1 if not)")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if check_sync() else 1)
    emit()
    print("emitted flat node bundle into", NODE, file=sys.stderr)


if __name__ == "__main__":
    main()