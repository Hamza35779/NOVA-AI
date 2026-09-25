#!/usr/bin/env python
"""Docs must only reference installer assets that actually ship.

Every concrete installer filename mentioned in current-claim docs is checked
against the assets of the release matching the repo's version
(frontend/package.json -> v<PKG>). Guards the drift where docs advertise a
``NOVA-AI-Setup-<version>.exe`` that no workflow produces (exactly what
happened: the Inno asset was last built by hand for 1.2.4 while docs kept
advertising it through 1.2.5/1.2.6/1.2.7).

Rules:
  * concrete ``NOVA.AI_<version>_…`` / ``NOVA.AI-<version>-…`` names must
    carry the current PKG version (stale concrete names fail),
  * every referenced asset (including the versionless
    ``nova-ai-windows-x64.zip``) must exist on the v<PKG> release,
  * the phantom ``NOVA-AI-Setup-<version>.exe`` name must not appear in
    current-claim docs at all (it is only legitimate in historical context
    — CHANGELOG, roadmap, the Inno project itself, deploy/windows/README.md).

If the v<PKG> release has not been cut yet (404) the check warns and passes
— a version-bump commit lands before its tag by design.

Usage: ``python scripts/check-doc-assets.py`` (override with --tag vX.Y.Z).
Exit codes: 0 = ok (or release pending); 1 = doc drift detected.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "nova-ai-doc-asset-check"}

# Docs whose installer references must match reality. (Historical narrative
# lives in CHANGELOG.md / docs/development/roadmap.md and is exempt.)
SCAN_FILES = [
    "README.md",
    "SETUP_AND_USAGE_GUIDE.md",
    "deploy/README.md",
    "docs/downloads.md",
    "docs/getting-started/installation.md",
    "docs/getting-started/windows-native.md",
]

# Concrete, versioned asset names a doc may reference, with capture of the
# version token. RPM keeps its "1.2.7-1" package-release suffix.
CONCRETE_PATTERNS = [
    re.compile(r"NOVA\.AI_([0-9]+\.[0-9]+\.[0-9]+)_x64-setup\.exe"),
    re.compile(r"NOVA\.AI_([0-9]+\.[0-9]+\.[0-9]+)_x64_en-US\.msi"),
    re.compile(r"NOVA\.AI_([0-9]+\.[0-9]+\.[0-9]+)_universal\.dmg"),
    re.compile(r"NOVA\.AI_([0-9]+\.[0-9]+\.[0-9]+)_amd64\.AppImage"),
    re.compile(r"NOVA\.AI_([0-9]+\.[0-9]+\.[0-9]+)_amd64\.deb"),
    re.compile(r"NOVA\.AI-([0-9]+\.[0-9]+\.[0-9]+)-[0-9]+\.x86_64\.rpm"),
]

# References to a specific asset name (versionless ones included).
ASSET_NAME_PATTERNS = [
    re.compile(r"NOVA\.AI_[0-9.]+_x64-setup\.exe"),
    re.compile(r"NOVA\.AI_[0-9.]+_x64_en-US\.msi"),
    re.compile(r"NOVA\.AI_[0-9.]+_universal\.dmg"),
    re.compile(r"NOVA\.AI_[0-9.]+_amd64\.AppImage"),
    re.compile(r"NOVA\.AI_[0-9.]+_amd64\.deb"),
    re.compile(r"NOVA\.AI-[0-9.-]+\.x86_64\.rpm"),
    re.compile(r"nova-ai-windows-x64\.zip"),
]

# The Inno-produced installer name that CI does not build (yet). Any concrete
# mention outside the exempt historical files is doc drift.
PHANTOM_PATTERN = re.compile(r"NOVA-AI-Setup-[0-9.]+\.exe")
PHANTOM_EXEMPT = {
    "deploy/windows/nova-ai-setup.iss",
    "deploy/windows/README.md",
    "CHANGELOG.md",
    "docs/development/roadmap.md",
}


def frontend_version() -> str:
    text = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    m = re.search(r'"version":\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("cannot read version from frontend/package.json")
    return m.group(1)


def release_assets(tag: str) -> set[str] | None:
    url = f"https://api.github.com/repos/Hamza35779/NOVA-AI/releases/tags/{tag}"
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return {a["name"] for a in data.get("assets", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default="",
        help="release tag to verify against (default: v<PKG from package.json>)",
    )
    args = parser.parse_args()

    pkg = frontend_version()
    tag = args.tag or f"v{pkg}"
    failures: list[str] = []

    referenced: set[str] = set()
    for rel in SCAN_FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in CONCRETE_PATTERNS:
            for version in pattern.findall(text):
                if version != pkg:
                    failures.append(
                        f"{rel}: references {pattern.pattern} built from version "
                        f"{version}, but the repo version is {pkg} — bump docs "
                        f"together with frontend/package.json"
                    )
        for pattern in ASSET_NAME_PATTERNS:
            referenced.update(pattern.findall(text))
        rel_key = rel.replace("\\", "/")
        if rel_key not in PHANTOM_EXEMPT:
            for hit in PHANTOM_PATTERN.findall(text):
                failures.append(
                    f"{rel}: references {hit}, an Inno-built installer that no "
                    f"CI workflow produces — use NOVA.AI_{pkg}_x64-setup.exe "
                    f"(desktop app) or nova-ai-windows-x64.zip (backend)"
                )

    print(f"repo version: {pkg}; checking docs against release {tag}")
    try:
        assets = release_assets(tag)
    except urllib.error.URLError as exc:
        print(f"warn: GitHub API unreachable ({exc}); skipping asset existence check")
        assets = None

    if assets is None:
        print(f"warn: release {tag} not published yet — skipping existence check")
    else:
        print(f"release {tag}: {len(assets)} assets")
        for name in sorted(referenced):
            if name not in assets:
                failures.append(
                    f"docs reference asset {name!r} which is not published on "
                    f"release {tag} (assets: {', '.join(sorted(assets))})"
                )
        if referenced and not failures:
            print(f"all {len(referenced)} referenced installer assets exist on {tag}")

    if failures:
        for f in failures:
            print(f"::error::{f}" if not sys.stdout.isatty() else f"FAIL: {f}")
        print(f"\n{len(failures)} doc-asset problem(s)")
        return 1
    print("doc-asset check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
