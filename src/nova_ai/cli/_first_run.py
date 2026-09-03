"""Bare-`nova` first-run guard.

When the user types ``nova`` with no subcommand, route them to the
chat command if a config exists, otherwise into the init wizard with
the ``--from-bare-nova`` flag (which lets init suppress the
launch-chat prompt and auto-confirm downstream questions).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nova_ai.core import config as _cfg

if TYPE_CHECKING:
    import click


def check_and_route(ctx: click.Context) -> None:
    """Called from the root group when no subcommand is invoked.

    Returns None and does nothing if a subcommand is being invoked
    (the user typed something specific like ``nova ask``).
    """
    if ctx.invoked_subcommand is not None:
        return

    import sys

    # When running as a packaged desktop executable, double-clicking starts the web workstation
    if getattr(sys, "frozen", False):
        import socket
        import threading
        import time
        import webbrowser

        from nova_ai.cli.serve import serve as serve_cmd

        # The server takes tens of seconds to initialize (engine discovery,
        # memory, scheduler) before uvicorn binds port 8000. A fixed sleep
        # opened the browser into ERR_CONNECTION_REFUSED; instead, poll the
        # port and open the tab the moment it accepts connections.
        def _open_browser() -> None:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                        break
                except OSError:
                    time.sleep(0.5)
            webbrowser.open("http://localhost:8000")

        print("Starting NOVA AI — the browser will open automatically when "
              "the server is ready (usually 10-30 seconds).")
        print("Keep this window open while using NOVA AI; closing it stops "
              "the server.")
        threading.Thread(target=_open_browser, daemon=True).start()
        ctx.invoke(serve_cmd)
        return

    # Late imports to avoid circular import with cli/__init__.py.
    from nova_ai.cli.chat_cmd import chat as chat_cmd
    from nova_ai.cli.init_cmd import init as init_cmd

    if _cfg.DEFAULT_CONFIG_PATH.exists():
        ctx.invoke(chat_cmd)
    else:
        ctx.invoke(init_cmd, from_bare_nova=True)
