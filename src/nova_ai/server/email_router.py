"""Email integration REST API — IMAP triage + SMTP send + AI summaries."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nova_ai.core.paths import get_config_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/email", tags=["email"])

_CREDS_FILE = "email_credentials.json"


def _creds_path() -> Path:
    return get_config_dir() / _CREDS_FILE


def _load_creds() -> dict:
    p = _creds_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _save_creds(creds: dict) -> None:
    _creds_path().parent.mkdir(parents=True, exist_ok=True)
    _creds_path().write_text(json.dumps(creds, indent=2))


def _get_imap():
    creds = _load_creds()
    if not creds:
        raise HTTPException(status_code=400, detail="Email not configured. Call POST /api/email/connect first.")
    from nova_ai.connectors.gmail_imap import GmailIMAPConnector
    return GmailIMAPConnector(
        email_address=creds["username"],
        app_password=creds["password"],
        imap_host=creds.get("imap_host", "imap.gmail.com"),
    )


def _get_smtp():
    creds = _load_creds()
    if not creds:
        raise HTTPException(status_code=400, detail="Email not configured.")
    from nova_ai.connectors.smtp_sender import SmtpSender
    return SmtpSender(
        host=creds.get("smtp_host", "smtp.gmail.com"),
        port=int(creds.get("smtp_port", 465)),
        username=creds["username"],
        password=creds["password"],
        use_ssl=creds.get("use_ssl", True),
    )


class EmailConnectRequest(BaseModel):
    username: str
    password: str          # App password for Gmail
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    use_ssl: bool = True


class EmailReplyRequest(BaseModel):
    to: str
    subject: str
    body: str
    reply_to_message_id: Optional[str] = None


class DraftRequest(BaseModel):
    original_subject: str
    original_body: str
    instruction: str = "Write a professional, concise reply."


@router.post("/connect")
async def connect_email(body: EmailConnectRequest):
    """Save IMAP/SMTP credentials and verify connection."""
    # Test IMAP connection
    try:
        import imaplib
        imap = imaplib.IMAP4_SSL(body.imap_host)
        imap.login(body.username, body.password)
        imap.logout()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"IMAP connection failed: {exc}")

    _save_creds(body.model_dump())
    return {"status": "connected", "email": body.username}


@router.get("/status")
async def email_status():
    """Check if email is configured and connection is healthy."""
    creds = _load_creds()
    if not creds:
        return {"configured": False}
    try:
        import imaplib
        imap = imaplib.IMAP4_SSL(creds.get("imap_host", "imap.gmail.com"))
        imap.login(creds["username"], creds["password"])
        imap.logout()
        return {"configured": True, "email": creds["username"], "healthy": True}
    except Exception as exc:
        return {"configured": True, "email": creds.get("username"), "healthy": False, "error": str(exc)}


@router.get("/inbox")
async def get_inbox(n: int = 20):
    """Fetch N most recent emails with urgency scores."""
    connector = _get_imap()
    try:
        emails = connector.fetch_n(n)
        return {"emails": emails, "total": len(emails)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/inbox/{uid}/summary")
async def email_summary(uid: str):
    """Generate an AI summary and action items for a single email."""
    connector = _get_imap()
    try:
        emails = connector.fetch_n(50)
        email = next((e for e in emails if str(e.get("uid")) == uid), None)
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    body_text = email.get("body_preview", "")
    prompt = (
        f"Email from: {email.get('sender')}\n"
        f"Subject: {email.get('subject')}\n\n"
        f"{body_text}\n\n"
        f"Provide:\n1. A 2-sentence summary\n2. Action items (bullet points)\n3. Urgency: {email.get('urgency')}"
    )
    try:
        from nova_ai.sdk import Nova
        summary = Nova().ask(prompt)
    except Exception:
        summary = "AI summary unavailable."

    return {"uid": uid, "summary": summary, "email": email}


@router.post("/draft")
async def draft_reply(body: DraftRequest):
    """Ask the AI to draft an email reply."""
    prompt = (
        f"Original email subject: {body.original_subject}\n"
        f"Original email body:\n{body.original_body}\n\n"
        f"Instruction: {body.instruction}\n\n"
        f"Write only the reply body text, no subject line:"
    )
    try:
        from nova_ai.sdk import Nova
        draft = Nova().ask(prompt)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI draft failed: {exc}")
    return {"draft": draft}


@router.post("/reply")
async def send_reply(body: EmailReplyRequest):
    """Send an email via SMTP."""
    sender = _get_smtp()
    try:
        sender.send(
            to=body.to,
            subject=body.subject,
            body=body.body,
            reply_to_message_id=body.reply_to_message_id,
        )
        return {"status": "sent", "to": body.to}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Send failed: {exc}")
