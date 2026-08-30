"""Desktop notification dispatcher with SSE subscriber broadcasting."""
from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import logging
import platform
import sqlite3
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_DB_FILE = "notifications.db"

# In-memory SSE queues for real-time frontend notification pushes
_sse_queues: List[asyncio.Queue] = []
_queues_lock = threading.Lock()


def register_notification_subscriber(queue: asyncio.Queue) -> None:
    with _queues_lock:
        _sse_queues.append(queue)


def unregister_notification_subscriber(queue: asyncio.Queue) -> None:
    with _queues_lock:
        if queue in _sse_queues:
            _sse_queues.remove(queue)


def _broadcast_sse(payload: dict) -> None:
    msg = json.dumps(payload)
    with _queues_lock:
        queues = list(_sse_queues)
    for q in queues:
        try:
            q.put_nowait(msg)
        except Exception:
            pass


class NotificationDispatcher:
    """Dispatches desktop notifications and manages notification history."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or str(get_config_dir() / _DB_FILE)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS notifications (
                        id          TEXT PRIMARY KEY,
                        title       TEXT NOT NULL,
                        message     TEXT NOT NULL,
                        urgency     TEXT NOT NULL DEFAULT 'normal',
                        action_url  TEXT,
                        timestamp   REAL NOT NULL,
                        read        INTEGER NOT NULL DEFAULT 0
                    );
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_time ON notifications(timestamp DESC);")
                conn.commit()

    def send(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
        action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a notification: save to DB, trigger desktop alert, and broadcast SSE."""
        notif_id = str(uuid.uuid4())[:8]
        now = time.time()

        with self._lock:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.execute(
                    "INSERT INTO notifications (id, title, message, urgency, action_url, timestamp, read) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0)",
                    (notif_id, title, message, urgency, action_url, now),
                )
                conn.commit()

        record = {
            "id": notif_id,
            "title": title,
            "message": message,
            "urgency": urgency,
            "action_url": action_url,
            "timestamp": now,
            "read": False,
        }

        # Desktop alert (Windows PowerShell toast / fallback)
        self._trigger_os_notification(title, message)

        # Broadcast to UI
        _broadcast_sse({"type": "notification", **record})

        return record

    def _trigger_os_notification(self, title: str, message: str) -> None:
        if platform.system() == "Windows":
            try:
                # PowerShell balloon notification
                script = f"""
                [reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
                $notify = New-Object System.Windows.Forms.NotifyIcon
                $notify.Icon = [System.Drawing.SystemIcons]::Information
                $notify.Visible = $True
                $notify.ShowBalloonTip(5000, '{title.replace("'", "''")}', '{message.replace("'", "''")}', [System.Windows.Forms.ToolTipIcon]::Info)
                """
                subprocess.Popen(["powershell", "-NoProfile", "-Command", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:
                logger.debug("Windows toast error: %s", exc)

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM notifications ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._lock:
            with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
                conn.execute("DELETE FROM notifications")
                conn.commit()


_dispatcher: Optional[NotificationDispatcher] = None
_d_lock = threading.Lock()


def get_notifier() -> NotificationDispatcher:
    global _dispatcher
    if _dispatcher is None:
        with _d_lock:
            if _dispatcher is None:
                _dispatcher = NotificationDispatcher()
    return _dispatcher
