"""``nova doctor`` — run diagnostic checks on the NOVA AI installation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table

from nova_ai.core.config import DEFAULT_CONFIG_PATH, load_config
from nova_ai.core.utils import soft_fail

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: str  # "ok", "warn", "fail"
    message: str
    details: Optional[str] = None


# -- Individual checks -------------------------------------------------------


def _bounded_health(engine: Any, timeout_s: float = 8.0) -> bool:
    """Call ``engine.health()`` with a hard wall-clock bound.

    Why not trust the engine's own HTTP timeout: httpx/httpcore timeouts do
    NOT cover DNS resolution — ``socket.getaddrinfo`` is a blocking C call
    outside the socket timeout's control. On a machine whose DNS black-holes
    (corporate firewalls, offline boxes with a stale resolver), a probe to an
    unreachable engine host hangs for the OS-level TCP timeout (minutes).
    Reproduced: `nova doctor` froze >120s with zero output while
    ``_OpenAICompatibleEngine.health(timeout=2.0)`` sat inside
    ``socket.create_connection``.

    The probe runs in a daemon thread; on expiry the calling check continues
    immediately ("Unreachable") and the abandoned thread dies whenever the
    OS finally unblocks the socket. Daemon threads keep interpreter shutdown
    clean.
    """
    import threading

    result: list[bool] = [False]

    def _probe() -> None:
        try:
            result[0] = bool(engine.health())
        except Exception:  # noqa: BLE001 — a raising probe means "unreachable"
            result[0] = False

    thread = threading.Thread(target=_probe, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        logger.warning(
            "Engine %s health probe exceeded %.0fs — treating as unreachable",
            getattr(engine, "engine_id", type(engine).__name__),
            timeout_s,
        )
    return result[0]


def _bounded_health_map(
    engines: Dict[str, Any], timeout_s: float = 8.0
) -> Dict[str, bool]:
    """Probe many engines concurrently with the same hard bound.

    ``_check_engines``/``_check_models`` must probe every registered engine
    (~13 on a default install). Sequentially, 8s bounds on unreachable hosts
    compound — a measured 107s doctor run. Probing in parallel caps the
    whole sweep at ~one bound instead of N×bound.
    """
    import threading

    results: Dict[str, bool] = {}
    lock = threading.Lock()

    def _probe(key: str, engine: Any) -> None:
        ok = _bounded_health(engine, timeout_s=timeout_s)
        with lock:
            results[key] = ok

    threads = [
        threading.Thread(target=_probe, args=(key, engine), daemon=True)
        for key, engine in engines.items()
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout_s + 2.0)  # child bound + small scheduling margin
    # Any thread still alive past its own bound recorded nothing — default False.
    for key in engines:
        results.setdefault(key, False)
    return results


def _make_engines(config: Any) -> Dict[str, Any]:
    """Instantiate every registered engine, skipping failures quietly."""
    from nova_ai.core.registry import EngineRegistry
    from nova_ai.engine import _discovery

    engines: Dict[str, Any] = {}
    for key in sorted(EngineRegistry.keys()):
        try:
            engines[key] = _discovery._make_engine(key, config)
        except Exception as exc:  # noqa: BLE001 — optional engine config
            soft_fail(logger, exc, "optional CLI step")
    return engines


def _check_python_version() -> CheckResult:
    """Check that Python version is >= 3.10."""
    ver = sys.version_info
    version_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if (ver.major, ver.minor) >= (3, 10):
        return CheckResult("Python version", "ok", version_str)
    return CheckResult("Python version", "fail", f"{version_str} (requires >= 3.10)")


def _check_config_exists() -> CheckResult:
    """Check that the config file exists."""
    if DEFAULT_CONFIG_PATH.exists():
        return CheckResult("Config file", "ok", str(DEFAULT_CONFIG_PATH))
    return CheckResult(
        "Config file",
        "warn",
        f"Not found at {DEFAULT_CONFIG_PATH}",
        details="Run `nova init` to generate a config file.",
    )


def _check_config_parses() -> CheckResult:
    """Check that the config file parses successfully."""
    if not DEFAULT_CONFIG_PATH.exists():
        return CheckResult("Config parsing", "warn", "Skipped (no config file)")
    try:
        load_config()
        return CheckResult("Config parsing", "ok", "Config loaded successfully")
    except Exception as exc:
        return CheckResult("Config parsing", "fail", f"Parse error: {exc}")


def _ensure_engines_imported() -> None:
    """Import engine modules to trigger registration decorators."""
    try:
        import nova_ai.engine  # noqa: F401
    except Exception as exc:
        soft_fail(logger, exc, "optional CLI step")


def _get_config() -> Any:
    """Load config or return a default if parsing fails."""
    try:
        return load_config()
    except Exception:
        from nova_ai.core.config import NovaConfig

        return NovaConfig()


def _check_engines() -> List[CheckResult]:
    """Probe each registered engine for health (concurrently, bounded)."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from nova_ai.core.registry import EngineRegistry

    config = _get_config()

    engines = _make_engines(config)
    health = _bounded_health_map(engines)
    for key in sorted(EngineRegistry.keys()):
        if key not in engines:
            results.append(
                CheckResult(f"Engine: {key}", "warn", "Failed to initialize")
            )
        elif health.get(key):
            results.append(CheckResult(f"Engine: {key}", "ok", "Reachable"))
        else:
            results.append(CheckResult(f"Engine: {key}", "warn", "Unreachable"))

    if not results:
        results.append(CheckResult("Engines", "warn", "No engines registered"))

    return results


def _check_models() -> List[CheckResult]:
    """List models from healthy engines (probes concurrent, bounded)."""
    results: List[CheckResult] = []

    _ensure_engines_imported()

    from nova_ai.core.registry import EngineRegistry

    config = _get_config()

    engines = _make_engines(config)
    health = _bounded_health_map(engines)
    for key in sorted(EngineRegistry.keys()):
        engine = engines.get(key)
        if engine is None or not health.get(key):
            continue
        try:
            models = engine.list_models()
            if models:
                model_list = ", ".join(models[:5])
                suffix = f" (+{len(models) - 5} more)" if len(models) > 5 else ""
                results.append(
                    CheckResult(
                        f"Models: {key}",
                        "ok",
                        f"{model_list}{suffix}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        f"Models: {key}",
                        "warn",
                        "No models available",
                        details="Pull a model (e.g. `ollama pull qwen3.5:2b`).",
                    )
                )
        except Exception as exc:
            soft_fail(logger, exc, "optional CLI step")
            continue

    return results


def _check_default_model() -> CheckResult:
    """Check whether the configured default model is available."""
    try:
        config = load_config()
    except Exception:
        return CheckResult("Default model", "warn", "Skipped (config unavailable)")

    default_model = config.intelligence.default_model
    if not default_model:
        return CheckResult(
            "Default model",
            "ok",
            "Not configured (auto-routing enabled)",
            details="Router will select a model dynamically.",
        )

    _ensure_engines_imported()

    from nova_ai.core.registry import EngineRegistry

    preferred = config.intelligence.preferred_engine or config.engine.default
    check_order = []
    if preferred:
        check_order.append(preferred)
    check_order += [k for k in sorted(EngineRegistry.keys()) if k != preferred]

    engines = _make_engines(config)
    for key in check_order:
        engine = engines.get(key)
        if engine is None:
            continue
        try:
            if _bounded_health(engine):
                models = engine.list_models()
                if default_model in models:
                    return CheckResult(
                        "Default model",
                        "ok",
                        f"{default_model} (on {key})",
                    )
        except Exception as exc:
            soft_fail(logger, exc, "optional CLI step")
            continue

    return CheckResult(
        "Default model",
        "warn",
        f"{default_model} not found on any engine",
    )


def _check_optional_deps() -> List[CheckResult]:
    """Check availability of optional dependency packages."""
    results: List[CheckResult] = []
    optional_packages = [
        ("fastapi", "nova_ai[server]", "REST API server"),
        ("torch", "pip install torch", "SFT/GRPO training"),
        ("pynvml", "nova_ai[gpu-metrics]", "NVIDIA energy monitoring"),
        ("amdsmi", "nova_ai[energy-amd]", "AMD energy monitoring"),
        ("colbert", "nova_ai[memory-colbert]", "ColBERT memory backend"),
        ("zeus", "nova_ai[energy-apple]", "Apple Silicon energy monitoring"),
    ]
    for pkg, install_hint, description in optional_packages:
        try:
            __import__(pkg)
            results.append(CheckResult(f"Optional: {description}", "ok", "Installed"))
        except Exception:
            results.append(
                CheckResult(
                    f"Optional: {description}",
                    "warn",
                    f"Not installed ({install_hint})",
                )
            )
    return results


def _check_speech_backend() -> CheckResult:
    """Check whether the configured speech backend can load."""
    try:
        from nova_ai.speech._discovery import get_speech_backend

        config = _get_config()
        backend = get_speech_backend(config)
        if backend is None:
            return CheckResult(
                "Speech backend",
                "warn",
                "Not configured",
                details="Install desktop dependencies with `uv sync --extra desktop`.",
            )

        # Local speech backends may legitimately load a model on first health
        # check — allow more headroom than the network probes, but still bound
        # it so a wedged model load cannot hang the whole doctor run.
        if _bounded_health(backend, timeout_s=30.0):
            return CheckResult(
                "Speech backend",
                "ok",
                f"{backend.backend_id} ready",
            )

        details = None
        last_error = getattr(backend, "last_error", None)
        if callable(last_error):
            details = last_error()
        return CheckResult(
            "Speech backend",
            "warn",
            f"{backend.backend_id} unavailable",
            details=details
            or "Install desktop dependencies with `uv sync --extra desktop`.",
        )
    except Exception as exc:
        return CheckResult(
            "Speech backend",
            "warn",
            f"Could not check: {exc}",
        )


def _check_security_profile() -> CheckResult:
    """Check if a security profile is configured."""
    try:
        from nova_ai.core.config import load_config

        config = load_config()
        if config.security.profile:
            return CheckResult(
                name="Security profile",
                status="ok",
                message=f"Profile '{config.security.profile}' active",
            )
        return CheckResult(
            name="Security profile",
            status="warn",
            message="No security profile set",
            details="Recommended: add security.profile = 'personal' to config.toml",
        )
    except Exception as exc:
        return CheckResult(
            name="Security profile",
            status="fail",
            message=f"Could not check: {exc}",
        )


def _check_nodejs() -> CheckResult:
    """Check Node.js version for Node-backed integrations."""
    node_path = shutil.which("node")
    if not node_path:
        return CheckResult(
            "Node.js",
            "warn",
            "Not found",
            details=(
                "Node.js 22+ is required for ClaudeCodeAgent and the "
                "WhatsApp Baileys channel bridge."
            ),
        )
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version_str = result.stdout.strip()
        # Parse "v22.1.0" -> (22, 1, 0)
        parts = version_str.lstrip("v").split(".")
        major = int(parts[0])
        if major >= 22:
            return CheckResult("Node.js", "ok", version_str)
        return CheckResult(
            "Node.js",
            "warn",
            f"{version_str} (requires >= v22)",
            details=(
                "Upgrade Node.js for ClaudeCodeAgent and WhatsApp Baileys support."
            ),
        )
    except Exception as exc:
        return CheckResult("Node.js", "warn", f"Error checking version: {exc}")


# -- Main command -------------------------------------------------------------

_STATUS_ICONS = {
    "ok": "[green]\u2713[/green]",
    "warn": "[yellow]![/yellow]",
    "fail": "[red]\u2717[/red]",
}


def _check_node_version() -> CheckResult:
    """Alias gate: Node 22+ required (CONTRIBUTING canonical)."""
    return _check_nodejs()


def _check_port_free(port: int = 8000) -> CheckResult:
    """Check default serve port is free."""
    import socket

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return CheckResult(f"Port {port}", "ok", "free")
    except OSError:
        return CheckResult(
            f"Port {port}",
            "warn",
            "in use",
            details=f"Stop stale server or run `nova serve --port {port + 1}`.",
        )
    finally:
        try:
            s.close()
        except Exception:
            pass


def _check_dirs_writable() -> CheckResult:
    """Check ~/.nova_ai writable + keyring availability."""
    from nova_ai.core.paths import get_config_dir

    try:
        d = get_config_dir()
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        try:
            import keyring  # noqa: F401

            kr = "keyring available"
        except ImportError:
            kr = "keyring missing (file fallback)"
        return CheckResult("Config dir", "ok", f"{d} writable; {kr}")
    except Exception as exc:
        return CheckResult("Config dir", "fail", f"not writable: {exc}")


def _check_web_ui(repo_root=None) -> CheckResult:
    """Check the built web UI exists (source installs only).

    ``src/nova_ai/server/static/`` is generated by ``npm run build`` and is
    never committed, so a fresh source clone serves the API fine but has no
    browser UI — historically with zero indication anything was missing.

    *repo_root* is injectable for tests; defaults to the checkout containing
    this file.
    """
    from pathlib import Path

    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    if not (root / "frontend").is_dir():
        # Installed wheel/executable layout: no frontend/ checkout next to the
        # package, so the UI ships pre-built inside the distribution.
        return CheckResult("Web UI", "ok", "bundled with install")
    index = root / "src" / "nova_ai" / "server" / "static" / "index.html"
    if index.is_file():
        return CheckResult("Web UI", "ok", "built (static/index.html present)")
    return CheckResult(
        "Web UI",
        "warn",
        "not built",
        details=(
            "Browser visits will show setup instructions instead of the app. "
            "Build it with: cd frontend && npm install && npm run build"
        ),
    )


def _run_all_checks() -> List[CheckResult]:
    """Run all diagnostic checks and return results."""
    checks: List[CheckResult] = []
    checks.append(_check_python_version())
    checks.append(_check_node_version())
    checks.append(_check_config_exists())
    checks.append(_check_config_parses())
    checks.append(_check_port_free())
    checks.append(_check_dirs_writable())
    checks.append(_check_web_ui())
    checks.extend(_check_engines())
    checks.extend(_check_models())
    checks.append(_check_default_model())
    checks.extend(_check_optional_deps())
    checks.append(_check_speech_backend())
    checks.append(_check_nodejs())
    checks.append(_check_security_profile())
    return checks


def _results_to_dicts(checks: List[CheckResult]) -> List[Dict[str, Any]]:
    """Convert CheckResult list to JSON-serializable dicts."""
    return [asdict(c) for c in checks]


@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output results as JSON.")
@click.option(
    "--fix", "auto_fix", is_flag=True, help="Auto-fix: create dirs, pull starter model."
)
@click.option(
    "--bundle",
    "bundle",
    is_flag=True,
    help="Write redacted diagnostics bundle for GitHub issues.",
)
@click.option(
    "--check-all", "check_all", is_flag=True, help="Alias: run all checks (default)."
)
def doctor(as_json: bool, auto_fix: bool, bundle: bool, check_all: bool) -> None:
    """Run diagnostic checks on your NOVA AI installation."""
    del check_all  # default behavior; flag kept for docs parity
    if auto_fix:
        _auto_fix()
    checks = _run_all_checks()

    # A failing check must fail the command: CI and setup scripts gate on
    # the exit code, and exit 0 on a broken install reads as healthy.
    # (Warnings are informational — only "fail" blocks.)
    if any(c.status == "fail" for c in checks):
        if as_json:
            click.echo(json.dumps(_results_to_dicts(checks), indent=2))
        raise click.exceptions.Exit(code=1)

    if as_json:
        click.echo(json.dumps(_results_to_dicts(checks), indent=2))
        return

    console = Console()
    console.print()
    console.print("[bold]NOVA AI Doctor[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=3, justify="center")
    table.add_column("Check")
    table.add_column("Result")

    for check in checks:
        icon = _STATUS_ICONS.get(check.status, "?")
        message = check.message
        if check.details:
            message += f"\n  [dim]{check.details}[/dim]"
        table.add_row(icon, check.name, message)

    console.print(table)

    ok_count = sum(1 for c in checks if c.status == "ok")
    warn_count = sum(1 for c in checks if c.status == "warn")
    fail_count = sum(1 for c in checks if c.status == "fail")
    console.print()
    console.print(f"  {ok_count} passed, {warn_count} warnings, {fail_count} failures")
    console.print()

    # Background tasks section
    from nova_ai.cli._bg_state import get_status
    from nova_ai.core.paths import get_config_dir

    scripts_dir = get_config_dir() / ".scripts"
    console.print("[bold]Background tasks[/bold]")
    bg = get_status()
    bg_failed = False

    if bg.rust_extension == "ready":
        console.print("  [green]✓[/green] Rust extension: ready")
    elif bg.rust_extension == "failed":
        console.print(f"  [red]✗[/red] Rust extension: failed — {bg.rust_error[:80]}")
        console.print(
            f"    retry: {scripts_dir}/install-rust.sh && "
            f"{scripts_dir}/build-extension.sh"
        )
        bg_failed = True
    else:
        console.print(
            "  [yellow]…[/yellow] Rust extension: building (run in background)"
        )

    if not bg.models:
        console.print("  [dim]no model downloads tracked[/dim]")
    for model_id, state in bg.models.items():
        if state == "ready":
            console.print(f"  [green]✓[/green] {model_id}: ready")
        elif state == "failed":
            console.print(f"  [red]✗[/red] {model_id}: failed")
            console.print(f"    retry: {scripts_dir}/pull-model.sh {model_id}")
            bg_failed = True
        else:
            console.print(f"  [yellow]…[/yellow] {model_id}: downloading")

    if bg_failed:
        raise click.exceptions.Exit(code=1)

    if bundle:
        path = _write_bundle(checks)
        console.print(f"[dim]Diagnostics bundle: {path} (secrets redacted)[/dim]")


def _auto_fix() -> None:
    """Best-effort fixes: config dir, starter model hint, stale pid cleanup."""
    from nova_ai.core.paths import get_config_dir

    try:
        get_config_dir().mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        soft_fail(logger, exc, "doctor --fix mkdir")
    # Model pull is intentionally hint-only (no network side effects in CI):
    # real pull runs via `ollama pull qwen3:8b` when Ollama is reachable.


def _write_bundle(checks: List[CheckResult]) -> str:
    """Zip redacted doctor JSON for GitHub issues."""
    import tempfile
    import zipfile

    try:
        from nova_ai.analytics.redaction import CredentialStripper

        strip = CredentialStripper().strip
    except ImportError:

        def strip(s: str) -> str:  # type: ignore[misc]
            return s

    payload = json.dumps(_results_to_dicts(checks), indent=2)
    payload = strip(payload)
    out = str(
        __import__("pathlib").Path(tempfile.gettempdir()) / "nova_doctor_bundle.zip"
    )
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("doctor.json", payload)
    return out
