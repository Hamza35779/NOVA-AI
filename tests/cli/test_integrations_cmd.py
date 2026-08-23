from __future__ import annotations

from click.testing import CliRunner

from nova_ai.cli.integrations_cmd import integrations_group


def test_integrations_list() -> None:
    runner = CliRunner()
    result = runner.invoke(integrations_group, ["list"])
    assert result.exit_code == 0
    assert "Communication & Messaging" in result.output
    assert "whatsapp" in result.output
    assert "notion" in result.output
    assert "github" in result.output


def test_integrations_enable_disable() -> None:
    runner = CliRunner()
    res_enable = runner.invoke(integrations_group, ["enable", "whatsapp"])
    assert res_enable.exit_code == 0
    assert "Enabled integration with WhatsApp" in res_enable.output

    res_disable = runner.invoke(integrations_group, ["disable", "whatsapp"])
    assert res_disable.exit_code == 0
    assert "Disabled integration" in res_disable.output
