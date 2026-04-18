from __future__ import annotations

import json

import pytest

from pyru.cli import build_parser, main


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str, catch_exit: bool = True) -> int:
    monkeypatch.setattr("sys.argv", ["pyru", *argv])
    if catch_exit:
        try:
            return int(main())
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0
    return int(main())


def test_parser_accepts_help_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--help"])
    assert excinfo.value.code == 0


def test_version_flag_reports_pyru(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pyru", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("pyru ")


def test_scrape_requires_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(monkeypatch, "scrape", "-s", "p")
    assert code != 0


def test_scrape_rejects_non_http_scheme(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(monkeypatch, "scrape", "-s", "p", "ftp://example.com/resource")
    assert code != 0
    err = capsys.readouterr().err
    assert "http(s)" in err.lower()


def test_scrape_rejects_missing_host(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(monkeypatch, "scrape", "-s", "p", "http:///no-host")
    assert code != 0


def test_scrape_concurrency_range_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(monkeypatch, "scrape", "-s", "p", "-c", "0", "http://example.com/")
    assert code != 0


def test_scrape_reports_unreachable_host_without_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(
        monkeypatch,
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
    )
    assert code == 1
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Traceback" not in combined


def test_scrape_invalid_selector_is_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(
        monkeypatch,
        "scrape",
        "-s",
        "!!!invalid",
        "--timeout-ms",
        "100",
        "--connect-timeout-ms",
        "50",
        "http://127.0.0.1:1/",
    )
    assert code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Traceback" not in combined
    assert "invalid CSS selector" in combined


def test_scrape_help_documents_every_option(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pyru", "scrape", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--selector", "--output", "--concurrency", "--user-agent", "--timeout-ms"):
        assert flag in out, f"missing {flag} in help output"
    json.dumps(out)  # help text is plain; must be JSON-serialisable
