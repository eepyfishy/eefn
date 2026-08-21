"""Node server — the coordinator's TCP gateway for node links.

Accepts in-bound node connections: signed AUTH, register (capabilities/specs/
models), heartbeat (real load → routing), and forwards coordinator requests to
connected nodes via invoke_remote. Runs inside the coordinator process (eef) but
lives here in the node system package.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from eefn.crypto import CryptoError, NodeCrypto
from eefn.protocol import encode_line, read_message

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8081


class NodeOfflineError(RuntimeError):
    """The requested node is not connected."""


class _Conn:
    """A single authenticated node link with a per-connection send lock."""

    def __init__(self, node_id: str, writer: asyncio.StreamWriter) -> None:
        self.node_id = node_id
        self.writer = writer
        self.send_lock = asyncio.Lock()
        self.connected_since = time.time()

    async def send(self, crypto: NodeCrypto, msg: dict) -> None:
        async with self.send_lock:
            self.writer.write(encode_line(crypto, msg))
            await self.writer.drain()

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:  # noqa: BLE001
            pass


class NodeServer:
    """Coordinator-side node gateway."""

    def __init__(self, psk: str, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.crypto = NodeCrypto(psk)
        self._server: Optional[asyncio.AbstractServer] = None
        self._conns: Dict[str, _Conn] = {}
        self._pending: Dict[str, asyncio.Future] = {}
        # callbacks wired by the coordinator runtime
        self.on_register: Optional[Callable[[dict], Awaitable[None]]] = None
        self.on_heartbeat: Optional[Callable[[dict], Awaitable[None]]] = None
        self.on_node_down: Optional[Callable[[str], Awaitable[None]]] = None
        self.local_dispatch: Optional[Callable[[str, str, dict], Awaitable[Any]]] = None

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_conn, self.host, self.port)
        # report the ACTUAL bound port (used when config port is 0 / ephemeral)
        if self.port == 0 and self._server.sockets:
            self.port = self._server.sockets[0].getsockname()[1]
        logger.info("node server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()
        if self._server:
            loop = self._server.get_loop()
            server = self._server
            self._server = None
            # Windows proactor sockets must close while their loop is alive
            if loop is not None and not loop.is_closed():
                server.close()
                await server.wait_closed()
        self._pending.clear()
        logger.info("node server stopped")

    def connected_nodes(self) -> Dict[str, dict]:
        return {nid: {"node_id": c.node_id, "uptime": time.time() - c.connected_since} for nid, c in self._conns.items()}

    # -- inbound connections ----------------------------------------------
    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        node_id: Optional[str] = None
        try:
            try:
                auth = await asyncio.wait_for(read_message(self.crypto, reader), timeout=15)
            except CryptoError:
                await self._deny(writer, "auth failed")
                return
            if not self._verify_auth(auth):
                await self._deny(writer, "auth failed")
                return
            node_id = str(auth["node_id"])
            writer.write(encode_line(self.crypto, {"type": "ok"}))
            await writer.drain()
            conn = _Conn(node_id, writer)
            self._conns[node_id] = conn
            logger.info("node authenticated: %s", node_id)
            await self._serve(conn, reader)
        except asyncio.TimeoutError:
            writer.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("inbound connection error: %s", exc)
            writer.close()
        finally:
            if node_id and node_id in self._conns:
                self._conns.pop(node_id, None)
                if self.on_node_down:
                    try:
                        await self.on_node_down(node_id)
                    except Exception:  # noqa: BLE001
                        logger.exception("on_node_down handler failed")

    async def _deny(self, writer: asyncio.StreamWriter, reason: str) -> None:
        try:
            writer.write(encode_line(self.crypto, {"type": "denied", "error": reason}))
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    async def _serve(self, conn: _Conn, reader: asyncio.StreamReader) -> None:
        while True:
            msg = await read_message(self.crypto, reader)
            if msg is None:
                break
            mtype = msg.get("type")
            if mtype == "register" and self.on_register:
                await safe_call(self.on_register, msg)
            elif mtype == "heartbeat" and self.on_heartbeat:
                await safe_call(self.on_heartbeat, msg)
            elif mtype == "response":
                self._resolve_response(msg)
            elif mtype == "announce":
                logger.debug("announce from %s (ignored)", conn.node_id)

    def _verify_auth(self, auth: Optional[dict]) -> bool:
        if not auth or auth.get("type") != "auth":
            return False
        try:
            node_id = str(auth["node_id"])
            version = str(auth["version"])
            nonce = str(auth["nonce"])
            ts = str(auth["timestamp"])
            sig = str(auth["signature"])
        except (KeyError, TypeError):
            return False
        raw = f"{nonce}|{node_id}|{version}|{ts}".encode("utf-8")
        try:
            return self.crypto.verify(raw, sig)
        except Exception:  # noqa: BLE001
            return False

    async def invoke_remote(self, node_id: str, capability: str, action: str, params: dict, timeout: float = 30.0) -> Any:
        """Send a request to a connected node and await its response."""
        conn = self._conns.get(node_id)
        if conn is None:
            raise NodeOfflineError(f"node '{node_id}' is not connected")
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        await conn.send(
            self.crypto,
            {"type": "request", "id": request_id, "capability": capability, "action": action, "params": params},
        )
        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise TimeoutError(f"node '{node_id}' did not answer within {timeout}s") from None
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            raise
        return result

    def _resolve_response(self, msg: dict) -> None:
        request_id = msg.get("id")
        if not request_id:
            return
        fut = self._pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(msg)


async def safe_call(fn: Callable[[dict], Awaitable[None]], payload: dict) -> None:
    """Run a wired handler without letting it break the serve loop."""
    try:
        await fn(payload)
    except Exception:  # noqa: BLE001
        logger.exception("handler failed")
