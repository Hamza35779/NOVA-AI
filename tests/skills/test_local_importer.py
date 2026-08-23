from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

from nova_ai.cli.skill_cmd import skill


def test_import_local_skill() -> None:
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create a sample local skill directory
        skill_dir = tmp_path / "sample_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: sample_skill\ndescription: A test sample skill.\n---\n\n# Sample Skill\n\nInstructions here.\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            skill, ["import-local", str(skill_dir), "--source-name", "testlocal"]
        )
        assert result.exit_code == 0
        assert "sample_skill" in result.output
        assert "Import complete" in result.output
