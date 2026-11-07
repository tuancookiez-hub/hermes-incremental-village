"""The engine download: what is pinned is what gets used, and nothing else."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from village import bridge, fetch  # noqa: E402

VERSION = "9.9.9"
BODY = b"pretend this is an engine"


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """Pin one fake build for this computer and keep downloads inside the test's folder."""
    monkeypatch.setattr(fetch, "platform_key", lambda: "testos-testarch")
    monkeypatch.setattr(fetch, "engine_dir", lambda: tmp_path / "engine")

    def pin(body=BODY, size=None, version=VERSION):
        path = tmp_path / "pin.json"
        path.write_text(json.dumps({"version": version, "repo": "owner/repo", "assets": {"testos-testarch": {
            "file": "engine-file", "sha256": hashlib.sha256(body).hexdigest(), "size": len(body) if size is None else size}}}))
        monkeypatch.setattr(fetch, "PIN_PATH", path)
    pin()
    return pin


def serve(body):
    urls = []

    def opener(url):
        urls.append(url)
        return io.BytesIO(body)
    opener.urls = urls
    return opener


def test_a_matching_download_is_put_in_place(pinned):
    opener = serve(BODY)
    path = fetch.install(VERSION, opener)
    assert path.read_bytes() == BODY and path.parent.name == VERSION
    assert opener.urls == ["https://github.com/owner/repo/releases/download/v9.9.9/engine-file"]
    assert fetch.status(VERSION)["installed"] is True
    assert not list(path.parent.glob("*.part"))
    if os.name != "nt":
        assert os.access(path, os.X_OK)


def test_a_file_that_does_not_match_its_pin_is_never_kept(pinned, tmp_path):
    with pytest.raises(fetch.FetchError, match="checksum"):
        fetch.install(VERSION, serve(b"something else entirely!!"))
    assert fetch.status(VERSION)["installed"] is False
    assert not (tmp_path / "engine").exists()


def test_a_download_larger_than_pinned_is_refused(pinned):
    with pytest.raises(fetch.FetchError, match="larger"):
        fetch.install(VERSION, serve(BODY + b"extra"))


def test_no_pin_for_this_version_means_no_download(pinned):
    opener = serve(BODY)
    with pytest.raises(fetch.FetchError, match="cargo install"):
        fetch.install("1.2.3", opener)
    assert opener.urls == [] and fetch.status("1.2.3")["available"] is False


def test_no_pin_for_this_computer_means_no_download(pinned, monkeypatch):
    monkeypatch.setattr(fetch, "platform_key", lambda: "beos-m68k")
    opener = serve(BODY)
    with pytest.raises(fetch.FetchError, match="beos-m68k"):
        fetch.install(VERSION, opener)
    assert opener.urls == []


def test_a_failed_connection_says_so(pinned):
    def down(url):
        raise OSError("no route")
    with pytest.raises(fetch.FetchError, match="no route"):
        fetch.install(VERSION, down)


def test_the_downloaded_engine_is_used_and_an_old_one_never_is(pinned, monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_VILLAGE_ENGINE", raising=False)
    monkeypatch.setattr(bridge, "PLUGIN_ROOT", tmp_path)
    monkeypatch.setattr(bridge, "ENGINE_VERSION", VERSION)
    path = fetch.install(VERSION, serve(BODY))
    assert bridge.find_binary() == str(path)
    monkeypatch.setattr(bridge, "ENGINE_VERSION", "9.9.10")
    assert bridge.find_binary() != str(path)


def test_the_shipped_pin_is_for_this_version():
    pin = json.loads(fetch.PIN_PATH.read_text(encoding="utf-8"))
    assert pin["version"] == bridge.ENGINE_VERSION
    assert pin["repo"].count("/") == 1
    for asset in pin["assets"].values():
        assert len(asset["sha256"]) == 64 and 0 < asset["size"] <= fetch.MAX_BYTES


def test_every_platform_name_is_one_the_build_produces():
    workflow = (Path(__file__).resolve().parent.parent / ".github/workflows/engine.yml").read_text(encoding="utf-8")
    for system in fetch._OS.values():
        for arch in set(fetch._ARCH.values()):
            if (system, arch) != ("windows", "aarch64"):
                assert f"name: {system}-{arch}," in workflow
