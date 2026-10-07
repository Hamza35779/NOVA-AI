"""Calendar write tool — create, update, delete, and read Google Calendar events.

Read paths (sync, search) already exist on the connector and as MCP tools;
this tool closes the write gap so agents can schedule on the user's behalf.

Network-facing (``is_local = False``) and confirmation-gated: every action
mutates or reads the user's live calendar.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from nova_ai.connectors.gcalendar import GCalendarConnector, _format_event
from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


def _event_datetime(value: str) -> Dict[str, str]:
    """Build an API ``start``/``end`` mapping from a date or datetime string."""
    value = value.strip()
    if len(value) == 10:  # YYYY-MM-DD → all-day event
        return {"date": value}
    return {"dateTime": value}


def _split_attendees(raw: Any) -> Optional[List[Dict[str, str]]]:
    """Normalise a comma-separated attendee string into API attendee objects."""
    if raw is None:
        return None
    if isinstance(raw, list):
        emails = [str(e).strip() for e in raw if str(e).strip()]
    else:
        emails = [e.strip() for e in str(raw).split(",") if e.strip()]
    if not emails:
        return None
    return [{"email": email} for email in emails]


@ToolRegistry.register("calendar_tool")
class CalendarTool(BaseTool):
    """Create, update, delete, and fetch Google Calendar events."""

    tool_id = "calendar_tool"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calendar_tool",
            description=(
                "Manage Google Calendar events. Actions: 'create' a new event "
                "(needs summary, start, end), 'update' an existing event "
                "(needs event_id plus the fields to change), 'delete' an event "
                "(needs event_id), 'get' one event's details. Times accept "
                "RFC 3339 datetimes (e.g. '2026-10-09T10:00:00Z') or plain "
                "dates ('2026-10-09') for all-day events."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "update", "delete", "get"],
                        "description": "Calendar operation to perform.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Calendar ID. Defaults to 'primary'.",
                        "default": "primary",
                    },
                    "event_id": {
                        "type": "string",
                        "description": "Event ID (required for update, delete, get).",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Event title (required for create).",
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time, RFC 3339 or YYYY-MM-DD.",
                    },
                    "end": {
                        "type": "string",
                        "description": "End time, RFC 3339 or YYYY-MM-DD.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location.",
                    },
                    "attendees": {
                        "type": ["string", "array"],
                        "description": (
                            "Attendee emails, comma-separated or as a list. "
                            "Attendees receive invites on create."
                        ),
                    },
                    "credentials_path": {
                        "type": "string",
                        "description": (
                            "Optional Google credentials file path. "
                            "Defaults to the connector's configured location."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="productivity",
            requires_confirmation=True,
            timeout_seconds=30.0,
        )

    @track_execution("calendar_tool")
    def execute(
        self,
        action: str,
        calendar_id: str = "primary",
        event_id: str = "",
        summary: str = "",
        start: str = "",
        end: str = "",
        description: str = "",
        location: str = "",
        attendees: Any = None,
        credentials_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        action = (action or "").lower().strip()
        if action not in ("create", "update", "delete", "get"):
            return ToolResult(
                tool_name="calendar_tool",
                content=f"Error: unknown action '{action}'. Use create, update, delete, or get.",
                success=False,
            )

        try:
            connector = (
                GCalendarConnector(credentials_path=credentials_path)
                if credentials_path
                else GCalendarConnector()
            )
            token_check = connector._get_token()
            if not token_check:
                raise RuntimeError("Google Calendar token missing")
        except RuntimeError as exc:
            return ToolResult(
                tool_name="calendar_tool",
                content=f"Error: Google Calendar not authenticated ({exc}). "
                "Connect the calendar first.",
                success=False,
            )

        try:
            if action == "create":
                return self._create(
                    connector, calendar_id, summary, start, end,
                    description, location, attendees,
                )
            if action in ("update", "delete", "get"):
                if not event_id.strip():
                    return ToolResult(
                        tool_name="calendar_tool",
                        content=f"Error: event_id is required for '{action}'.",
                        success=False,
                    )
                if action == "delete":
                    connector.delete_event(event_id.strip(), calendar_id)
                    return ToolResult(
                        tool_name="calendar_tool",
                        content=f"Deleted event '{event_id.strip()}'.",
                        success=True,
                        metadata={"action": action, "event_id": event_id.strip()},
                    )
                if action == "get":
                    event = connector.get_event(event_id.strip(), calendar_id)
                    return ToolResult(
                        tool_name="calendar_tool",
                        content=_format_event(event),
                        success=True,
                        metadata={
                            "action": action,
                            "event_id": event.get("id", event_id.strip()),
                        },
                    )
                return self._update(
                    connector, calendar_id, event_id.strip(), summary,
                    start, end, description, location, attendees,
                )
        except Exception as exc:  # noqa: BLE001 — surfaced to the agent verbatim
            return ToolResult(
                tool_name="calendar_tool",
                content=f"Calendar {action} failed: {exc}",
                success=False,
            )
        # Unreachable: all actions return above.
        return ToolResult(
            tool_name="calendar_tool",
            content=f"Error: unhandled action '{action}'.",
            success=False,
        )

    def _create(
        self,
        connector: GCalendarConnector,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str,
        location: str,
        attendees: Any,
    ) -> ToolResult:
        if not summary.strip():
            return ToolResult(
                tool_name="calendar_tool",
                content="Error: summary is required for 'create'.",
                success=False,
            )
        if not start.strip() or not end.strip():
            return ToolResult(
                tool_name="calendar_tool",
                content="Error: start and end are required for 'create'.",
                success=False,
            )
        event = connector.create_event(
            summary.strip(),
            _event_datetime(start),
            _event_datetime(end),
            calendar_id,
            description=description.strip() or None,
            location=location.strip() or None,
            attendees=_split_attendees(attendees),
        )
        return ToolResult(
            tool_name="calendar_tool",
            content=f"Created event:\n{_format_event(event)}",
            success=True,
            metadata={"action": "create", "event_id": event.get("id", "")},
        )

    def _update(
        self,
        connector: GCalendarConnector,
        calendar_id: str,
        event_id: str,
        summary: str,
        start: str,
        end: str,
        description: str,
        location: str,
        attendees: Any,
    ) -> ToolResult:
        fields: Dict[str, Any] = {}
        if summary.strip():
            fields["summary"] = summary.strip()
        if start.strip():
            fields["start"] = _event_datetime(start)
        if end.strip():
            fields["end"] = _event_datetime(end)
        if description.strip():
            fields["description"] = description.strip()
        if location.strip():
            fields["location"] = location.strip()
        parsed_attendees = _split_attendees(attendees)
        if parsed_attendees is not None:
            fields["attendees"] = parsed_attendees
        if not fields:
            return ToolResult(
                tool_name="calendar_tool",
                content="Error: nothing to update. Provide at least one field to change.",
                success=False,
            )
        event = connector.update_event(event_id, calendar_id, **fields)
        return ToolResult(
            tool_name="calendar_tool",
            content=f"Updated event:\n{_format_event(event)}",
            success=True,
            metadata={"action": "update", "event_id": event.get("id", event_id)},
        )


__all__ = ["CalendarTool"]
