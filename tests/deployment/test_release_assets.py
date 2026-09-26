"""Unit tests for the latest.json updater-manifest validation in
scripts/check-release-assets.py (no network access)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-release-assets.py"

spec = importlib.util.spec_from_file_location("check_release_assets", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules.setdefault("check_release_assets", mod)
spec.loader.exec_module(mod)

validate = mod.validate_latest_json

SIG = "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZQ=="


def manifest(version="1.2.11", platforms=None, **overrides):
    base = {
        "version": version,
        "notes": f"NOVA AI Desktop {version}",
        "pub_date": "2026-09-27T00:00:00Z",
        "platforms": platforms if platforms is not None else {
            "windows-x86_64": {"signature": SIG, "url": "https://x/NOVA.AI_1.2.11_x64-setup.exe"},
            "darwin-aarch64": {"signature": SIG, "url": "https://x/NOVA.AI.app.tar.gz"},
            "darwin-x86_64": {"signature": SIG, "url": "https://x/NOVA.AI.app.tar.gz"},
            "linux-x86_64": {"signature": SIG, "url": "https://x/NOVA.AI_1.2.11_amd64.AppImage"},
        },
    }
    base.update(overrides)
    return base


ASSETS = {
    "NOVA.AI_1.2.11_x64-setup.exe",
    "NOVA.AI_1.2.11_x64-setup.exe.sig",
    "NOVA.AI.app.tar.gz",
    "NOVA.AI.app.tar.gz.sig",
    "NOVA.AI_1.2.11_amd64.AppImage",
    "NOVA.AI_1.2.11_amd64.AppImage.sig",
    "NOVA.AI_1.2.11_x64_en-US.msi",
    "NOVA.AI_1.2.11_universal.dmg",
    "latest.json",
}


class TestValidManifest:
    def test_complete_manifest_passes(self):
        assert validate(json.dumps(manifest()), "1.2.11", ASSETS) == []

    def test_version_must_match_tag(self):
        problems = validate(json.dumps(manifest(version="1.2.10")), "1.2.11", ASSETS)
        assert any("version" in p for p in problems)


class TestPlatforms:
    def test_missing_platform_fails(self):
        m = manifest()
        del m["platforms"]["linux-x86_64"]
        problems = validate(json.dumps(m), "1.2.11", ASSETS)
        assert any("linux-x86_64" in p for p in problems)

    def test_empty_platforms_fails(self):
        problems = validate(json.dumps(manifest(platforms={})), "1.2.11", ASSETS)
        assert any("platforms" in p for p in problems)

    def test_missing_signature_fails(self):
        m = manifest()
        m["platforms"]["windows-x86_64"]["signature"] = ""
        problems = validate(json.dumps(m), "1.2.11", ASSETS)
        assert any("signature" in p for p in problems)

    def test_url_space_fails(self):
        m = manifest()
        m["platforms"]["windows-x86_64"]["url"] = (
            "https://x/NOVA AI_1.2.11_x64-setup.exe"
        )
        problems = validate(json.dumps(m), "1.2.11", ASSETS)
        assert any("space" in p for p in problems)

    def test_url_target_not_on_release_fails(self):
        m = manifest()
        m["platforms"]["linux-x86_64"]["url"] = (
            "https://x/NOVA.AI_9.9.9_amd64.AppImage"
        )
        problems = validate(json.dumps(m), "1.2.11", ASSETS)
        assert any("not an asset" in p for p in problems)

    def test_invalid_json_reported(self):
        problems = validate("{not json", "1.2.11", ASSETS)
        assert len(problems) == 1
        assert "not valid JSON" in problems[0]


class TestVersionGate:
    def test_updater_assets_required_from_1_2_11(self):
        assert mod.FIRST_SIGNED_VERSION == (1, 2, 11)
        import re
        # UPDATER_ASSETS keys are regexes; each expected artifact name must
        # be matched by exactly one of them.
        for name in (
            "NOVA.AI.app.tar.gz",
            "NOVA.AI.app.tar.gz.sig",
            "NOVA.AI_1.2.11_x64-setup.exe.sig",
            "NOVA.AI_1.2.11_amd64.AppImage.sig",
            "latest.json",
        ):
            assert any(
                re.search(p, name) for p in mod.UPDATER_ASSETS
            ), f"no updater pattern matches {name!r}"

    def test_pre_signed_releases_skip_updater_expectations(self):
        # v1.2.10 must remain smokeable without the updater chain.
        expected = mod.expected_assets()
        assert "latest.json" not in expected
        assert not any(".sig" in p for p in expected)
