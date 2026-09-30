"""Tests for the /v1/skills API routes.

Covers the A2 audit item: the skills endpoints must be backed by the real
skill system (SkillManager discovery + SkillImporter installs + filesystem
removal) instead of returning ``{"status": "not_implemented"}`` stubs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import nova_ai.server.api_routes as routes  # noqa: E402

SKILL_TOML = """\
[skill]
name = "greet-fixture"
version = "0.1.0"
description = "Fixture skill used by the skills API tests"
author = "tests"

[[skill.steps]]
tool_name = "think"
arguments_template = '{"thought": "greet {name}"}'
output_key = "greeting"
"""


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient with the skill roots isolated to a temp NOVA_AI_HOME.

    Also chdirs into the temp dir so the ``./skills`` workspace scan root
    cannot pick up anything from the repo or the user's checkout.
    """
    monkeypatch.setenv("NOVA_AI_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    app = FastAPI()
    app.include_router(routes.skills_router)
    return TestClient(app)


@pytest.fixture()
def install_fixture_skill(client):
    """Write a valid skill directory under <NOVA_AI_HOME>/skills/."""

    def _install(name: str = "greet-fixture") -> Path:
        from nova_ai.core.paths import get_config_dir

        skill_dir = get_config_dir() / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "skill.toml").write_text(SKILL_TOML, encoding="utf-8")
        return skill_dir

    return _install


class TestListSkills:
    def test_empty_when_nothing_installed(self, client):
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        assert resp.json() == {"skills": []}

    def test_returns_discovered_manifests(self, client, install_fixture_skill):
        install_fixture_skill()
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        skills = resp.json()["skills"]
        assert [s["name"] for s in skills] == ["greet-fixture"]
        entry = skills[0]
        assert entry["version"] == "0.1.0"
        assert entry["step_count"] == 1
        assert "Fixture skill" in entry["description"]
        assert entry["author"] == "tests"


class TestGetSkill:
    def test_returns_manifest_and_install_paths(self, client, install_fixture_skill):
        skill_dir = install_fixture_skill()
        resp = client.get("/v1/skills/greet-fixture")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "greet-fixture"
        assert body["installed_paths"] == [str(skill_dir)]

    def test_unknown_skill_returns_404(self, client):
        resp = client.get("/v1/skills/no-such-skill")
        assert resp.status_code == 404
        assert "no-such-skill" in resp.json()["detail"]


class TestRemoveSkill:
    def test_removes_skill_from_disk(self, client, install_fixture_skill):
        skill_dir = install_fixture_skill()
        resp = client.delete("/v1/skills/greet-fixture")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "removed"
        assert body["removed_paths"] == [str(skill_dir)]
        assert not skill_dir.exists()

    def test_unknown_skill_returns_404(self, client):
        resp = client.delete("/v1/skills/no-such-skill")
        assert resp.status_code == 404
        assert "no-such-skill" in resp.json()["detail"]


class TestInstallSkill:
    def test_unknown_source_returns_400(self, client):
        resp = client.post("/v1/skills", json={"source": "nope", "name": "x"})
        assert resp.status_code == 400
        assert "nope" in resp.json()["detail"]

    def test_github_source_requires_url(self, client):
        resp = client.post("/v1/skills", json={"source": "github", "name": "x"})
        assert resp.status_code == 400
        assert "url" in resp.json()["detail"]

    def test_empty_name_returns_422(self, client):
        resp = client.post("/v1/skills", json={"source": "hermes", "name": "  "})
        assert resp.status_code == 422

    @staticmethod
    def _fake_resolver(monkeypatch, tmp_path):
        """Stub resolver serving one ResolvedSkill with a real SKILL.md."""

        src_dir = tmp_path / "source-cache" / "greet-fixture"
        src_dir.mkdir(parents=True)
        (src_dir / "SKILL.md").write_text(
            "---\n"
            "name: greet-fixture\n"
            "description: Fixture skill\n"
            "version: 0.1.0\n"
            "---\n\n"
            "# Greet\n\nSay hello.\n",
            encoding="utf-8",
        )

        class _Resolved:
            name = "greet-fixture"
            source = "fake"
            path = src_dir
            category = "general"
            description = "Fixture skill"
            commit = "abc123"

        class _FakeResolver:
            def __init__(self, skills):
                self._skills = skills

            def sync(self):
                pass

            def list_skills(self):
                return self._skills

        return _FakeResolver([_Resolved()])

    def test_installs_via_resolver_and_importer(self, client, monkeypatch, tmp_path):
        from nova_ai.core.paths import get_config_dir

        resolver = self._fake_resolver(monkeypatch, tmp_path)
        monkeypatch.setattr(
            routes, "_get_skill_resolver", lambda source, url="": resolver
        )

        resp = client.post(
            "/v1/skills", json={"source": "fake", "name": "greet-fixture"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "installed"
        assert body["name"] == "greet-fixture"

        installed = get_config_dir() / "skills" / "fake" / "greet-fixture"
        assert Path(body["path"]) == installed
        assert (installed / "SKILL.md").exists()
        assert (installed / ".source").exists()

        # The installed skill must immediately be discoverable.
        listed = client.get("/v1/skills")
        assert [s["name"] for s in listed.json()["skills"]] == ["greet-fixture"]

    def test_skips_when_already_installed_without_force(
        self, client, monkeypatch, tmp_path
    ):
        resolver = self._fake_resolver(monkeypatch, tmp_path)
        monkeypatch.setattr(
            routes, "_get_skill_resolver", lambda source, url="": resolver
        )

        first = client.post(
            "/v1/skills", json={"source": "fake", "name": "greet-fixture"}
        )
        assert first.status_code == 200
        assert first.json()["status"] == "installed"

        second = client.post(
            "/v1/skills", json={"source": "fake", "name": "greet-fixture"}
        )
        assert second.status_code == 200
        assert second.json()["status"] == "skipped"

        # With force=True the reinstall overwrites instead of skipping.
        forced = client.post(
            "/v1/skills",
            json={"source": "fake", "name": "greet-fixture", "force": True},
        )
        assert forced.status_code == 200
        assert forced.json()["status"] == "installed"

    def test_skill_not_found_in_source_returns_404(self, client, monkeypatch):
        class _FakeResolver:
            def sync(self):
                pass

            def list_skills(self):
                return []

        monkeypatch.setattr(
            routes, "_get_skill_resolver", lambda source, url="": _FakeResolver()
        )
        resp = client.post("/v1/skills", json={"source": "fake", "name": "ghost"})
        assert resp.status_code == 404
        assert "ghost" in resp.json()["detail"]
