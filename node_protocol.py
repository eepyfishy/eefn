"""Node wire protocol: newline-delimited JSON, each line AES-256-GCM encrypted.

Message kinds:
    auth      -> signed handshake (nonce|node_id|version|timestamp)
    ok/denied <- server verdict
    register  -> node advertises capabilities + specs
    heartbeat -> {node_id, load, latency, specs} for load-based routing
    request   -> coordinator asks a node to run capability/action/params
    response  -> node replies {id, success, data|error}
    announce  -> capability upsert (future)

Framing: one JSON object per line; the line is ``crypto.encrypt(json)``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Optional

ADD = 512 * 1024  # max message size after base64 (~512KB ciphertext allowance)

PROTOCOL_VERSION = 1


def now_ms() -> int:
    return int(time.time() * 1000)


def encode_line(crypto, message: Dict[str, Any]) -> bytes:
    """Encrypt a dict into a single wire line (bytes ending in \\n)."""
    payload = json.dumps(message, separators=(",", ":"), default=str).encode("utf-8")
    return crypto.encrypt(payload).encode("ascii") + b"\n"


async def read_message(crypto, reader: asyncio.StreamReader) -> Optional[Dict[str, Any]]:
    """Read + decrypt one wire line, or None on clean EOF."""
    line = await reader.readuntil(b"\n")
    if not line:
        return None
    token = line.strip().decode("ascii")
    if not token:
        return None
    plaintext = crypto.decrypt(token)
    return json.loads(plaintext.decode("utf-8"))


# -- message builders (client side) ---------------------------------------

def build_auth(crypto, node_id: str, version: str) -> Dict[str, Any]:
    nonce = str(now_ms())
    ts = str(now_ms())
    raw = f"{nonce}|{node_id}|{version}|{ts}".encode("utf-8")
    return {
        "type": "auth",
        "protocol": PROTOCOL_VERSION,
        "node_id": node_id,
        "version": version,
        "nonce": nonce,
        "timestamp": ts,
        "signature": crypto.sign(raw),
    }


def build_register(node_id: str, name: str, version: str, capabilities: list, specs: dict, models: list) -> Dict[str, Any]:
    return {
        "type": "register",
        "node_id": node_id,
        "name": name,
        "version": version,
        "capabilities": capabilities,
        "specs": specs,
        "models": models,
    }


def build_heartbeat(node_id: str, load: Dict[str, Any], latency_ms: float = 0.0, specs: Optional[dict] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"type": "heartbeat", "node_id": node_id, "load": load, "latency_ms": latency_ms}
    if specs:
        msg["specs"] = specs
    return msg


def build_response(request_id: str, success: bool, data: Any = None, error: str = "") -> Dict[str, Any]:
    msg: Dict[str, Any] = {"type": "response", "id": request_id, "success": success}
    if success:
        msg["data"] = data
    else:
        msg["error"] = error
    return msg