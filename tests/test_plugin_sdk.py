"""Plugin SDK + doctor flags smoke tests."""

from click.testing import CliRunner

from nova_ai.cli.doctor_cmd import doctor
from nova_ai.cli.plugin_cmd import plugin
from nova_ai.cli.registry_cmd import registry


def test_doctor_flags_exist():
    runner = CliRunner()
    for flag in ("--fix", "--bundle", "--check-all", "--json"):
        result = runner.invoke(doctor, [flag, "--help"] if flag == "--json" else ["--help"])
        assert flag in result.output, flag


def test_plugin_scaffold_tool(tmp_path):
    from nova_ai.plugins.sdk import scaffold

    target = scaffold("tool", "my-test-tool", tmp_path)
    assert target.exists()
    assert (tmp_path / "test_my-test-tool.py").exists()
    assert "my-test-tool" in target.read_text(encoding="utf-8")


def test_registry_search_install():
    runner = CliRunner()
    result = runner.invoke(registry, ["search", "definitely-not-a-real-tool-xyz"])
    assert result.exit_code == 0
    result = runner.invoke(registry, ["install", "demo-tool"])
    assert result.exit_code == 0
    result = runner.invoke(plugin, ["--help"])
    assert result.exit_code == 0
