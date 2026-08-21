"""eefn — the EEF node system.

Everything "node": the wire protocol + crypto, the node engine (capabilities a
PC node offers), the long-running node client, and the coordinator-side node
server (TCP gateway). This package is the single source of truth; the flat,
standalone `node/` bundle is generated from it by `tools/emit_node.py`.

The coordinator (eef) imports `eefn.server.NodeServer`; fresh machines run the
flat node bundle (stdlib + cryptography only).
"""

from eefn.crypto import CryptoError, NodeCrypto, derive_key
from eefn.engine import CAPABILITIES, NodeEngine
from eefn.protocol import (
    PROTOCOL_VERSION,
    build_auth,
    build_heartbeat,
    build_register,
    build_response,
    encode_line,
    now_ms,
    read_message,
)
from eefn.server import DEFAULT_PORT, NodeOfflineError, NodeServer

__version__ = "0.1.0"

__all__ = [
    "CryptoError",
    "NodeCrypto",
    "derive_key",
    "CAPABILITIES",
    "NodeEngine",
    "PROTOCOL_VERSION",
    "build_auth",
    "build_heartbeat",
    "build_register",
    "build_response",
    "encode_line",
    "now_ms",
    "read_message",
    "DEFAULT_PORT",
    "NodeOfflineError",
    "NodeServer",
    "NodeClient",
]

# Avoid a circular import at module top by importing client after the rest.
from eefn.client import NodeClient  # noqa: E402
