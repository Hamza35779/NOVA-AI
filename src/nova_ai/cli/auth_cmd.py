"""CLI commands for API key management."""

from __future__ import annotations

import os
import stat

import click

# NOTE: keyring storage is imported lazily inside the commands so the base
# CLI keeps working without the optional security-keyring extra.
from nova_ai.core.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
)
from nova_ai.server.auth_middleware import generate_api_key


@click.group("auth")
def auth() -> None:
    """Manage API authentication keys."""


@auth.command("create-key")
@click.option(
    "--store",
    type=click.Choice(["config", "keyring"]),
    default="config",
    show_default=True,
    help="Where to persist the key. 'keyring' uses the OS credential vault "
    "(Windows Credential Manager / macOS Keychain / Secret Service).",
)
def create_key(store: str) -> None:
    """Generate a new API key and store it in config or the OS keyring."""
    key = generate_api_key()

    if store == "keyring":
        from nova_ai.security import keyring_store

        try:
            keyring_store.store_secret("server", "api_key", key)
        except keyring_store.KeyringUnavailable as exc:
            click.echo(f"Keyring unavailable: {exc}")
            raise SystemExit(1) from exc
        click.echo("API key generated and stored in the OS keyring.")
        click.echo("It is NOT written to config.toml (no plaintext on disk).")
        click.echo("Clients keep sending it as a Bearer token / NOVA_AI_API_KEY.")
        return

    config_path = DEFAULT_CONFIG_PATH

    # Ensure config directory exists
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Update or add [server.auth].api_key via tomlkit (parse-and-edit) so we
    # can never emit a duplicate/broken [server] table — the old raw string
    # append could corrupt config.toml and crash `nova serve` with a
    # TOMLDecodeError. Falls back cleanly if the existing file is unparseable.
    import tomlkit
    from tomlkit.exceptions import TOMLKitError

    try:
        doc = (
            tomlkit.parse(config_path.read_text(encoding="utf-8"))
            if config_path.exists()
            else tomlkit.document()
        )
    except TOMLKitError as exc:
        click.echo(f"Existing config is not valid TOML ({exc}); refusing to edit.")
        raise SystemExit(1) from exc

    if "server" not in doc:
        doc.add("server", tomlkit.table())
    server = doc["server"]
    if "auth" not in server or not isinstance(server["auth"], dict):
        server.add("auth", tomlkit.table())
    server["auth"]["api_key"] = key

    try:
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    except OSError as exc:
        click.echo(f"Could not write {config_path}: {exc}")
        raise SystemExit(1) from exc
    os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    click.echo(f"API key generated: {key}")
    click.echo(f"Stored in: {config_path}")
    click.echo("File permissions set to 0600 (user-only read/write).")


@auth.command("revoke-key")
def revoke_key() -> None:
    """Revoke the current API key (OS keyring and/or config)."""
    from nova_ai.security import keyring_store

    removed_from_keyring = False
    try:
        removed_from_keyring = keyring_store.delete_secret("server", "api_key")
    except keyring_store.KeyringUnavailable:
        pass
    except Exception as exc:  # backend error — warn, still try the config
        click.echo(f"Warning: could not clear keyring entry: {exc}")

    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        if removed_from_keyring:
            click.echo("API key revoked (removed from the OS keyring).")
        else:
            click.echo("No API key found.")
        return

    content = config_path.read_text()
    if "api_key" not in content:
        if removed_from_keyring:
            click.echo("API key revoked (removed from the OS keyring).")
        else:
            click.echo("No API key found in config.")
        return

    import tomlkit

    doc = tomlkit.parse(content)
    server = doc.get("server")
    auth = server.get("auth") if server is not None else None
    if auth is not None and "api_key" in auth:
        auth["api_key"] = ""
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        click.echo("API key revoked.")
    elif removed_from_keyring:
        click.echo("API key revoked (removed from the OS keyring).")
    else:
        click.echo("No API key found in config.")


@auth.command("migrate-key")
def migrate_key() -> None:
    """Move the API key from config.toml into the OS keyring."""
    from nova_ai.security import keyring_store

    config_path = DEFAULT_CONFIG_PATH
    if not config_path.exists():
        click.echo("No config file found — nothing to migrate.")
        return

    import tomlkit
    from tomlkit.exceptions import TOMLKitError

    try:
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    except TOMLKitError as exc:
        click.echo(f"Existing config is not valid TOML ({exc}); refusing to edit.")
        raise SystemExit(1) from exc

    server = doc.get("server")
    auth = server.get("auth") if server is not None else None
    key = auth.get("api_key", "") if auth is not None else ""
    if not key:
        click.echo("No plaintext API key in config.toml — nothing to migrate.")
        return

    try:
        keyring_store.store_secret("server", "api_key", key)
    except keyring_store.KeyringUnavailable as exc:
        click.echo(f"Keyring unavailable: {exc}")
        raise SystemExit(1) from exc

    auth["api_key"] = ""
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    click.echo("API key moved into the OS keyring; config.toml no longer stores it.")
