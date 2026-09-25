"""Tests for Docker and deployment files."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent.parent
DOCKER_DIR = ROOT / "deploy" / "docker"


class TestDockerFiles:
    def test_dockerfile_exists(self):
        assert (DOCKER_DIR / "Dockerfile").is_file()

    def test_dockerfile_gpu_exists(self):
        assert (DOCKER_DIR / "Dockerfile.gpu").is_file()

    def test_dockerfile_has_entrypoint(self):
        content = (DOCKER_DIR / "Dockerfile").read_text()
        assert "ENTRYPOINT" in content
        assert "nova" in content

    def test_dockerfile_copies_forced_package_includes(self):
        # Every Dockerfile that builds the wheel from an explicit `COPY src/`
        # context (rather than `COPY . .`) must also copy the non-src
        # force-include paths before installing, or hatchling's wheel build
        # fails (see #447). Guard ALL such Dockerfiles, not just the CPU one,
        # so the GPU variants can't silently regress.
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"][
            "force-include"
        ]
        non_src_includes = [s for s in force_include if not s.startswith("src/")]

        install_marker = 'uv pip install --system ".[server]"'
        wheel_dockerfiles = [
            p
            for p in sorted(DOCKER_DIR.glob("Dockerfile*"))
            if install_marker in p.read_text() and "COPY src/ src/" in p.read_text()
        ]
        # Sanity: we actually found the wheel-building Dockerfiles to guard.
        assert wheel_dockerfiles, "no wheel-building Dockerfiles found to check"

        for dockerfile in wheel_dockerfiles:
            content = dockerfile.read_text()
            install_step = content.index(install_marker)
            for source in non_src_includes:
                copy_marker = f"COPY {source} "
                assert copy_marker in content, (
                    f"{dockerfile.name} is missing '{copy_marker.strip()}' "
                    f"(a non-src force-include path)"
                )
                assert content.index(copy_marker) < install_step, (
                    f"{dockerfile.name} copies '{source}' after the install step"
                )

    def test_docker_compose_valid_yaml(self):
        import importlib

        yaml_mod = None
        try:
            yaml_mod = importlib.import_module("yaml")
        except ImportError:
            pass

        compose_path = DOCKER_DIR / "docker-compose.yml"
        assert compose_path.is_file()
        content = compose_path.read_text()

        # Basic structural checks without requiring PyYAML
        assert "services:" in content
        assert "nova:" in content

        if yaml_mod is not None:
            data = yaml_mod.safe_load(content)
            assert "services" in data

    def test_docker_compose_has_services(self):
        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        assert "nova:" in content
        assert "ollama:" in content

    def test_systemd_service_exists(self):
        assert (ROOT / "deploy" / "systemd" / "nova_ai.service").is_file()


class TestDockerBuildConsistency:
    """Static cross-file checks that a local `docker build` would catch.

    Docker is not installed on every dev machine (and CI only exercises the
    image in the docker.yml workflow), so these tests pin the invariants the
    build relies on: the frontend COPY path must match vite's build.outDir,
    compose's build context/dockerfile must resolve to real files, the env
    template must cover every compose interpolation, and the published port
    must match the EXPOSE/serve flags.
    """

    @staticmethod
    def _wheel_dockerfiles() -> list[Path]:
        install_marker = 'uv pip install --system ".[server]"'
        return [
            p
            for p in sorted(DOCKER_DIR.glob("Dockerfile*"))
            if install_marker in p.read_text() and "COPY src/ src/" in p.read_text()
        ]

    @staticmethod
    def _compose_yaml() -> dict:
        yaml = pytest.importorskip("yaml")
        return yaml.safe_load((DOCKER_DIR / "docker-compose.yml").read_text())

    @staticmethod
    def _vite_outdir() -> str:
        """build.outDir declared in frontend/vite.config.ts (single source)."""
        config = (ROOT / "frontend" / "vite.config.ts").read_text()
        match = re.search(r"outDir:\s*['\"]([^'\"]+)['\"]", config)
        assert match, "frontend/vite.config.ts no longer declares build.outDir"
        return match.group(1)

    def test_dockerfile_frontend_copy_matches_vite_outdir(self):
        # vite writes the SPA into `../src/nova_ai/server/static` relative to
        # frontend/, i.e. /src/nova_ai/server/static inside the /frontend
        # builder stage. The COPY --from=frontend path must be exactly that,
        # or the wheel installs without a UI and `nova serve` ships API-only.
        expected = posixpath.normpath(posixpath.join("/", self._vite_outdir()))
        assert expected.endswith("nova_ai/server/static"), (
            f"unexpected vite outDir resolved to {expected}"
        )
        for dockerfile in self._wheel_dockerfiles():
            content = dockerfile.read_text()
            marker = f"COPY --from=frontend {expected}"
            assert marker in content, (
                f"{dockerfile.name}: SPA stage copy must be '{marker} ...' "
                f"to match vite build.outDir ({self._vite_outdir()})"
            )

    def test_compose_build_context_and_dockerfile_resolve(self):
        compose_dir = (DOCKER_DIR / "docker-compose.yml").parent
        build = self._compose_yaml()["services"]["nova"]["build"]
        context = (compose_dir / build["context"]).resolve()
        assert context == ROOT, "compose build context must be the repo root"
        dockerfile = context / build["dockerfile"]
        assert dockerfile.is_file(), f"missing compose build file {dockerfile}"

    def test_env_example_covers_compose_interpolation(self):
        compose_text = (DOCKER_DIR / "docker-compose.yml").read_text()
        env_text = (DOCKER_DIR / ".env.example").read_text()
        interpolated = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)[?:}]", compose_text))
        assert interpolated, "compose no longer interpolates any env vars"
        for var in interpolated:
            assert re.search(rf"^{var}=", env_text, re.MULTILINE), (
                f".env.example is missing '{var}=' documented in compose"
            )
        # The API key MUST use the :? fail-fast form — the container binds
        # 0.0.0.0, so silently starting without a key is the #221 failure mode.
        assert re.search(r"\$\{NOVA_AI_API_KEY:\?", compose_text), (
            "NOVA_AI_API_KEY must use ${VAR:?msg} fail-fast interpolation"
        )

    def test_compose_ports_match_dockerfile(self):
        expose = re.findall(r"^EXPOSE\s+(\d+)", (DOCKER_DIR / "Dockerfile").read_text(), re.MULTILINE)
        ports = self._compose_yaml()["services"]["nova"].get("ports", [])
        assert ports == ["8000:8000"], f"compose nova ports drifted: {ports}"
        assert expose == ["8000"], f"Dockerfile EXPOSE drifted: {expose}"

    def test_container_command_is_safe_public_bind(self):
        # 0.0.0.0 + auth middleware: the public bind is only acceptable
        # because NOVA_AI_API_KEY is mandatory (see auth_middleware / #221).
        # compose deliberately omits `command:` and inherits the Dockerfile CMD.
        compose = self._compose_yaml()["services"]["nova"]
        assert "command" not in compose, (
            "compose overrides the image CMD — re-check bind safety here"
        )
        cmd = re.search(
            r'^CMD\s+(\[.*\])\s*$',
            (DOCKER_DIR / "Dockerfile").read_text(),
            re.MULTILINE,
        )
        assert cmd, "Dockerfile lost its CMD"
        import json

        assert json.loads(cmd.group(1)) == [
            "serve", "--host", "0.0.0.0", "--port", "8000"
        ]

    def test_gpu_overrides_reference_real_dockerfiles(self):
        yaml = pytest.importorskip("yaml")
        for override, expected_dockerfile in (
            ("docker-compose.gpu.nvidia.yml", "Dockerfile.gpu"),
            ("docker-compose.gpu.rocm.yml", "Dockerfile.gpu.rocm"),
        ):
            data = yaml.safe_load((DOCKER_DIR / override).read_text())
            dockerfile = data["services"]["nova"]["build"]["dockerfile"]
            # Accept either a compose-dir-relative or repo-root-relative path
            # (compose resolves it against the build context).
            assert posixpath.basename(dockerfile) == expected_dockerfile, (
                f"{override} builds with unexpected dockerfile {dockerfile}"
            )
            assert (ROOT / dockerfile).is_file() or (DOCKER_DIR / dockerfile).is_file(), (
                f"{override} points at missing {dockerfile}"
            )
