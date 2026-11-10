"""Talks to the Rust rules engine (engine-rs) over a pipe.

One ``hermes-village-engine`` process per Python process. Requests and responses are one JSON
object per line. The binary is never started at import time: the first call that needs it starts
it, checks that it was built from this ``rules.json``, and keeps it for the life of the process.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any


PROTOCOL = 2
ENGINE_VERSION = "0.12.0"  # must match engine-rs/Cargo.toml and plugin.yaml
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = Path(__file__).resolve().with_name("rules.json")
_EXE = "hermes-village-engine.exe" if os.name == "nt" else "hermes-village-engine"
_REBUILD = "run `cargo install --path engine-rs --locked` in the Hermes Incremental Village plugin folder"


class EngineUnavailable(RuntimeError):
    """The Rust engine is missing, stale, or would not start."""


class EngineError(RuntimeError):
    """The engine understood the request and refused it (or hit a bug while running it)."""


def rules_sha256() -> str:
    return hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()


def find_binary() -> str | None:
    """HERMES_VILLAGE_ENGINE, a development build next to the plugin, cargo's bin folder, then PATH."""
    named = os.environ.get("HERMES_VILLAGE_ENGINE")
    if named and Path(named).is_file():
        return named
    built = PLUGIN_ROOT / "engine-rs" / "target" / "release" / _EXE
    if built.is_file():
        return str(built)
    installed = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo") / "bin" / _EXE
    if installed.is_file():
        return str(installed)
    return shutil.which("hermes-village-engine")


class _Bridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._pid = os.getpid()
        self._next_id = 0

    # -- process management

    def _start(self) -> subprocess.Popen:
        binary = find_binary()
        if binary is None:
            raise EngineUnavailable(
                "The village engine is not installed: " + _REBUILD + ", or point HERMES_VILLAGE_ENGINE at the binary.")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                [binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                shell=False, close_fds=True, creationflags=flags)
        except OSError as exc:
            raise EngineUnavailable(f"The village engine at {binary} would not start ({exc}); " + _REBUILD + ".") from exc
        try:
            hello = self._exchange(proc, {"id": 0, "op": "hello"})
        except EngineUnavailable:
            self._kill(proc)
            raise
        info = hello.get("result") or {}
        if (info.get("protocol"), info.get("version"), info.get("rules_sha256")) != (PROTOCOL, ENGINE_VERSION, rules_sha256()):
            self._kill(proc)
            raise EngineUnavailable(
                f"The village engine at {binary} is out of date for this plugin (its version, rules or protocol differ); "
                + _REBUILD + ".")
        return proc

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        for pipe in (proc.stdin, proc.stdout):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001 - best effort on the way out
            pass

    @staticmethod
    def _exchange(proc: subprocess.Popen, req: dict) -> dict:
        line = json.dumps(req, separators=(",", ":")) + "\n"
        try:
            proc.stdin.write(line.encode("utf-8"))
            proc.stdin.flush()
            raw = proc.stdout.readline()
        except (OSError, ValueError) as exc:
            raise EngineUnavailable("The village engine stopped answering.") from exc
        if not raw:
            raise EngineUnavailable("The village engine exited.")
        return json.loads(raw.decode("utf-8"))

    def close(self) -> None:
        with self._lock:
            if self._proc is not None and self._pid == os.getpid():
                self._kill(self._proc)
            self._proc = None

    # -- requests

    def call(self, op: str, world: dict | None = None, args: dict | None = None) -> dict:
        with self._lock:
            if self._pid != os.getpid():  # forked: the child must not share the parent's pipe
                self._proc, self._pid = None, os.getpid()
            self._next_id += 1
            req: dict[str, Any] = {"id": self._next_id, "op": op}
            if world is not None:
                req["world"] = world
            if args is not None:
                req["args"] = args
            last: EngineUnavailable | None = None
            for _ in range(2):  # a dead process is restarted once
                if self._proc is None or self._proc.poll() is not None:
                    self._proc = self._start()
                try:
                    resp = self._exchange(self._proc, req)
                except EngineUnavailable as exc:
                    last = exc
                    self._kill(self._proc)
                    self._proc = None
                    continue
                if not resp.get("ok"):
                    raise EngineError(resp.get("error") or "the village engine refused the request")
                return resp
            raise EngineUnavailable(f"The village engine keeps stopping ({last}); " + _REBUILD + ".")


_bridge = _Bridge()
atexit.register(_bridge.close)


def call(op: str, world: dict | None = None, args: dict | None = None) -> dict:
    return _bridge.call(op, world, args)


def close() -> None:
    _bridge.close()
