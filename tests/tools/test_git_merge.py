"""Tests for the git_manager merge action."""

from __future__ import annotations

import subprocess

from nova_ai.tools.git_manager import GitManagerTool


def _run_git(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path) -> None:
    _run_git(["init", "-b", "main"], str(path))
    _run_git(["config", "user.email", "test@test.com"], str(path))
    _run_git(["config", "user.name", "Test User"], str(path))
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _run_git(["add", "."], str(path))
    _run_git(["commit", "-m", "Initial commit"], str(path))


class TestGitMerge:
    def test_merge_feature_branch(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitManagerTool()

        result = tool.execute(
            action="checkout", repo_path=str(tmp_path), args="-b feature"
        )
        assert result.success is True
        (tmp_path / "feature.txt").write_text("feature\n", encoding="utf-8")
        result = tool.execute(action="add_all", repo_path=str(tmp_path))
        assert result.success is True
        result = tool.execute(
            action="commit", repo_path=str(tmp_path), args="Add feature"
        )
        assert result.success is True
        result = tool.execute(
            action="checkout", repo_path=str(tmp_path), args="main"
        )
        assert result.success is True

        result = tool.execute(
            action="merge", repo_path=str(tmp_path), args="feature"
        )
        assert result.success is True
        assert (tmp_path / "feature.txt").is_file()
        assert result.metadata["action"] == "merge"

    def test_merge_conflict_reports_error(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitManagerTool()

        (tmp_path / "base.txt").write_text("main line\n", encoding="utf-8")
        _run_git(["commit", "-am", "Main change"], str(tmp_path))
        _run_git(["checkout", "-b", "feature"], str(tmp_path))
        (tmp_path / "base.txt").write_text("feature line\n", encoding="utf-8")
        _run_git(["commit", "-am", "Feature change"], str(tmp_path))
        _run_git(["checkout", "main"], str(tmp_path))
        (tmp_path / "base.txt").write_text("conflicting main line\n", encoding="utf-8")
        _run_git(["commit", "-am", "Conflicting main change"], str(tmp_path))

        result = tool.execute(
            action="merge", repo_path=str(tmp_path), args="feature"
        )
        assert result.success is False
        assert "CONFLICT" in result.content or "conflict" in result.content.lower()

    def test_merge_nonexistent_branch(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitManagerTool()
        result = tool.execute(
            action="merge", repo_path=str(tmp_path), args="no-such-branch"
        )
        assert result.success is False

    def test_merge_not_a_repo(self, tmp_path):
        tool = GitManagerTool()
        result = tool.execute(
            action="merge", repo_path=str(tmp_path), args="main"
        )
        assert result.success is False
        assert "Not a Git repository" in result.content
