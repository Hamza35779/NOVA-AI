import pytest
from fastapi.testclient import TestClient

from nova_ai.server.mobile_pair_router import router, _get_local_ip, _generate_qr_svg
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_get_local_ip():
    ip = _get_local_ip()
    assert isinstance(ip, str)
    assert len(ip.split(".")) == 4

def test_generate_qr_svg():
    svg = _generate_qr_svg("http://127.0.0.1:8000")
    assert "<svg" in svg

def test_pairing_info():
    response = client.get("/api/mobile/pairing-info")
    assert response.status_code == 200
    data = response.json()
    assert "lan_ip" in data
    assert "port" in data
    assert "lan_url" in data
    assert "qr_svg" in data
    assert "pairing_pin" in data
    assert "instructions" in data
