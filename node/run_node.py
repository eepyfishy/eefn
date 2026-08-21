#!/usr/bin/env python3
"""Standalone EEF node entry point (installed into C:/eefn by the bootstrap).

Reads config.json next to this file (node_id, name, psk, ordered endpoints),
then connects to the coordinator. stdlib + cryptography only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"


def load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    parser = argparse.ArgumentParser(description="EEF node")
    parser.add_argument("--connect", help="comma-separated host:port endpoints (overrides config.json)")
    parser.add_argument("--name", default=cfg.get("name", "node"))
    parser.add_argument("--id", default=cfg.get("node_id", ""))
    parser.add_argument("--psk", default=cfg.get("psk") or os.environ.get("EEF_NODE_PSK", ""))
    parser.add_argument("--allow-write", action="store_true", help="enable filesystem writes on this node")
    args = parser.parse_args()

    from node_client import NodeClient  # type: ignore
    from node_engine import NodeEngine  # type: ignore

    if not args.psk:
        print("ERROR: no --psk given and none in config.json (set EEF_NODE_PSK too)")
        raise SystemExit(2)

    endpoints = list(cfg.get("endpoints", []))
    if args.connect:
        endpoints = [e.strip() for e in args.connect.split(",") if e.strip()]
    node_id = args.id or f"node-{os.environ.get('COMPUTERNAME', 'pc').lower()}"
    engine = NodeEngine(allow_write=args.allow_write)
    client = NodeClient(endpoints, node_id, args.name, args.psk, engine)
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("node stopped")


if __name__ == "__main__":
    main()