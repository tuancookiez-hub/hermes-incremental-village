"""Pin the engine builds of a release into village/engine-release.json.

Run this after the "Build engine" workflow finishes for a tag. It refuses any file whose GitHub build
attestation does not check out against this repository, so only what CI built can be pinned.

    python scripts/pin_engine.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "village" / "engine-release.json"
WORKFLOW = ".github/workflows/engine.yml"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    version, repo = pin["version"], pin["repo"]
    assets = {}
    with tempfile.TemporaryDirectory() as tmp:
        run("gh", "release", "download", f"v{version}", "--repo", repo, "--dir", tmp, "--pattern", "hermes-village-engine-*")
        for path in sorted(Path(tmp).iterdir()):
            run("gh", "attestation", "verify", str(path), "--repo", repo, "--signer-workflow", f"{repo}/{WORKFLOW}")
            key = path.stem if path.suffix == ".exe" else path.name
            key = key.removeprefix(f"hermes-village-engine-{version}-")
            data = path.read_bytes()
            assets[key] = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if not assets:
        raise SystemExit(f"no engine files found on release v{version}")
    PIN.write_text(json.dumps({**pin, "assets": assets}, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"pinned {len(assets)} builds of {version}: {', '.join(sorted(assets))}")


if __name__ == "__main__":
    main()
