"""Tests for the calendar_tool. All Calendar API calls are mocked; no network."""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch

import pytest

from nova_ai.tools.calendar_tool import CalendarTool

_EVENT = {
    "id": "evt1",
    "summary": "Sprint Planning",
    "description": "Review goals.",
    "start": {"dateTime": "2026-10-09T10:00:00Z"},
    "end": {"dateTime": "2026-10-09T11:00:00Z"},
    "location": "Room 3",
    "attendees": [{"email": "alice@co.com"}],
    "organizer": {"email": "me@co.com"},
    "htmlLink": "https://calendar.google.com/event?eid=evt1",
}


@pytest.fixture()
def creds(tmp_path) -> str:
    path = tmp_path / "gcalendar.json"
    path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    return str(path)


@pytest.fixture()
def tool() -> CalendarTool:
    return CalendarTool()


def _unauthenticated_tool() -> CalendarTool:
    return CalendarTool()


class TestCalendarToolSpec:
    def test_spec(self, tool: CalendarTool):
        assert tool.spec.name == "calendar_tool"
        assert tool.spec.category == "productivity"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.parameters["required"] == ["action"]
        assert set(tool.spec.parameters["properties"]["action"]["enum"]) == {
            "create",
            "update",
            "delete",
            "get",
        }


class TestCalendarToolAuth:
    def test_not_authenticated(self, tool: CalendarTool, tmp_path):
        missing = str(tmp_path / "no-creds.json")
        result = tool.execute(action="get", event_id="evt1", credentials_path=missing)
        assert result.success is False
        assert "not authenticated" in result.content.lower()


class TestCalendarToolCreate:
    def test_create_event(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_insert",
            return_value=dict(_EVENT),
        ) as mock_insert:
            result = tool.execute(
                action="create",
                summary="Sprint Planning",
                start="2026-10-09T10:00:00Z",
                end="2026-10-09T11:00:00Z",
                attendees="alice@co.com",
                credentials_path=creds,
            )
        assert result.success is True
        assert result.metadata["event_id"] == "evt1"
        body: Dict[str, Any] = mock_insert.call_args[0][2]
        assert body["summary"] == "Sprint Planning"
        assert body["start"] == {"dateTime": "2026-10-09T10:00:00Z"}
        assert body["attendees"] == [{"email": "alice@co.com"}]

    def test_create_all_day_event(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_insert",
            return_value=dict(_EVENT),
        ) as mock_insert:
            result = tool.execute(
                action="create",
                summary="Holiday",
                start="2026-12-25",
                end="2026-12-26",
                credentials_path=creds,
            )
        assert result.success is True
        body = mock_insert.call_args[0][2]
        assert body["start"] == {"date": "2026-12-25"}

    def test_create_missing_summary(self, tool: CalendarTool, creds: str):
        result = tool.execute(
            action="create",
            start="2026-10-09T10:00:00Z",
            end="2026-10-09T11:00:00Z",
            credentials_path=creds,
        )
        assert result.success is False
        assert "summary is required" in result.content

    def test_create_missing_times(self, tool: CalendarTool, creds: str):
        result = tool.execute(
            action="create", summary="No time", credentials_path=creds
        )
        assert result.success is False
        assert "start and end are required" in result.content


class TestCalendarToolUpdateDeleteGet:
    def test_update_event(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_patch",
            return_value=dict(_EVENT),
        ) as mock_patch:
            result = tool.execute(
                action="update",
                event_id="evt1",
                location="Room 5",
                credentials_path=creds,
            )
        assert result.success is True
        assert mock_patch.call_args[0][3] == {"location": "Room 5"}

    def test_update_nothing_to_change(self, tool: CalendarTool, creds: str):
        result = tool.execute(
            action="update", event_id="evt1", credentials_path=creds
        )
        assert result.success is False
        assert "nothing to update" in result.content

    def test_delete_event(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_delete",
            return_value=None,
        ) as mock_delete:
            result = tool.execute(
                action="delete", event_id="evt1", credentials_path=creds
            )
        assert result.success is True
        assert mock_delete.call_args[0][2] == "evt1"

    def test_get_event(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_get",
            return_value=dict(_EVENT),
        ):
            result = tool.execute(
                action="get", event_id="evt1", credentials_path=creds
            )
        assert result.success is True
        assert "Sprint Planning" in result.content
        assert result.metadata["event_id"] == "evt1"

    def test_missing_event_id(self, tool: CalendarTool, creds: str):
        result = tool.execute(action="delete", credentials_path=creds)
        assert result.success is False
        assert "event_id is required" in result.content

    def test_unknown_action(self, tool: CalendarTool, creds: str):
        result = tool.execute(action="teleport", credentials_path=creds)
        assert result.success is False
        assert "unknown action" in result.content

    def test_api_error_surfaced(self, tool: CalendarTool, creds: str):
        with patch(
            "nova_ai.connectors.gcalendar._gcal_api_event_get",
            side_effect=RuntimeError("404 not found"),
        ):
            result = tool.execute(
                action="get", event_id="evt1", credentials_path=creds
            )
        assert result.success is False
        assert "404 not found" in result.content
