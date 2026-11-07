"""Getting the rules engine without installing Rust.

GitHub Actions builds the engine from this repository's source and attests each build. The checksums
of those exact files are pinned in engine-release.json, and this module fetches the one for this
computer when the player asks for it, from the /village setup command or the button on the page.
Nothing here runs by itself, and a file that does not match its pin is thrown away unused.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

PIN_PATH = Path(__file__).with_name("engine-release.json")
MAX_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 60
_OS = {"win32": "windows", "darwin": "macos", "linux": "linux"}
_ARCH = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


class FetchError(RuntimeError):
    """A download that was refused or failed. The message is written for the player."""


def platform_key() -> str | None:
    system, arch = _OS.get(sys.platform), _ARCH.get(platform.machine().lower())
    return f"{system}-{arch}" if system and arch else None


def engine_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir  # public Hermes plugin storage helper
    return plugin_data_dir("hermes-village") / "engine"


def installed_path(version: str) -> Path | None:
    """Where this version's engine is kept. Each version has its own folder, so an old one is never run."""
    try:
        return engine_dir() / version / ("hermes-village-engine.exe" if os.name == "nt" else "hermes-village-engine")
    except ImportError:  # outside Hermes there is no plugin storage
        return None


def _pin(version: str) -> dict[str, Any] | None:
    """The pinned file for this computer, or None when no build is pinned for it."""
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if pin.get("version") != version:
        return None
    asset = pin.get("assets", {}).get(platform_key() or "")
    return None if not asset else {**asset, "url": f"https://github.com/{pin['repo']}/releases/download/v{version}/{asset['file']}"}


def status(version: str) -> dict[str, Any]:
    asset, path = _pin(version), installed_path(version)
    return {"version": version, "platform": platform_key(), "available": asset is not None,
            "installed": bool(path and path.is_file()), "size": asset["size"] if asset else None,
            "url": asset["url"] if asset else None}


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-village"})
    return urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS)


def _read(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise FetchError("The engine download is larger than it should be, so it was not used.")
    return data


def install(version: str, opener: Callable[[str], Any] = _open) -> Path:
    """Download this version's engine, check it against its pin, and only then put it in place."""
    asset, path = _pin(version), installed_path(version)
    if asset is None:
        raise FetchError(f"No engine build is published for this computer ({platform_key() or 'unknown'}) "
                         f"and version {version}. Build it with `cargo install --path engine-rs --locked`.")
    if path is None:
        raise FetchError("Plugin storage is not available here.")
    try:
        with opener(asset["url"]) as response:
            data = _read(response, min(MAX_BYTES, int(asset["size"])))
    except FetchError:
        raise
    except OSError as exc:
        raise FetchError(f"The engine could not be downloaded ({exc}). Check your connection and try again.") from exc
    if hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise FetchError("The downloaded engine does not match the checksum pinned in this plugin, so it was not used.")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.chmod(0o755)
    os.replace(part, path)
    return path
