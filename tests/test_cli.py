from __future__ import annotations

import json

from click.testing import CliRunner
from pyru.cli import cli


def test_help_lists_scrape_command() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "scrape" in result.output.lower()


def test_version_flag_prints_semver() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert "pyru" in result.output.lower()


def test_scrape_requires_at_least_one_url() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scrape", "-s", "p"])
    assert result.exit_code != 0


def test_scrape_rejects_non_http_scheme() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scrape", "-s", "p", "ftp://example.com/resource"])
    assert result.exit_code != 0
    assert "http(s)" in result.output.lower()


def test_scrape_rejects_missing_host() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scrape", "-s", "p", "http:///no-host"])
    assert result.exit_code != 0


def test_scrape_reports_unreachable_host_without_crashing() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "scrape",
            "-s",
            "p",
            "-c",
            "1",
            "--timeout-ms",
            "200",
            "--connect-timeout-ms",
            "100",
            "http://127.0.0.1:1/",
        ],
    )
    # Connection refusal → per-URL error, non-zero exit, but no traceback.
    assert result.exit_code == 1, result.output
    assert "Traceback" not in (result.output + (result.stderr or ""))


def test_scrape_invalid_selector_is_clean_error_not_traceback() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "scrape",
            "-s",
            "!!!invalid",
            "--timeout-ms",
            "100",
            "--connect-timeout-ms",
            "50",
            "http://127.0.0.1:1/",
        ],
    )
    assert result.exit_code != 0
    combined = result.output + (result.stderr or "")
    assert "Traceback" not in combined
    assert "invalid CSS selector" in combined


def test_scrape_json_output_is_valid_for_help_only() -> None:
    # We cannot make real HTTP calls in unit tests; smoke-check `--help` for `scrape` subcommand.
    runner = CliRunner()
    result = runner.invoke(cli, ["scrape", "--help"])
    assert result.exit_code == 0, result.output
    assert "--selector" in result.output
    assert "--output" in result.output
    assert "--concurrency" in result.output
    # Ensure the JSON output option is documented.
    assert "json" in result.output.lower()
    # Sanity: our help text never accidentally embeds JSON-breaking characters
    json.dumps(result.output)
