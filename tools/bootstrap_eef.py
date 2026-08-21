#!/usr/bin/env python3
"""bootstrap_eef.py — ONE file that provisions a brand-new EEF node from GITHUB.

On a fresh machine (Python 3.11+ installed) you either copy this file over, or
run the PowerShell one-liner:

    powershell -nop -c "irm https://raw.githubusercontent.com/eepyfishy/eefn/main/install.ps1 | iex"
    # or (manual single file):
    python bootstrap_eef.py --psk SECRET

What it does:
  1. Downloads the node dist zip from GitHub (eefn repo) — not from the coordinator.
  2. Extracts it into the install dir (default C:/eefn on Windows).
  3. Writes config.json (node_id, name, psk, ordered endpoints).
  4. Ensures the `cryptography` package is present (AES-256-GCM links).
  5. Leaves start.cmd so you can launch the node with one double-click.

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
# GitHub is the source of truth for the node package (public eefn repo).
GITHUB_PKG = "https://github.com/eepyfishy/eefn/raw/main/dist/eef-node-dist.zip"
# No explicit port: Playit already forwards to 8081 by default.
DEFAULT_PLAYIT = "node.eeftuna.playit.plus"


def _default_install_dir() -> str:
    return DEFAULT_INSTALL_WIN if os.name == "nt" else DEFAULT_INSTALL_POSIX


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - user-supplied endpoint
        dest.write_bytes(resp.read())


def _ensure_cryptography() -> None:
    try:
        import cryptography  # noqa: F401

        return
    except Exception:  # noqa: BLE001
        pass
    print("[bootstrap] installing 'cryptography' (needed for AES-256-GCM node links)...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--user", "cryptography"], check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a fresh EEF node from GitHub")
    parser.add_argument("--pkg", default=GITHUB_PKG, help="node package zip URL (default: GitHub eefn dist)")
    parser.add_argument("--dir", default=_default_install_dir(), help="install dir (default C:/eefn on Windows)")
    parser.add_argument("--name", default=socket.gethostname() or "node", help="human-readable node name")
    parser.add_argument("--id", default="", help="node id (default: node-<hostname>)")
    parser.add_argument("--psk", default=os.environ.get("EEF_NODE_PSK", ""), help="shared secret")
    parser.add_argument(
        "--coordinator",
        default="26.234.244.3:8081",
        help="primary coordinator endpoint (default 26.234.244.3:8081, Radmin VPN)",
    )
    parser.add_argument("--playit", default=DEFAULT_PLAYIT, help="secondary tunnel endpoint (default Playit, no port needed)")
    args = parser.parse_args()

    if not args.psk:
        print("ERROR: --psk is required (or set EEF_NODE_PSK). It must match the coordinator's node.psk.")
        raise SystemExit(2)

    install_dir = Path(args.dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    print(f"[bootstrap] downloading node package from {args.pkg} ...")
    tmp = Path(tempfile.mkdtemp()) / "node-dist.zip"
    _download(args.pkg, tmp)
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(install_dir)
    tmp.unlink(missing_ok=True)

    if not (install_dir / "run_node.py").exists():
        print(f"ERROR: node package did not extract run_node.py into {install_dir}")
        raise SystemExit(1)

    node_id = args.id or f"node-{socket.gethostname().split('.')[0].lower()}"
    config = {
        "node_id": node_id,
        "name": args.name,
        "psk": args.psk,
        "endpoints": [args.coordinator, args.playit],
    }
    (install_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    _ensure_cryptography()

    print("[bootstrap] installed node to:", install_dir)
    print(f"[bootstrap] node_id={node_id}  endpoints={config['endpoints']}")
    print(f"[bootstrap] start it with:  cd {install_dir} && python run_node.py")


if __name__ == "__main__":
    main()