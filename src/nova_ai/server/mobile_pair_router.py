"""Mobile Companion & PWA QR code pairing API."""
from __future__ import annotations

import logging
import socket
from typing import Any, Dict

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mobile", tags=["mobile"])


def _get_local_ip() -> str:
    """Discover the local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        # Doesn't need to be reachable, just opens a socket to route
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def _generate_qr_svg(data: str) -> str:
    """Generate a clean SVG QR code data URI or SVG markup."""
    # Try using qrcode library if present, or generate a clean SVG representation
    try:
        import io

        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(data, image_factory=factory)
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode("utf-8")
    except Exception:
        # Simple SVG fallback
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text x="10" y="50" font-size="6" fill="white">{data}</text></svg>'


@router.get("/pairing-info")
async def get_pairing_info() -> Dict[str, Any]:
    """Return local LAN access URLs and pairing instructions."""
    ip = _get_local_ip()
    port = 8000
    lan_url = f"http://{ip}:{port}"
    qr_svg = _generate_qr_svg(lan_url)

    return {
        "lan_ip": ip,
        "port": port,
        "lan_url": lan_url,
        "qr_svg": qr_svg,
        "pairing_pin": f"{abs(hash(ip)) % 9000 + 1000}",
        "instructions": [
            "1. Connect your phone/tablet to the same Wi-Fi network as your computer.",
            f"2. Scan the QR code or open: {lan_url}",
            "3. On iOS (Safari): Tap Share -> 'Add to Home Screen'.",
            "4. On Android (Chrome): Tap menu -> 'Install App'.",
        ],
    }
