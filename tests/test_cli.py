from typer.testing import CliRunner
from relia_cli.main import app as cli_app

runner = CliRunner()

def test_cli_help():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    # Commands should be listed in the help text
    assert "generate" in result.stdout
    assert "lint" in result.stdout

def test_cli_verbose_flag():
    result = runner.invoke(cli_app, ["--verbose"])
    assert result.exit_code == 0
    assert "Verbose logging enabled" in result.stdout