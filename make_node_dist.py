#!/usr/bin/env python3
"""Build eef-node-dist.zip from the flat node modules in THIS repo.

    python make_node_dist.py          # -> dist/eef-node-dist.zip

The dist is what a fresh node pulls via the coordinator's /api/node/dist.zip, or
what this repo provisions directly. Because everything here is flat and
self-contained (stdlib + cryptography only), the zip is the running node.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
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

Installed into its own directory (default C:/eefn) by bootstrap_eef.py. The
bootstrap writes config.json (node_id, name, psk, ordered endpoints) here.

Run:  python run_node.py
Options:  --connect H:PORT,list   --name NAME   --id ID   --psk SECRET   --allow-write

Requires: Python 3.11+ and the `cryptography` package (installed by the bootstrap).
"""


def build(out: str | Path | None = None) -> Path:
    out_path = Path(out) if out else DIST / "eef-node-dist.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES:
            zf.write(HERE / name, name)
        zf.writestr("README.txt", README)
    return out_path


if __name__ == "__main__":
    path = build()
    print(f"built {path} ({path.stat().st_size} bytes)", file=sys.stderr)