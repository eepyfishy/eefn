"""Tests for the flat node bundle: emit sync, dist contents, and an end-to-end join.

The flat `node/` bundle (generated from the eefn package) is what actually runs on a
fresh machine. These tests prove the bundle is in sync, zips correctly, and that a
bundle-extracted node can authenticate + answer a request against a live NodeServer.
"""

import asyncio
import subprocess
import sys
import zipfile
from pathlib import Path

from eefn.server import NodeServer

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_emit_sync():
    """node/ must match what tools/emit_node.py would generate."""
    subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "emit_node.py"), "--check"], check=True)


async def test_flat_bundle_joins_server(tmp_path):
    import runpy

    runpy.run_path(str(REPO_ROOT / "tools" / "make_node_dist.py"))

    # extract the dist zip into a fresh install dir (simulates the bootstrap)
    install = tmp_path / "installed"
    install.mkdir()
    with zipfile.ZipFile(REPO_ROOT / "dist" / "eef-node-dist.zip") as z:
        z.extractall(install)
    files = {p.name for p in install.iterdir()}
    assert {"node_crypto.py", "node_protocol.py", "node_engine.py", "node_client.py", "run_node.py", "start.cmd"} <= files

    # run a NodeServer and have the extracted flat node connect + answer a request
    server = NodeServer(psk="s", host="127.0.0.1", port=0)
    await server.start()
    port = server.port

    # load the flat bundle via a dotted import path
    sys.path.insert(0, str(install))
    try:
        import node_client
        import node_engine

        client = node_client.NodeClient([f"127.0.0.1:{port}"], "node-flat", "flat", "s", node_engine.NodeEngine())
        run_task = asyncio.create_task(client.run())
        try:
            for _ in range(150):
                if "node-flat" in server.connected_nodes():
                    break
                await asyncio.sleep(0.05)
            assert "node-flat" in server.connected_nodes(), "flat node did not register"
            res = await server.invoke_remote("node-flat", "system.ping", "_", {})
            assert res.get("success") is True and res["data"]["pong"] is True
        finally:
            run_task.cancel()
            try:
                await run_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
                pass
    finally:
        await server.stop()
        sys.path.remove(str(install))


async def test_bootstrap_extracts_and_writes_config(tmp_path):
    """Run bootstrap_eef.py with a file:// pkg into a temp dir; check result."""
    import runpy

    runpy.run_path(str(REPO_ROOT / "tools" / "make_node_dist.py"))
    dist = REPO_ROOT / "dist" / "eef-node-dist.zip"
    pkg_url = dist.resolve().as_uri()  # file:///...

    install = tmp_path / "c-eefn"
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "bootstrap_eef.py"),
            "--pkg", pkg_url,
            "--dir", str(install),
            "--psk", "test-psk",
            "--coordinator", "26.234.244.3:8081",
            "--playit", "node.eeftuna.playit.plus",
            "--name", "provision-test",
            "--id", "node-test",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (install / "run_node.py").exists()
    cfg = __import__("json").loads((install / "config.json").read_text(encoding="utf-8"))
    assert cfg["psk"] == "test-psk"
    assert cfg["node_id"] == "node-test"
    assert cfg["endpoints"] == ["26.234.244.3:8081", "node.eeftuna.playit.plus"]