"""Calendar and Reminders REST API routes.

Provides agenda summaries, meeting preparation notes, and event scheduling.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])

_CREDS_FILE = "calendar_credentials.json"


def _creds_path() -> Path:
    return get_config_dir() / _CREDS_FILE


def _load_creds() -> dict:
    p = _creds_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_creds(creds: dict) -> None:
    _creds_path().parent.mkdir(parents=True, exist_ok=True)
    _creds_path().write_text(json.dumps(creds, indent=2), encoding="utf-8")


class CalendarConnectRequest(BaseModel):
    provider: str = "caldav"  # caldav | google
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    google_token: Optional[str] = None


class CreateEventRequest(BaseModel):
    summary: str
    start: str
    end: str
    description: str = ""
    location: str = ""
    attendees: List[str] = []


class MeetingPrepRequest(BaseModel):
    summary: str
    description: str = ""
    attendees: List[str] = []


@router.post("/connect")
async def connect_calendar(body: CalendarConnectRequest):
    """Save Calendar / CalDAV credentials."""
    creds = body.model_dump()
    _save_creds(creds)
    return {"status": "connected", "provider": body.provider}


@router.get("/status")
async def calendar_status():
    """Return calendar connection status."""
    creds = _load_creds()
    if not creds:
        return {"configured": False}
    return {
        "configured": True,
        "provider": creds.get("provider", "caldav"),
        "username": creds.get("username", "user"),
    }


@router.get("/events")
async def get_events(days: int = 7):
    """Fetch upcoming events."""
    creds = _load_creds()
    from nova_ai.connectors.caldav_connector import CalDavConnector

    connector = CalDavConnector(
        url=creds.get("url", "https://caldav.example.com"),
        username=creds.get("username", "demo"),
        password=creds.get("password", "demo"),
    )
    events = connector.fetch_events(days_ahead=days)
    return {"events": events, "total": len(events)}


@router.get("/agenda")
async def get_agenda_briefing():
    """Generate an AI morning agenda briefing for today."""
    creds = _load_creds()
    from nova_ai.connectors.caldav_connector import CalDavConnector

    connector = CalDavConnector(
        url=creds.get("url", "https://caldav.example.com"),
        username=creds.get("username", "demo"),
        password=creds.get("password", "demo"),
    )
    events = connector.fetch_events(days_ahead=2)

    events_text = "\n".join(
        f"- {e.get('summary')} at {e.get('start')} (Location: {e.get('location', 'N/A')})"
        for e in events
    )

    prompt = (
        f"You are NOVA AI assistant. Provide a concise, motivating morning briefing based on today's schedule:\n\n"
        f"{events_text or 'No events scheduled for today.'}\n\n"
        f"Format: 2-sentence executive summary followed by top 3 priority focus items."
    )
    try:
        from nova_ai.sdk import Nova
        briefing = Nova().ask(prompt)
    except Exception:
        briefing = "Good morning! You have upcoming meetings scheduled today. Stay focused on your primary priorities."

    return {
        "briefing": briefing,
        "event_count": len(events),
        "events": events,
    }


@router.post("/meeting-prep")
async def prep_meeting(body: MeetingPrepRequest):
    """Generate meeting preparation notes, discussion topics, and action items."""
    prompt = (
        f"Prepare meeting notes and discussion strategy for:\n"
        f"Meeting: {body.summary}\n"
        f"Context: {body.description}\n"
        f"Attendees: {', '.join(body.attendees) if body.attendees else 'Team'}\n\n"
        f"Provide:\n"
        f"1. Meeting Objective\n"
        f"2. Key Talking Points (3-4 bullet points)\n"
        f"3. Potential Questions & Risks\n"
        f"4. Suggested Outcomes / Action Items"
    )
    try:
        from nova_ai.sdk import Nova
        prep = Nova().ask(prompt)
    except Exception:
        prep = (
            f"## Objective: {body.summary}\n"
            f"- Review agenda items\n- Align on next steps\n- Assign action items"
        )
    return {"prep": prep, "summary": body.summary}


@router.post("/events")
async def create_event(body: CreateEventRequest):
    """Schedule a new event."""
    creds = _load_creds()
    from nova_ai.connectors.caldav_connector import CalDavConnector

    connector = CalDavConnector(
        url=creds.get("url", "https://caldav.example.com"),
        username=creds.get("username", "demo"),
        password=creds.get("password", "demo"),
    )
    result = connector.create_event(
        summary=body.summary,
        start_time=body.start,
        end_time=body.end,
        description=body.description,
        location=body.location,
    )
    return result
