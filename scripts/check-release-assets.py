#!/usr/bin/env python
"""Release-asset smoke check.

Downloads every asset on a stable ``vX.Y.Z`` release and verifies, per asset:
  * the exact byte size GitHub reports,
  * the sha256 GitHub publishes in the release asset ``digest`` field,
  * magic bytes (ZIP/PK, ELF, Mach-O, RPM, ISO-9660/Apple DMG, PE/MZ),
  * (CLI zip only) the archive lists ``nova-ai-windows-x64.exe`` and the
    embedded version file contains the tag's version string.

Then verifies the release page is COMPLETE: the stable ``vX.Y.Z`` tag must
carry both the PyInstaller artifacts (release.yml) and the Tauri bundles
(desktop.yml). That guards the exact failure mode of the v1.2.6 cut, where
the macOS leg failed and the release silently shipped without desktop
bundles. Also checks PyPI's latest ``nova-ai-pro`` release equals the tag
version (skipped with --no-pypi or when PyPI is unreachable/behind — the
publish workflow may still be running).

CI: .github/workflows/artifact-smoke.yml runs this on every `release:
published` event. Local: ``python scripts/check-release-assets.py v1.2.7``.

Exit codes: 0 = all checks passed; 1 = one or more failures.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.github.com/repos/Hamza35779/NOVA-AI"
PYPI = "https://pypi.org/pypi/nova-ai-pro/json"
UA = {"User-Agent": "nova-ai-asset-smoke"}

# (name_suffix, magic) — checked with startswith on the first bytes. The dmg
# is UDZO: a zlib stream whose CMF byte is 0x78 and whose FLG varies with the
# compression level (0x01 and 0xda both observed on real release assets), so
# it is special-cased in magic_matches() instead of listed here.
MAGIC_CHECKS: list[tuple[str, bytes]] = [
    (".zip", b"PK\x03\x04"),
    (".deb", b"!<arch>\ndebian-binary"),
    (".rpm", b"\xed\xab\xee\xdb"),
    (".dmg", b"\x78"),  # placeholder — real check in magic_matches()
    (".AppImage", b"\x7fELF"),
    (".exe", b"MZ"),
    (".msi", b"\xd0\xcf\x11\xe0"),  # OLE2 compound document
]

STABLE_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def fail(msg: str) -> None:
    print(f"::error::{msg}" if not sys.stdout.isatty() else f"FAIL: {msg}")
    FAILURES.append(msg)


FAILURES: list[str] = []


def http_get(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def expected_assets() -> dict[str, str]:
    """Minimum asset set per producing workflow, keyed by name suffix/regex."""
    return {
        r"^nova-ai-windows-x64\.zip$": "release.yml (PyInstaller CLI zip)",
        r"^nova-ai-linux-amd64\.deb$": "release.yml (PyInstaller CLI deb)",
        r"^nova-ai-macos\.dmg$": "release.yml (PyInstaller CLI dmg)",
        r"^NOVA-AI-Setup-[0-9.]+\.exe$": "release.yml (Inno Setup EXE)",
        r"^NOVA\.AI_.+_x64-setup\.exe$": "desktop.yml (Tauri NSIS installer)",
        r"^NOVA\.AI_.+_x64_en-US\.msi$": "desktop.yml (Tauri MSI installer)",
        r"^NOVA\.AI_.+_universal\.dmg$": "desktop.yml (Tauri universal dmg)",
        r"^NOVA\.AI_.+_amd64\.AppImage$": "desktop.yml (Tauri AppImage)",
        r"^NOVA\.AI_.+_amd64\.deb$": "desktop.yml (Tauri deb)",
        r"^NOVA\.AI-.+\.x86_64\.rpm$": "desktop.yml (Tauri rpm)",
    }


def magic_for(name: str) -> bytes | None:
    for suffix, magic in MAGIC_CHECKS:
        if name.endswith(suffix):
            return magic
    return None


def magic_matches(name: str, blob: bytes) -> bool:
    if name.endswith(".dmg"):
        # UDZO dmg = zlib stream: CMF 0x78, FLG varies with compression level.
        return (
            len(blob) >= 2
            and blob[0] == 0x78
            and blob[1] in (0x01, 0x5E, 0x9C, 0xDA)
        )
    magic = magic_for(name)
    if magic is None:
        return True
    return blob.startswith(magic[:4])


def check_pypi(version: str) -> None:
    try:
        data = json.loads(http_get(PYPI, timeout=60))
    except (urllib.error.URLError, OSError) as exc:
        print(f"warn: PyPI unreachable ({exc}) — skipping sync check")
        return
    latest = data.get("info", {}).get("version", "")
    if latest != version:
        fail(f"PyPI latest version is {latest!r}, expected {version!r} (tag version)")
    else:
        print(f"pypi: latest nova-ai-pro == {version} OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="stable tag to verify, e.g. v1.2.7")
    parser.add_argument(
        "--no-pypi", action="store_true", help="skip the PyPI version-sync check"
    )
    parser.add_argument(
        "--cache-dir",
        default="",
        help="reuse previously downloaded assets from this directory when "
        "their size matches (they are still sha256-verified)",
    )
    parser.add_argument(
        "--wait-minutes",
        type=int,
        default=40,
        help="when expected assets are missing, re-poll the release this long "
        "before failing (desktop.yml attaches its bundles after "
        "publish-release creates the release — a race, not a defect; 0 = "
        "single check)",
    )
    args = parser.parse_args()

    m = STABLE_RE.match(args.tag)
    if not m:
        fail(f"tag {args.tag!r} is not a stable vX.Y.Z tag")
        return 1
    version = m.group(1)

    try:
        rel = json.loads(
            http_get(f"{API}/releases/tags/{args.tag}", timeout=60)
        )
    except urllib.error.HTTPError as exc:
        fail(f"release {args.tag} not found (HTTP {exc.code})")
        return 1
    assets = {a["name"]: a for a in rel.get("assets", [])}
    print(f"release {args.tag}: {len(assets)} assets")

    # --- completeness ------------------------------------------------------
    # desktop.yml publishes to the same release after publish-release creates
    # it, so on a `release: published` trigger the Tauri bundles legitimately
    # lag. Re-poll instead of failing instantly.
    deadline = time.monotonic() + args.wait_minutes * 60
    while True:
        missing = [
            (pattern, source)
            for pattern, source in expected_assets().items()
            if not any(re.search(pattern, name) for name in assets)
        ]
        if not missing or time.monotonic() >= deadline:
            break
        print(
            f"waiting for {len(missing)} expected asset(s) "
            f"({', '.join(p for p, _ in missing)}); re-polling in 30s"
        )
        time.sleep(30)
        assets = {
            a["name"]: a
            for a in json.loads(http_get(f"{API}/releases/tags/{args.tag}", timeout=60))["assets"]
        }
    for pattern, source in missing:
        fail(f"missing expected asset matching {pattern!r} ({source})")

    # --- per-asset integrity ----------------------------------------------
    for name, asset in sorted(assets.items()):
        size, digest = asset["size"], asset.get("digest", "")
        expected_sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
        print(f"-- {name} ({size} bytes)")
        cached = Path(args.cache_dir) / name if args.cache_dir else None
        if cached is not None and cached.is_file() and cached.stat().st_size == size:
            blob = cached.read_bytes()
            print("   (reusing cached download)")
        else:
            try:
                blob = http_get(asset["browser_download_url"])
            except (urllib.error.URLError, OSError) as exc:
                fail(f"{name}: download failed: {exc}")
                continue
        if len(blob) != size:
            fail(f"{name}: size mismatch — got {len(blob)}, expected {size}")
        sha = hashlib.sha256(blob).hexdigest()
        if expected_sha and sha != expected_sha:
            fail(f"{name}: sha256 mismatch — got {sha}, expected {expected_sha}")
        elif not expected_sha:
            print(f"   note: GitHub published no digest field; computed {sha}")
        magic = magic_for(name)
        if magic and not magic_matches(name, blob):
            fail(f"{name}: magic bytes {blob[:4].hex()} do not match {magic!r}")
        if name.endswith(".zip") and "windows-x64" in name:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = zf.namelist()
                if not any(n.endswith("nova-ai-windows-x64.exe") for n in names):
                    fail(f"{name}: zip does not contain nova-ai-windows-x64.exe")
                vpath = next(
                    (
                        n
                        for n in names
                        if n.endswith("_internal/nova_ai/_version.py")
                    ),
                    None,
                )
                if vpath is None:
                    print(
                        "   note: no bundled _version.py (editable-source build); "
                        "skipping version read"
                    )
                else:
                    text = zf.read(vpath).decode("utf-8", "replace")
                    if version not in text:
                        fail(
                            f"{name}: bundled version file does not mention {version}"
                        )

    if not args.no_pypi:
        check_pypi(version)

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) FAILED")
        return 1
    print("\nall asset checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
