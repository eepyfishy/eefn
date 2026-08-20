"""Node client — connects a fresh machine to the coordinator.

Ordered-endpoint failover (Radmin primary → Playit secondary), signed AUTH,
register, heartbeat (real load for routing), and a request/response serve loop.
Reconnects with backoff forever. stdlib + cryptography only.

NOTE: this file runs standalone from a node install dir (flat imports: node_crypto,
node_engine, node_protocol). It is not imported as ``eef.node.client``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
from typing import Any, Dict, List, Optional

from node_crypto import NodeCrypto
from node_engine import NodeEngine
from node_protocol import (
    build_auth,
    build_heartbeat,
    build_register,
    build_response,
    encode_line,
    read_message,
)

logger = logging.getLogger("node")


def system_specs() -> Dict[str, Any]:
    """Best-effort CPU/RAM specs (stdlib only; 0 when unknown)."""
    return {
        "cpu_cores": __import__("os").cpu_count() or 0,
        "cpu_freq_mhz": 0,
        "ram_mb": 0,
        "gpu_model": "",
        "gpu_vram_mb": 0,
        "gpu_family": "",
        "platform": sys.platform,
    }


def current_load() -> Dict[str, Any]:
    """Simple, real-ish load sample (0.0 when psutil absent — still honest)."""
    try:
        import psutil

        return {
            "cpu": psutil.cpu_percent(interval=0.2) / 100.0,
            "ram": psutil.virtual_memory().percent / 100.0,
            "gpu": 0.0,
            "queue": 0,
        }
    except Exception:  # noqa: BLE001
        return {"cpu": 0.0, "ram": 0.0, "gpu": 0.0, "queue": 0}


def discover_models() -> List[Dict[str, Any]]:
    """Advertise local Ollama models (if any) so the router can use this node."""
    try:
        from urllib.request import Request, urlopen

        base = __import__("os").environ.get("EEF_NODE_OLLAMA", "http://localhost:11434")
        req = Request(f"{base}/api/tags")
        with urlopen(req, timeout=2) as resp:  # noqa: S310 - local Ollama
            data = json.loads(resp.read().decode("utf-8"))
        return [{"model_id": m.get("name", ""), "backend": "ollama"} for m in data.get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001
        return []


class NodeClient:
    """Long-running node: connect → authenticate → register → serve."""

    def __init__(
        self,
        endpoints: List[str],
        node_id: str,
        name: str,
        psk: str,
        engine: NodeEngine,
        *,
        version: str = "0.1.0",
        heartbeat_interval: float = 3.0,
    ) -> None:
        self.endpoints = endpoints
        self.node_id = node_id
        self.name = name
        self.crypto = NodeCrypto(psk)
        self.engine = engine
        self.version = version
        self.heartbeat_interval = heartbeat_interval
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def run(self) -> None:
        logger.info("node %s starting (endpoints=%s)", self.node_id, self.endpoints)
        backoff = 1.0
        while True:
            try:
                await self._connect_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("node disconnected: %s; reconnecting in %ss", exc, backoff)
                backoff = min(backoff * 2, 30) + random.random()
                await asyncio.sleep(backoff)

    async def _connect_once(self) -> None:
        last_error: Optional[Exception] = None
        for raw in self.endpoints:
            try:
                host, port = self._parse_endpoint(raw)
                reader, writer = await asyncio.open_connection(host, port)
                self._writer = writer
                await self._auth(reader, writer)
                await self._register(writer)
                self._connected = True
                logger.info("connected via %s:%s authenticated+registered", host, port)
                await self._serve(reader, writer)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("endpoint %s failed: %s", raw, exc)
        raise last_error or ConnectionError("all endpoints failed")

    @staticmethod
    def _parse_endpoint(raw: str) -> tuple:
        host, _, port = raw.rpartition(":")
        return (host or "127.0.0.1"), int(port or 8081)

    async def _auth(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(encode_line(self.crypto, build_auth(self.crypto, self.node_id, self.version)))
        await writer.drain()
        reply = await read_message(self.crypto, reader)
        if not reply or reply.get("type") == "denied":
            raise PermissionError(f"coordinator denied auth: {reply}")

    async def _register(self, writer: asyncio.StreamWriter) -> None:
        msg = build_register(
            self.node_id,
            self.name,
            self.version,
            self.engine.capabilities(),
            system_specs(),
            discover_models(),
        )
        writer.write(encode_line(self.crypto, msg))
        await writer.drain()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop(writer))
        try:
            while True:
                msg = await read_message(self.crypto, reader)
                if msg is None:
                    break
                await self._handle(msg, writer)
        finally:
            heartbeat.cancel()
            self._connected = False
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _heartbeat_loop(self, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                heartbeat = build_heartbeat(self.node_id, current_load(), latency_ms=0.0, specs=system_specs())
                writer.write(encode_line(self.crypto, heartbeat))
                await writer.drain()
                await asyncio.sleep(self.heartbeat_interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass

    async def _handle(self, msg: Dict[str, Any], writer: asyncio.StreamWriter) -> None:
        if msg.get("type") != "request":
            return
        request_id = msg.get("id", "")
        try:
            data = await asyncio.to_thread(
                self.engine.execute, msg.get("capability", ""), msg.get("action", "run"), msg.get("params", {})
            )
            writer.write(encode_line(self.crypto, build_response(request_id, True, data=data)))
            await writer.drain()
        except Exception as exc:  # noqa: BLE001
            writer.write(encode_line(self.crypto, build_response(request_id, False, error=str(exc))))
            await writer.drain()