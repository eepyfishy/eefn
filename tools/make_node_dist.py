#!/usr/bin/env python3
"""Build dist/eef-node-dist.zip from the flat standalone bundle in node/.

    python tools/make_node_dist.py          # -> dist/eef-node-dist.zip

The dist is what a fresh node pulls from GITHUB during provisioning
(https://github.com/eepyfishy/eefn/raw/main/dist/eef-node-dist.zip), and is
committed to the repo so that URL always resolves.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
NODE = HERE / "node"
DIST = HERE / "dist"

FILES = [
    "node_crypto.py",
    "node_protocol.py",
    "node_engine.py",
    "node_client.py",
    "run_node.py",
    "start.cmd",
]

README = """EEF Node — standalone node runtime.

Installed into its own directory (default C:/eefn) by bootstrap_eef.py, which
writes config.json (node_id, name, psk, ordered endpoints) here.

Run:  python run_node.py
Options:  --connect H:PORT,list   --name NAME   --id ID   --psk SECRET   --allow-write

Requires: Python 3.11+ and the `cryptography` package (installed by the bootstrap).
"""


def build(out: str | Path | None = None) -> Path:
    out_path = Path(out) if out else DIST / "eef-node-dist.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES:
            zf.write(NODE / name, name)
        zf.writestr("README.txt", README)
    return out_path


if __name__ == "__main__":
    path = build()
    print(f"built {path} ({path.stat().st_size} bytes)", file=sys.stderr)