"""Node-system tests: crypto, signed AUTH, server register/heartbeat, remote invoke,
and the emitted flat bundle joining a live NodeServer."""

import asyncio
from pathlib import Path

import pytest

from eefn.crypto import CryptoError, NodeCrypto
from eefn.engine import NodeEngine
from eefn.protocol import (
    build_auth,
    build_register,
    build_response,
    encode_line,
    read_message,
)
from eefn.server import NodeOfflineError, NodeServer

PSK = "test-shared-secret"


async def test_crypto_roundtrip_and_tamper():
    crypto = NodeCrypto(PSK)
    token = crypto.encrypt(b"hello world")
    assert crypto.decrypt(token) == b"hello world"
    flipped = "A" if token[-1] != "A" else "B"
    with pytest.raises(CryptoError):
        crypto.decrypt(token[:-1] + flipped)
    with pytest.raises(CryptoError):
        NodeCrypto("other").decrypt(token)


async def test_crypto_sign_and_verify():
    crypto = NodeCrypto(PSK)
    data = b"nonce|n1|0.1|123"
    sig = crypto.sign(data)
    assert crypto.verify(data, sig) is True
    assert crypto.verify(data + b"x", sig) is False
    assert NodeCrypto("other").verify(data, sig) is False


async def _server_port(server):
    return server._server.sockets[0].getsockname()[1]


async def _node_responder(reader, writer, crypto, engine):
    """Drive a node link from a client-side module: auth, register, answer requests."""
    writer.write(encode_line(crypto, build_auth(crypto, "node-a", "0.1.0")))
    await writer.drain()
    assert (await read_message(crypto, reader))["type"] == "ok"
    writer.write(encode_line(crypto, build_register("node-a", "test-node", "0.1.0", engine.capabilities(), {"cpu_cores": 4, "ram_mb": 8192}, [])))
    await writer.drain()
    while True:
        msg = await read_message(crypto, reader)
        if msg is None:
            return
        if msg.get("type") == "heartbeat":
            continue
        if msg.get("type") == "request":
            try:
                data = engine.execute(msg.get("capability", ""), msg.get("action", "run"), msg.get("params", {}))
                writer.write(encode_line(crypto, build_response(msg.get("id"), True, data=data)))
            except Exception as exc:  # noqa: BLE001
                writer.write(encode_line(crypto, build_response(msg.get("id"), False, error=str(exc))))
            await writer.drain()


async def test_server_auth_register_remote_invoke():
    server = NodeServer(psk=PSK, host="127.0.0.1", port=0)
    registered = []

    async def on_register(msg):
        registered.append(msg)

    server.on_register = on_register
    await server.start()
    port = await _server_port(server)
    try:
        client_task = asyncio.create_task(
            _node_responder(*await asyncio.open_connection("127.0.0.1", port), NodeCrypto(PSK), NodeEngine())
        )
        await _wait_until(lambda: registered)
        assert registered[0]["node_id"] == "node-a"
        result = await server.invoke_remote("node-a", "system.ping", "_", {})
        assert result.get("success") is True
        assert result.get("data", {}).get("pong") is True
        client_task.cancel()
        try:
            await client_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
            pass
    finally:
        await server.stop()


async def test_invoke_offline_node_raises():
    server = NodeServer(psk=PSK, host="127.0.0.1", port=0)
    with pytest.raises(NodeOfflineError):
        await server.invoke_remote("missing-node", "system.ping", "_", {})


async def test_server_denies_bad_auth():
    server = NodeServer(psk=PSK, host="127.0.0.1", port=0)
    await server.start()
    port = await _server_port(server)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        bad = NodeCrypto("wrong-key")
        writer.write(encode_line(bad, build_auth(bad, "evil", "0.1.0")))
        await writer.drain()
        reply = await read_message(NodeCrypto(PSK), reader)
        assert reply.get("type") == "denied"
        writer.close()
    finally:
        await server.stop()


REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_dist(tmp: Path) -> Path:
    import runpy

    runpy.run_path(str(REPO_ROOT / "tools" / "make_node_dist.py"))
    dist = REPO_ROOT / "dist" / "eef-node-dist.zip"
    assert dist.exists()
    return dist


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    async def _poll():
        while not predicate():
            await asyncio.sleep(0.05)

    await asyncio.wait_for(_poll(), timeout)