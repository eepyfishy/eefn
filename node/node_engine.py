"""Node-side capability execution.

Self-contained (stdlib + a little urllib for Ollama) so a node runs with nothing
but Python and `cryptography`. A node contributes: system.ping, filesystem,
launch_application, and model inference (llm.infer / vlm.analyze) against its
local Ollama.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from urllib.request import Request, urlopen
except Exception:  # pragma: no cover
    Request = urlopen = None  # type: ignore

OLLAMA_URL = os.environ.get("EEF_NODE_OLLAMA", "http://localhost:11434")

CAPABILITIES = ["system.ping", "filesystem", "launch_application", "llm.infer", "vlm.analyze"]


class NodeEngine:
    """Executes capabilities a PC node offers."""

    def __init__(self, allow_write: bool = False, allowed_roots: Optional[List[str]] = None) -> None:
        self.allow_write = allow_write
        self.allowed_roots = [Path(r).resolve() for r in allowed_roots] if allowed_roots else None

    def capabilities(self) -> List[str]:
        return list(CAPABILITIES)

    def execute(self, capability: str, action: str, params: Dict[str, Any]) -> Any:
        if capability == "system.ping":
            return self._ping()
        if capability == "filesystem":
            return self._filesystem(action, params)
        if capability == "launch_application":
            return self._launch(action, params)
        if capability in ("llm.infer", "vlm.analyze"):
            return self._ollama(capability, params)
        raise ValueError(f"unknown capability '{capability}'")

    # -- system -----------------------------------------------------------
    @staticmethod
    def _ping() -> dict:
        return {"pong": True, "time": time.time(), "python": sys.version.split()[0]}

    # -- filesystem -------------------------------------------------------
    def _resolve(self, raw: str) -> Path:
        p = Path(raw).expanduser().resolve()
        if self.allowed_roots and not any(
            p == root or root in p.parents for root in self.allowed_roots
        ):
            raise PermissionError(f"path '{p}' outside allowed roots")
        return p

    def _filesystem(self, action: str, params: Dict[str, Any]) -> Any:
        raw = str(params.get("path", ""))
        if not raw:
            raise ValueError("filesystem requires 'path'")
        p = self._resolve(raw)
        if action == "read":
            if not p.exists():
                raise FileNotFoundError(str(p))
            return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")}
        if action == "list":
            if not p.exists():
                raise FileNotFoundError(str(p))
            return {"path": str(p), "entries": [str(e) for e in p.iterdir()]}
        if action == "write":
            if not self.allow_write:
                raise PermissionError("filesystem.write is not enabled on this node")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(params.get("content", "")), encoding="utf-8")
            return {"path": str(p), "written": True}
        raise ValueError(f"unknown filesystem action '{action}'")

    # -- launch apps ------------------------------------------------------
    def _launch(self, action: str, params: Dict[str, Any]) -> Any:
        name = str(params.get("name", ""))
        if action == "launch":
            if not name:
                raise ValueError("launch requires 'name'")
            argv = [name, *[str(a) for a in params.get("args", [])]]
            subprocess.Popen(argv, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"launched": name}
        raise ValueError(f"unknown launch action '{action}'")

    # -- model inference (local Ollama) -----------------------------------
    def _ollama(self, capability: str, params: Dict[str, Any]) -> Any:
        if Request is None:
            raise RuntimeError("urllib unavailable")
        messages = params.get("messages") or [
            {"role": "user", "content": params.get("prompt", "")}
        ]
        images = params.get("images")
        model = params.get("model")
        if not model:
            model = "qwen3-vl:latest" if capability == "vlm.analyze" else "gemma4:latest"
        if images and messages and messages[-1].get("role") == "user":
            messages[-1]["images"] = images
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": float(params.get("temperature", 0.7)),
                "num_predict": int(params.get("max_tokens", 1024)),
            },
        }
        req = Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=int(params.get("timeout", 60))) as resp:  # noqa: S310 - local Ollama
            result = json.loads(resp.read().decode("utf-8"))
        return {"content": result.get("message", {}).get("content", "")}