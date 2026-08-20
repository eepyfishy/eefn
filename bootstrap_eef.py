#!/usr/bin/env python3
"""bootstrap_eef.py — ONE file that provisions a brand-new EEF node.

On a fresh machine (Python 3.11+ installed) you either copy this file over, or —
from anywhere with network reach to the coordinator — run the one-liner:

    powershell -nop -c "irm http://26.234.244.3:8081/api/node/install.ps1 | iex"
    # or (manual single file):
    python bootstrap_eef.py --from http://26.234.244.3:8081 --psk SECRET

What it does:
  1. Downloads the node package from the coordinator  (/api/node/dist.zip)
  2. Extracts it into the install dir (default C:/eefn on Windows)
  3. Writes config.json (node_id, name, psk, ordered endpoints: Radmin -> Playit)
  4. Ensures the `cryptography` package is present (AES-256-GCM links)
  5. Leaves start.cmd so you can launch the node with one double-click

stdlib only — nothing to install to run the bootstrap itself.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_INSTALL_WIN = "C:/eefn"
DEFAULT_INSTALL_POSIX = "/opt/eefn"


def _default_install_dir() -> str:
    return DEFAULT_INSTALL_WIN if os.name == "nt" else DEFAULT_INSTALL_POSIX


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - user-supplied endpoint
        dest.write_bytes(resp.read())


def _ensure_cryptography(install_dir: Path) -> None:
    try:
        import cryptography  # noqa: F401

        return
    except Exception:  # noqa: BLE001
        pass
    print("[bootstrap] installing 'cryptography' (needed for AES-256-GCM node links)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--user", "cryptography"], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a fresh EEF node")
    parser.add_argument("--from", dest="base", required=True, help="coordinator base URL, e.g. http://26.234.244.3:8081")
    parser.add_argument("--dir", default=_default_install_dir(), help="install dir (default C:/eefn on Windows)")
    parser.add_argument("--name", default=socket.gethostname() or "node", help="human-readable node name")
    parser.add_argument("--id", default="", help="node id (default: node-<hostname>)")
    parser.add_argument("--psk", default=os.environ.get("EEF_NODE_PSK", ""), help="shared secret")
    parser.add_argument("--playit", default="node.eeftuna.playit.plus:8081", help="secondary tunnel endpoint")
    args = parser.parse_args()

    if not args.psk:
        print("ERROR: --psk is required (or set EEF_NODE_PSK). It must match the coordinator's node.psk.")
        raise SystemExit(2)

    base = args.base.rstrip("/")
    install_dir = Path(args.dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    print(f"[bootstrap] downloading node package from {base}/api/node/dist.zip ...")
    tmp = Path(tempfile.mkdtemp()) / "node-dist.zip"
    _download(f"{base}/api/node/dist.zip", tmp)
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(install_dir)
    tmp.unlink(missing_ok=True)

    host = urllib.request.urlparse(base).hostname or "127.0.0.1"
    primary = f"{host}:8081"
    node_id = args.id or f"node-{socket.gethostname().split('.')[0].lower()}"
    config = {"node_id": node_id, "name": args.name, "psk": args.psk, "endpoints": [primary, args.playit]}
    (install_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    _ensure_cryptography(install_dir)

    if not (install_dir / "run_node.py").exists():
        print(f"ERROR: node package did not extract run_node.py into {install_dir}")
        raise SystemExit(1)

    print("[bootstrap] installed node to:", install_dir)
    print(f"[bootstrap] node_id={node_id}  endpoints={config['endpoints']}")
    print(f"[bootstrap] start it with:  cd {install_dir} && python run_node.py")


if __name__ == "__main__":
    main()