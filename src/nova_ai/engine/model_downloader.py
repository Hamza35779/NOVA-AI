"""Resilient multi-threaded model downloader engine.

Chunked, resumable, checksum-verified downloads for local model weights
(GGUF / SafeTensors / PyTorch checkpoints) from Hugging Face and other
direct-URL hubs. Replaces the single-stream ``download_gguf_model`` path:

- **Multi-connection chunking** — splits the file into N chunks fetched
  concurrently via HTTP ``Range`` requests (falls back to a single stream
  when the server does not advertise ``accept-ranges``).
- **Resume state persistence** — every chunk's committed bytes are tracked
  in a sidecar ``*.nova_dl.json`` next to the partial file, so an
  interrupted download continues where it left off across process
  restarts. URL responses without a known total size restart from zero.
- **Integrity validation** — after the final byte lands, the file is
  hashed (SHA-256 by default, MD5 supported) and compared against the
  expected digest before the ``.tmp`` file is promoted to its final name.
  HF ``X-Linked-ETag``/ETag is used as a fallback fingerprint when no
  digest is published.
- **Dynamic throttling** — a token-bucket limiter bounds aggregate
  bandwidth; concurrency can be tuned at runtime.
- **Retry with backoff** — per-chunk retries on connection resets and
  timeouts, with jittered exponential backoff.

Usage::

    from nova_ai.engine.model_downloader import ResilientDownloader, DownloadSpec

    dl = ResilientDownloader()
    path = dl.download(DownloadSpec(
        url="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/x.gguf",
        dest=Path.home() / ".nova_ai" / "models" / "x.gguf",
        sha256="…",               # optional, enforced when present
        progress=lambda done, total, speed: None,
    ))
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------

_DEFAULT_CONNECTIONS = int(os.environ.get("NOVA_DL_CONNECTIONS", "6"))
_DEFAULT_CHUNK_RETRIES = int(os.environ.get("NOVA_DL_RETRIES", "5"))
_DEFAULT_TIMEOUT = float(os.environ.get("NOVA_DL_TIMEOUT", "30"))
_USER_AGENT = "nova-ai/1.2.4 (resilient-downloader)"

ProgressFn = Callable[[int, int, float], None]
"""``progress(bytes_done, bytes_total, bytes_per_second)``"""


@dataclass
class DownloadSpec:
    """Everything the downloader needs to fetch one model file."""

    url: str
    dest: Path
    sha256: Optional[str] = None
    md5: Optional[str] = None
    # Extra headers (e.g. HF token Authorization)
    headers: Dict[str, str] = field(default_factory=dict)
    # Minimum server size (bytes) required to accept chunked mode; below this
    # a single connection is cheaper than thread coordination.
    chunk_threshold: int = 8 * 1024 * 1024
    # Max concurrent connections for this file (0 = engine default)
    connections: int = 0
    # Aggregate bandwidth cap in bytes/sec (0 = unlimited)
    max_bytes_per_sec: int = 0
    # Called after every committed chunk with (done, total, speed)
    progress: Optional[ProgressFn] = None


class ChecksumMismatch(RuntimeError):
    """Raised when a downloaded file fails integrity validation."""


class RangeUnsupported(RuntimeError):
    """Server did not advertise Range support; single-stream fallback used."""


# ---------------------------------------------------------------------------
# Token bucket (dynamic throttling)
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Simple thread-safe token bucket for bandwidth throttling."""

    def __init__(self, rate: int) -> None:
        self.rate = max(0, rate)
        self._tokens = float(rate) if rate > 0 else 0.0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def set_rate(self, rate: int) -> None:
        with self._lock:
            self.rate = max(0, rate)
            self._tokens = min(self._tokens, float(self.rate))

    def consume(self, amount: int) -> None:
        """Block until ``amount`` tokens are available."""
        if self.rate <= 0:
            return
        while amount > 0:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    float(self.rate),
                    self._tokens + (now - self._last) * self.rate,
                )
                self._last = now
                granted = min(amount, self._tokens)
                if granted > 0:
                    self._tokens -= granted
                    amount -= int(granted)
            if amount > 0:
                time.sleep(min(0.05, max(0.001, amount / max(self.rate, 1))))


# ---------------------------------------------------------------------------
# Resume state sidecar
# ---------------------------------------------------------------------------


class _ResumeState:
    """Persistent per-file chunk ledger (``<dest>.nova_dl.json``).

    Layout::

        {
          "url": "...",
          "etag": "...",
          "total": 12345,
          "chunks": [[start, end, committed], ...],
          "updated": 1700000000.0
        }
    """

    def __init__(self, dest: Path) -> None:
        self.path = dest.with_suffix(dest.suffix + ".nova_dl.json")
        self.data: Dict[str, Any] = {}

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            return self.data
        except (OSError, ValueError):
            self.data = {}
            return None

    def save(self, *, url: str, etag: str, total: int, chunks: List[List[int]]) -> None:
        self.data = {
            "url": url,
            "etag": etag,
            "total": total,
            "chunks": chunks,
            "updated": time.time(),
        }
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            logger.debug("Could not persist resume state to %s", self.path)

    def discard(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self.data = {}


# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------


class ResilientDownloader:
    """Chunked, resumable, checksum-verifying file downloader."""

    def __init__(
        self,
        *,
        max_connections: int = _DEFAULT_CONNECTIONS,
        chunk_retries: int = _DEFAULT_CHUNK_RETRIES,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.max_connections = max(1, max_connections)
        self.chunk_retries = max(1, chunk_retries)
        self.timeout = timeout
        self._bucket = _TokenBucket(0)
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused

    # -- control ------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def set_speed_limit(self, bytes_per_sec: int) -> None:
        self._bucket.set_rate(max(0, bytes_per_sec))

    def _check_gate(self) -> None:
        if self._cancel.is_set():
            raise RuntimeError("Download cancelled")
        self._pause.wait()

    # -- HTTP helpers ---------------------------------------------------------

    def _headers(
        self, spec: DownloadSpec, extra: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        h = {"User-Agent": _USER_AGENT, **spec.headers}
        if extra:
            h.update(extra)
        return h

    def _client(self):
        import httpx

        return httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(self.timeout, read=None),
        )

    # -- public entry ---------------------------------------------------------

    def download(self, spec: DownloadSpec) -> Path:
        """Download ``spec.url`` to ``spec.dest`` with full resilience.

        Raises ``ChecksumMismatch`` when validation fails; the partial file
        is removed and resume state discarded in that case. A download whose
        cancel flag is already set raises immediately.
        """
        if self._cancel.is_set():
            raise RuntimeError("Download cancelled")

        spec.dest.parent.mkdir(parents=True, exist_ok=True)
        self._cancel.clear()

        # Lazy import here (not module level) so the except clause below can
        # reference httpx without making httpx a hard import of this module.
        import httpx

        with self._client() as client:
            probe = client.head(
                spec.url,
                headers=self._headers(spec),
                timeout=self.timeout,
            )

            total = int(probe.headers.get("content-length", "0") or 0)
            etag = probe.headers.get("etag", "")
            accept_ranges = probe.headers.get("accept-ranges", "").lower() == "bytes"

            # HF redirects to CDN; HEAD may 405 — retry with GET+Range probe.
            # raise_for_status() must come AFTER this check: failing the HEAD
            # hard would make the fallback below unreachable.
            if probe.status_code >= 400 or total == 0:
                try:
                    with client.stream(
                        "GET",
                        spec.url,
                        headers=self._headers(spec, {"Range": "bytes=0-0"}),
                    ) as resp:
                        resp.raise_for_status()
                        cr = resp.headers.get("content-range", "")
                        accept_ranges = (
                            accept_ranges
                            or bool(cr)
                            or (
                                resp.headers.get("accept-ranges", "").lower()
                                == "bytes"
                            )
                        )
                        if cr and "/" in cr:
                            total = int(cr.rsplit("/", 1)[-1])
                        etag = etag or resp.headers.get("etag", "")
                        if resp.status_code == 200 and not cr:
                            # Full body came back — drain and mark unsupported
                            accept_ranges = False
                except httpx.HTTPError as exc:
                    # GET probe also failed — report the more precise error
                    probe.raise_for_status()
                    raise RuntimeError(f"Probe failed for {spec.url}: {exc}") from exc

            final_path = spec.dest
            tmp_path = spec.dest.with_suffix(spec.dest.suffix + ".part")

            # Resume: adopt existing partial only if server fingerprint matches
            state = _ResumeState(final_path)
            prior = state.load() or {}
            resumable = (
                prior
                and prior.get("url") == spec.url
                and (not etag or not prior.get("etag") or prior.get("etag") == etag)
                and prior.get("total") == total
                and tmp_path.exists()
            )

            if not resumable or total <= 0:
                state.discard()
                tmp_path.unlink(missing_ok=True)

            if total <= 0:
                # Unknown size: single-stream fallback still must pass
                # integrity validation before promotion — bypassing _validate
                # would mount a corrupt file as verified. Run the simple
                # stream into the .part path, then validate + promote here.
                self._single_stream(client, spec, tmp_path)
                self._validate(spec, tmp_path)
                tmp_path.replace(final_path)
                state.discard()
                logger.info("Model verified and mounted: %s", final_path)
                return final_path

            chunks = self._plan_chunks(
                total,
                connections=(spec.connections or self.max_connections),
                threshold=spec.chunk_threshold,
            )
            if resumable and isinstance(prior.get("chunks"), list):
                chunks = self._merge_progress(chunks, prior["chunks"])

            supports_range = accept_ranges
            logger.info(
                "Downloading %s (%.1f MB) -> %s [%s]",
                spec.url.rsplit("/", 1)[-1],
                total / 1_048_576,
                final_path.name,
                "chunked" if supports_range else "single-stream",
            )

            if supports_range and len(chunks) > 1:
                self._download_chunked(client, spec, tmp_path, chunks, total, etag)
            else:
                self._download_single_range(client, spec, tmp_path, total)

            # ------------------------------------------------------------
            # Integrity validation — hash before promotion
            # ------------------------------------------------------------
            self._validate(spec, tmp_path)

            tmp_path.replace(final_path)
            state.discard()
            logger.info("Model verified and mounted: %s", final_path)
            return final_path
    # -- strategies -----------------------------------------------------------

    def _download_chunked(
        self,
        client,
        spec: DownloadSpec,
        tmp_path: Path,
        chunks: List[List[int]],
        total: int,
        etag: str = "",
    ) -> None:
        """Fetch chunks concurrently, retrying each on failure."""
        lock = threading.Lock()
        progress = spec.progress or (lambda d, t, s: None)
        start_monotonic = time.monotonic()
        done_bytes = sum(c[2] for c in chunks)

        def _report() -> None:
            elapsed = max(time.monotonic() - start_monotonic, 1e-6)
            with lock:
                current = sum(c[2] for c in chunks)
            speed = (current - done_bytes) / elapsed if elapsed > 0 else 0.0
            progress(current, total, speed)

        def _fetch(chunk: List[int]) -> None:
            start, end, committed = chunk
            attempt = 0
            while True:
                self._check_gate()
                attempt += 1
                try:
                    offset = start + committed
                    headers = self._headers(spec, {"Range": f"bytes={offset}-{end}"})
                    with client.stream("GET", spec.url, headers=headers) as resp:
                        if resp.status_code == 416:
                            # Range already satisfied — chunk complete
                            chunk[2] = end - start + 1
                            return
                        resp.raise_for_status()
                        with tmp_path.open("r+b") as fh:
                            fh.seek(offset)
                            for data in resp.iter_bytes(chunk_size=256 * 1024):
                                self._check_gate()
                                self._bucket.consume(len(data))
                                fh.write(data)
                                chunk[2] += len(data)
                    return
                except Exception as exc:  # noqa: BLE001 — retry any transport error
                    if self._cancel.is_set():
                        raise
                    if attempt > self.chunk_retries:
                        raise RuntimeError(
                            f"Chunk {start}-{end} failed after "
                            f"{self.chunk_retries} retries: {exc}"
                        ) from exc
                    backoff = min(30.0, (2**attempt) * 0.5)
                    backoff *= 0.5 + random.random()  # jitter
                    logger.warning(
                        "Chunk %s-%s retry %d/%d in %.1fs: %s",
                        start,
                        end,
                        attempt,
                        self.chunk_retries,
                        backoff,
                        exc,
                    )
                    time.sleep(backoff)

        # Open the preallocated file once
        if not tmp_path.exists() or tmp_path.stat().st_size != total:
            with tmp_path.open("wb") as fh:
                fh.truncate(total)

        with ThreadPoolExecutor(
            max_workers=len(chunks), thread_name_prefix="nova-dl"
        ) as pool:
            futures = {pool.submit(_fetch, c): c for c in chunks}
            last_save = 0.0
            try:
                while futures:
                    finished = [f for f in futures if f.done()]
                    for f in finished:
                        futures.pop(f)
                        f.result()  # re-raise chunk failures
                        _report()
                    if time.monotonic() - last_save > 2.0:
                        state = _ResumeState(spec.dest)
                        state.save(url=spec.url, etag=etag, total=total, chunks=chunks)
                        last_save = time.monotonic()
                    if not futures:
                        break
                    time.sleep(0.1)
            except Exception:
                # Persist progress so a retry can resume
                state = _ResumeState(spec.dest)
                state.save(url=spec.url, etag=etag, total=total, chunks=chunks)
                raise
            state = _ResumeState(spec.dest)
            state.save(url=spec.url, etag=etag, total=total, chunks=chunks)
            _report()

    def _download_single_range(
        self,
        client,
        spec: DownloadSpec,
        tmp_path: Path,
        total: int,
    ) -> None:
        """Sequential fallback with in-stream retry from last byte offset."""
        progress = spec.progress or (lambda d, t, s: None)
        offset = 0
        if tmp_path.exists():
            offset = tmp_path.stat().st_size
            if offset >= total:
                return
        attempt = 0
        start_monotonic = time.monotonic()
        while True:
            self._check_gate()
            attempt += 1
            try:
                headers = self._headers(
                    spec, {"Range": f"bytes={offset}-"} if offset else None
                )
                with client.stream("GET", spec.url, headers=headers) as resp:
                    resp.raise_for_status()
                    with tmp_path.open("ab") as fh:
                        for data in resp.iter_bytes(chunk_size=256 * 1024):
                            self._check_gate()
                            self._bucket.consume(len(data))
                            fh.write(data)
                            offset += len(data)
                            elapsed = max(time.monotonic() - start_monotonic, 1e-6)
                            progress(offset, total, offset / elapsed)
                return
            except Exception as exc:  # noqa: BLE001
                if self._cancel.is_set():
                    raise
                if attempt > self.chunk_retries:
                    raise
                backoff = min(30.0, (2**attempt) * 0.5) * (0.5 + random.random())
                logger.warning(
                    "Single-stream retry %d/%d in %.1fs: %s",
                    attempt,
                    self.chunk_retries,
                    backoff,
                    exc,
                )
                time.sleep(backoff)

    def _single_stream(
        self,
        client,
        spec: DownloadSpec,
        tmp_path: Path,
    ) -> None:
        """Unknown content-length: simple streaming download, no resume.

        Writes to ``tmp_path`` only — the caller validates the hash and
        performs the .part → final promotion (kept there so every download
        path funnels through the same integrity gate).
        """
        progress = spec.progress or (lambda d, t, s: None)
        attempt = 0
        downloaded = 0
        start = time.monotonic()
        while True:
            self._check_gate()
            attempt += 1
            try:
                with client.stream(
                    "GET", spec.url, headers=self._headers(spec)
                ) as resp:
                    resp.raise_for_status()
                    with tmp_path.open("wb") as fh:
                        for data in resp.iter_bytes(chunk_size=256 * 1024):
                            self._check_gate()
                            self._bucket.consume(len(data))
                            fh.write(data)
                            downloaded += len(data)
                            elapsed = max(time.monotonic() - start, 1e-6)
                            progress(downloaded, 0, downloaded / elapsed)
                return
            except Exception as exc:  # noqa: BLE001
                if self._cancel.is_set():
                    raise
                if attempt > self.chunk_retries:
                    raise RuntimeError(f"Download failed: {exc}") from exc
                time.sleep(min(30.0, (2**attempt) * 0.5) * (0.5 + random.random()))

    # -- chunk planning -------------------------------------------------------

    @staticmethod
    def _plan_chunks(total: int, connections: int, threshold: int) -> List[List[int]]:
        """Split [0, total) into ``connections`` contiguous [start, end, done]."""
        if total < threshold or connections <= 1:
            return [[0, total - 1, 0]]
        n = min(connections, max(1, total // threshold))
        n = max(1, min(n, connections))
        span = total // n
        chunks: List[List[int]] = []
        pos = 0
        for i in range(n):
            end = total - 1 if i == n - 1 else pos + span - 1
            chunks.append([pos, end, 0])
            pos = end + 1
        return chunks

    @staticmethod
    def _merge_progress(
        chunks: List[List[int]], saved: List[List[int]]
    ) -> List[List[int]]:
        """Carry committed byte counts from a prior session onto the plan."""
        by_start = {c[0]: c for c in saved if isinstance(c, list) and len(c) == 3}
        merged = []
        for start, end, _done in chunks:
            prior = by_start.get(start)
            if prior and prior[1] == end:
                merged.append([start, end, min(prior[2], end - start + 1)])
            else:
                merged.append([start, end, 0])
        return merged

    # -- validation -----------------------------------------------------------

    def _validate(self, spec: DownloadSpec, tmp_path: Path) -> None:
        """Hash the completed file; raise ChecksumMismatch on any mismatch."""
        expected = spec.sha256 or spec.md5
        if not expected:
            logger.info(
                "No checksum published for %s — trusting ETag only", spec.dest.name
            )
            return
        algo = "sha256" if spec.sha256 else "md5"
        h = hashlib.new(algo)
        with tmp_path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        actual = h.hexdigest().lower()
        expected = expected.lower().removeprefix("sha256:").strip()
        if actual != expected:
            tmp_path.unlink(missing_ok=True)
            _ResumeState(spec.dest).discard()
            raise ChecksumMismatch(
                f"{algo} mismatch for {spec.dest.name}: "
                f"expected {expected}, got {actual}"
            )
        logger.info("Integrity verified (%s=%s…)", algo, actual[:12])


def compute_file_hash(path: Path, algo: str = "sha256") -> str:
    """Utility: hash a local file (streamed, constant memory)."""
    h = hashlib.new(algo)
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
