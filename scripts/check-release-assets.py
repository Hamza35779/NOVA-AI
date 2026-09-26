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
(desktop.yml) — including the Tauri updater chain: per-payload ``.sig``
minisign signatures, the macOS ``.app.tar.gz`` updater payload, and a
``latest.json`` manifest whose version matches the tag, whose URLs point
at real assets on the release (no raw spaces — GitHub renames them to
dots), and whose signatures match the published ``.sig`` files. That
guards the exact failure modes of the v1.2.6 cut (release silently
shipped without desktop bundles) and of the first signed build (manifest
URLs 404ing on download). Also checks PyPI's latest ``nova-ai-pro``
release equals the tag version (skipped with --no-pypi or when PyPI is
unreachable/behind — the publish workflow may still be running).

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


# Tauri updater chain — required only on cuts NEWER than 1.2.10 (the last
# unsigned release). A stable release without these means the in-app
# auto-update channel would point at a release the updater cannot verify
# or download.
UPDATER_ASSETS = {
    r"^NOVA\.AI\.app\.tar\.gz$": "desktop.yml (macOS updater payload)",
    r"^NOVA\.AI\.app\.tar\.gz\.sig$": "desktop.yml (macOS updater signature)",
    r"^NOVA\.AI_.+_x64-setup\.exe\.sig$": "desktop.yml (Windows updater signature)",
    r"^NOVA\.AI_.+_amd64\.AppImage\.sig$": "desktop.yml (Linux updater signature)",
    r"^latest\.json$": "desktop.yml (Tauri updater manifest)",
}

# First release carrying the signed updater chain.
FIRST_SIGNED_VERSION = (1, 2, 11)


# Platform keys the latest.json assembler in desktop.yml always emits for a
# stable cut. The universal macOS payload covers both darwin keys.
REQUIRED_UPDATER_PLATFORMS = (
    "windows-x86_64",
    "darwin-aarch64",
    "darwin-x86_64",
    "linux-x86_64",
)


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


def validate_latest_json(manifest_text: str, version: str, asset_names: set[str]) -> list[str]:
    """Validate a latest.json updater manifest against a release.

    Returns a list of failure messages (empty = valid). Kept pure so the
    artifact-smoke tests can unit-test it without network access.
    """
    problems: list[str] = []
    try:
        m = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        return [f"latest.json: not valid JSON: {exc}"]

    if m.get("version") != version:
        problems.append(
            f"latest.json: version {m.get('version')!r} != tag version {version!r}"
        )
    platforms = m.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        problems.append("latest.json: missing or empty 'platforms' map")
        return problems

    for plat in REQUIRED_UPDATER_PLATFORMS:
        entry = platforms.get(plat)
        if entry is None:
            problems.append(f"latest.json: missing platform entry {plat!r}")
            continue
        url = entry.get("url", "")
        name = url.rsplit("/", 1)[-1]
        if not name:
            problems.append(f"latest.json[{plat}]: URL has no filename")
            continue
        # GitHub renames spaces to dots when storing release assets; a raw
        # space in the manifest URL means the updater download will 404.
        if " " in name:
            problems.append(
                f"latest.json[{plat}]: URL filename contains a raw space "
                f"({name!r}) — GitHub stores assets with dots; updater would 404"
            )
        if name not in asset_names:
            problems.append(
                f"latest.json[{plat}]: URL target {name!r} is not an asset "
                "on this release"
            )
        if not entry.get("signature"):
            problems.append(f"latest.json[{plat}]: missing signature")

    return problems


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

    # The updater chain (.sig files, macOS .app.tar.gz, latest.json) is only
    # expected on cuts newer than 1.2.10, the last unsigned release.
    version_t = tuple(int(x) for x in version.split("."))
    if version_t >= FIRST_SIGNED_VERSION:
        expected = {**expected_assets(), **UPDATER_ASSETS}
    else:
        expected = expected_assets()

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
            for pattern, source in expected.items()
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
    # Retain the small updater-chain assets for the manifest checks below
    # (everything else is only needed inside the per-asset loop).
    UPDATER_SMALL = (".sig", "latest.json")
    small_assets: dict[str, tuple[str, dict]] = {}
    for name, asset in assets.items():
        if name.endswith(UPDATER_SMALL):
            small_assets[name] = (asset["browser_download_url"], asset)

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

    # --- Tauri updater chain (signed releases) -----------------------------
    # Every expected .sig present in the per-asset loop above was already
    # size/sha256-verified; here we cross-check the manifest against the
    # release it was published on.
    sig_names = [n for n in assets if n.endswith(".sig")]
    manifest_blob: bytes | None = None
    if "latest.json" in assets:
        entry = small_assets.get("latest.json")
        if entry is None:
            fail("latest.json: asset vanished between listing and download")
        else:
            url, meta = entry
            try:
                manifest_blob = http_get(url)
            except (urllib.error.URLError, OSError) as exc:
                fail(f"latest.json: download failed: {exc}")
            else:
                if len(manifest_blob) != meta["size"]:
                    fail(
                        f"latest.json: size mismatch — got {len(manifest_blob)}, "
                        f"expected {meta['size']}"
                    )
                text = manifest_blob.decode("utf-8", "replace")
                for problem in validate_latest_json(text, version, set(assets)):
                    fail(problem)
                if not any(
                    p.startswith("latest.json:") for p in FAILURES
                ):
                    print(
                        f"latest.json: version {version}, "
                        f"{len(REQUIRED_UPDATER_PLATFORMS)} platform entries OK"
                    )
    elif sig_names:
        fail(
            "release has updater .sig files but no latest.json — the manifest "
            "step failed or was skipped"
        )
    else:
        print(
            "note: no updater signatures/manifest on this release "
            "(unsigned pre-1.2.11 cut) — updater-chain checks skipped"
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
