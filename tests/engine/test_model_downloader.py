"""Tests for the resilient model downloader engine."""

from __future__ import annotations

import hashlib
import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

from nova_ai.engine.model_downloader import (
    ChecksumMismatch,
    DownloadSpec,
    ResilientDownloader,
    compute_file_hash,
)

PAYLOAD = os.urandom(5 * 1024 * 1024)
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    """Static-file server with Range support over a test payload."""

    def do_GET(self) -> None:  # noqa: N802
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            lo_s, hi_s = rng[6:].split("-")
            lo = int(lo_s)
            hi = int(hi_s) if hi_s else len(PAYLOAD) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {lo}-{hi}/{len(PAYLOAD)}")
            self.send_header("Content-Length", str(hi - lo + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(PAYLOAD[lo : hi + 1])
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(PAYLOAD)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(PAYLOAD)

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def log_message(self, *args) -> None:  # silence test output
        pass


@pytest.fixture()
def range_server():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _RangeHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/file.bin"
    srv.shutdown()


def _spec(tmp_path: Path, url: str, **kw) -> DownloadSpec:
    return DownloadSpec(
        url=url,
        dest=tmp_path / "model.bin",
        sha256=kw.pop("sha256", PAYLOAD_SHA256),
        chunk_threshold=kw.pop("chunk_threshold", 1024 * 1024),
        **kw,
    )


def test_chunked_download_verifies_checksum(tmp_path, range_server) -> None:
    dl = ResilientDownloader(max_connections=4)
    out = dl.download(_spec(tmp_path, range_server))
    assert out.read_bytes() == PAYLOAD
    assert not out.with_suffix(".bin.nova_dl.json").exists()


def test_checksum_mismatch_rejects_file(tmp_path, range_server) -> None:
    dl = ResilientDownloader(max_connections=2)
    spec = _spec(tmp_path, range_server, sha256="0" * 64)
    with pytest.raises(ChecksumMismatch):
        dl.download(spec)
    # rejected file must not be left in place
    assert not (tmp_path / "model.bin").exists()


def test_md5_validation(tmp_path, range_server) -> None:
    import hashlib as _h

    dl = ResilientDownloader(max_connections=2)
    spec = _spec(tmp_path, range_server)
    spec.sha256 = None
    spec.md5 = _h.md5(PAYLOAD).hexdigest()
    out = dl.download(spec)
    assert out.read_bytes() == PAYLOAD


def test_progress_callback_reports_bytes(tmp_path, range_server) -> None:
    seen: list[tuple[int, int]] = []
    dl = ResilientDownloader(max_connections=3)
    dl.download(
        _spec(tmp_path, range_server, progress=lambda d, t, s: seen.append((d, t)))
    )
    assert seen, "progress callback never fired"
    assert seen[-1][0] == len(PAYLOAD)
    assert seen[-1][1] == len(PAYLOAD)


def test_cancel_stops_download(tmp_path, range_server) -> None:
    dl = ResilientDownloader(max_connections=2)
    dl.cancel()
    with pytest.raises(Exception):  # noqa: B017
        dl.download(_spec(tmp_path, range_server))


def test_plan_chunks_contiguous_and_bounded() -> None:
    chunks = ResilientDownloader._plan_chunks(
        100_000_000, connections=6, threshold=8 * 1024 * 1024
    )
    assert len(chunks) == 6
    assert chunks[0][0] == 0
    assert chunks[-1][1] == 99_999_999
    for a, b in zip(chunks, chunks[1:]):
        assert b[0] == a[1] + 1


def test_plan_chunks_small_file_single_chunk() -> None:
    chunks = ResilientDownloader._plan_chunks(1_000_000, connections=6, threshold=8 * 1024 * 1024)
    assert chunks == [[0, 999_999, 0]]


def test_merge_progress_restores_committed_bytes() -> None:
    plan = [[0, 99, 0], [100, 199, 0]]
    saved = [[0, 99, 40], [100, 199, 0]]
    merged = ResilientDownloader._merge_progress(plan, saved)
    assert merged[0] == [0, 99, 40]
    assert merged[1] == [100, 199, 0]


def test_merge_progress_ignores_mismatched_layout() -> None:
    plan = [[0, 99, 0], [100, 199, 0]]
    saved = [[0, 149, 50]]  # different chunking layout
    merged = ResilientDownloader._merge_progress(plan, saved)
    assert all(c[2] == 0 for c in merged)


def test_resume_state_roundtrip(tmp_path: Path) -> None:
    from nova_ai.engine.model_downloader import _ResumeState

    state = _ResumeState(tmp_path / "model.gguf")
    assert state.load() is None or state.data == {}
    state.save(url="u", etag="e", total=10, chunks=[[0, 9, 5]])
    reloaded = _ResumeState(tmp_path / "model.gguf")
    data = reloaded.load()
    assert data["url"] == "u"
    assert data["chunks"] == [[0, 9, 5]]
    reloaded.discard()
    assert _ResumeState(tmp_path / "model.gguf").load() is None


def test_compute_file_hash(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(PAYLOAD[:1024])
    assert compute_file_hash(f) == hashlib.sha256(PAYLOAD[:1024]).hexdigest()
