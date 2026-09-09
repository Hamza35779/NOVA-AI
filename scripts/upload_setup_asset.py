"""Upload the fresh NOVA-AI-Setup-1.2.4.exe to the v1.2.4 GitHub release.

One-shot helper: reads the GitHub token via `git credential fill`, deletes
nothing (the old asset was already deleted), uploads the local file, and
prints the resulting asset metadata.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

REPO = "Hamza35779/NOVA-AI"
RELEASE_ID = "381810447"
ASSET_NAME = "NOVA-AI-Setup-1.2.4.exe"
LOCAL = Path(__file__).resolve().parents[1] / "dist" / ASSET_NAME


def get_token() -> str:
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("no GitHub credential found")


def main() -> None:
    token = get_token()
    size = LOCAL.stat().st_size
    url = (
        f"https://uploads.github.com/repos/{REPO}/releases/{RELEASE_ID}"
        f"/assets?name={ASSET_NAME}"
    )
    req = urllib.request.Request(
        url,
        data=LOCAL.read_bytes(),
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        asset = json.load(resp)
    print(f"uploaded: {asset['name']} {asset['size'] / 1e6:.1f} MB state: {asset['state']}")
    print(f"url: {asset['browser_download_url']}")


if __name__ == "__main__":
    main()
