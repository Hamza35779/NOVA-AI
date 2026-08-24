"""Slack Socket Mode daemon — listens for DMs and responds with DeepResearch.

Run as a standalone process or import start_slack_daemon() to spawn
from the server. Uses slack-bolt for reliable Socket Mode handling.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

from nova_ai.channels.slack_blocks import (
    FOLLOWUP_ACTIONS,
    FOLLOWUP_PROMPTS,
    MAX_BLOCKS,
    actions_block,
    build_reply_blocks,
    inline_mrkdwn,
)
from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_PID_FILE = str(get_config_dir() / "slack-daemon.pid")


def _to_slack_fmt(text: str) -> str:
    """Convert markdown to Slack mrkdwn format.

    Headers become bold lines; inline markup (bold, links, strikethrough,
    LaTeX) is handled by the shared Block Kit module's converter so both
    rendering paths stay consistent.
    """
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    return inline_mrkdwn(text)


def run_slack_daemon(
    bot_token: str,
    app_token: str,
    model: str = "qwen3.5:9b",
) -> None:
    """Run the Slack daemon (blocking). Handles DMs with DeepResearch."""
    import threading

    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    from nova_ai.agents.deep_research import DeepResearchAgent
    from nova_ai.engine.ollama import OllamaEngine
    from nova_ai.server.agent_manager_routes import (
        _build_deep_research_tools,
    )

    # Write PID
    pid_path = Path(_PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    # Build agent
    engine = OllamaEngine()
    tools = _build_deep_research_tools(engine=engine, model=model)
    agent = DeepResearchAgent(
        engine=engine,
        model=model,
        tools=tools,
        max_turns=5,
    )
    logger.info("Slack daemon: agent ready with %d tools", len(tools))

    app = App(token=bot_token)

    processing = threading.Event()

    @app.event("message")
    def handle_dm(event: dict, say: Any) -> None:
        text = event.get("text", "")
        if not text:
            return

        ts = event.get("ts", "")
        logger.info("Slack DM: %s", text[:60])

        say(text="Message received! Working on it now...", thread_ts=ts)
        processing.set()

        # Progress updater
        stop = threading.Event()

        def _progress() -> None:
            while not stop.is_set():
                stop.wait(60)
                if stop.is_set():
                    break
                if processing.is_set():
                    say(
                        text="Still working! Will reply ASAP",
                        thread_ts=ts,
                    )

        pt = threading.Thread(target=_progress, daemon=True)
        pt.start()

        try:
            result = agent.run(text)
            raw_content = result.content or ""
            reply = _to_slack_fmt(raw_content or "No results found.")
        except Exception as exc:
            raw_content = ""
            reply = f"Error: {exc}"
            logger.error("Slack daemon error: %s", exc)
        finally:
            processing.clear()
            stop.set()

        _post_reply(say, ts, reply, raw_content, with_buttons=True)
        logger.info("Slack DM reply sent (%d chars)", len(reply))

    def _post_reply(
        post: Any,
        thread_ts: str,
        reply: str,
        raw_content: str,
        *,
        with_buttons: bool = False,
    ) -> None:
        """Post *reply* to a thread as Block Kit when it has structure.

        The plain-mrkdwn text always rides along as the fallback field.
        Research replies additionally get follow-up action buttons (roadmap
        WS2) — handled by the ``app.action`` registrations below.
        """
        kwargs: dict = {"thread_ts": thread_ts}
        blocks = build_reply_blocks(raw_content)
        if blocks is not None:
            if with_buttons and len(blocks) < MAX_BLOCKS:
                buttons = actions_block(list(FOLLOWUP_ACTIONS))
                if buttons is not None:
                    blocks.append(buttons)
            kwargs["blocks"] = blocks
        post(text=reply, **kwargs)

    def _make_followup_handler(prompt: str) -> Any:
        def handle_followup(ack: Any, body: dict, client: Any) -> None:
            ack()
            message = body.get("message", {})
            channel_id = body.get("channel", {}).get("id", "")
            thread_ts = message.get("thread_ts") or message.get("ts", "")
            logger.info(
                "Slack follow-up button clicked (prompt: %.40s)", prompt
            )
            try:
                result = agent.run(prompt)
                raw_content = result.content or ""
                reply = _to_slack_fmt(raw_content or "No results found.")
                _post_reply(
                    lambda text, **kw: client.chat_postMessage(
                        channel=channel_id, text=text, **kw
                    ),
                    thread_ts,
                    reply,
                    raw_content,
                )
            except Exception as exc:
                logger.error("Slack follow-up error: %s", exc)
                client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text=f"Error: {exc}",
                )

        return handle_followup

    for _action_id, _label in FOLLOWUP_ACTIONS:
        app.action(_action_id)(
            _make_followup_handler(FOLLOWUP_PROMPTS[_action_id])
        )

    handler = SocketModeHandler(app, app_token)

    # Graceful shutdown
    def _stop(signum: int, frame: Any) -> None:
        logger.info("Slack daemon stopping...")
        handler.close()
        if pid_path.exists():
            pid_path.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("Slack daemon started, listening for DMs...")
    handler.start()  # Blocks until close()


def start_slack_daemon(
    bot_token: str,
    app_token: str,
    model: str = "qwen3.5:9b",
) -> int:
    """Spawn the Slack daemon as a background subprocess.

    Returns the PID of the spawned process.
    """
    import subprocess

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nova_ai.channels.slack_daemon",
            "--bot-token",
            bot_token,
            "--app-token",
            app_token,
            "--model",
            model,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def is_running() -> bool:
    """Check if the Slack daemon is running."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


def stop_daemon() -> bool:
    """Stop the running Slack daemon."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_path.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--app-token", required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    args = parser.parse_args()

    run_slack_daemon(
        bot_token=args.bot_token,
        app_token=args.app_token,
        model=args.model,
    )
