"""Smoke tests for the CLI entrypoint."""

from click.testing import CliRunner

from dorgy.cli import cli


def test_cli_help_displays_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Dorgy automatically organizes" in result.output
