"""Tests for secure file creation helpers (Section 4)."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

# POSIX permission bits (0o700/0o600) are only meaningful on Unix. On
# Windows, os.chmod can only toggle the read-only flag and st_mode does
# not reflect ACLs — the helper still runs, but the exact-mode assertions
# would fail everywhere. The Windows CI job (3.12/3.13) runs this file,
# so the mode assertions must be Unix-only; behavior (file/dir exists)
# is still exercised on every platform.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits are not emulated on Windows",
)


class TestSecureMkdir:
    """secure_mkdir should create directories with 0o700."""

    @posix_only
    def test_creates_directory_with_700(self) -> None:
        from nova_ai.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_dir"
            result = secure_mkdir(target)
            assert result.is_dir()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700

    def test_creates_parent_directories(self) -> None:
        from nova_ai.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "c"
            result = secure_mkdir(target)
            assert result.is_dir()

    @posix_only
    def test_existing_directory_gets_permission_fix(self) -> None:
        from nova_ai.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir(mode=0o755)
            secure_mkdir(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700


class TestSecureCreate:
    """secure_create should create files with 0o600."""

    @posix_only
    def test_creates_file_with_600(self) -> None:
        from nova_ai.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_file.db"
            result = secure_create(target)
            assert result.exists()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    @posix_only
    def test_existing_file_gets_permission_fix(self) -> None:
        from nova_ai.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.db"
            target.write_text("data")
            os.chmod(target, 0o644)
            secure_create(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    @posix_only
    def test_creates_parent_directory_with_700(self) -> None:
        from nova_ai.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "file.db"
            secure_create(target)
            parent_mode = stat.S_IMODE(os.stat(target.parent).st_mode)
            assert parent_mode == 0o700
