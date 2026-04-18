from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from pyru.cli import build_parser, main


class CLITests(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["pyru", *argv]),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            try:
                code = int(main())
            except SystemExit as exc:
                code = int(exc.code) if exc.code is not None else 0
        return code, out.getvalue(), err.getvalue()

    def test_parser_accepts_help_flag(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_version_flag_prints_pyru(self) -> None:
        code, out, _ = self._run("--version")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("pyru "))

    def test_scrape_requires_at_least_one_url(self) -> None:
        code, _, _ = self._run("scrape", "-s", "p")
        self.assertNotEqual(code, 0)

    def test_scrape_rejects_non_http_scheme(self) -> None:
        code, _, err = self._run("scrape", "-s", "p", "ftp://example.com/resource")
        self.assertNotEqual(code, 0)
        self.assertIn("http(s)", err.lower())

    def test_scrape_rejects_missing_host(self) -> None:
        code, _, _ = self._run("scrape", "-s", "p", "http:///no-host")
        self.assertNotEqual(code, 0)

    def test_scrape_concurrency_range_is_enforced(self) -> None:
        code, _, _ = self._run("scrape", "-s", "p", "-c", "0", "http://example.com/")
        self.assertNotEqual(code, 0)

    def test_scrape_reports_unreachable_host_without_traceback(self) -> None:
        code, out, err = self._run(
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
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)

    def test_scrape_invalid_selector_yields_clean_error(self) -> None:
        code, out, err = self._run(
            "scrape",
            "-s",
            "!!!invalid",
            "--timeout-ms",
            "100",
            "--connect-timeout-ms",
            "50",
            "http://127.0.0.1:1/",
        )
        self.assertNotEqual(code, 0)
        combined = out + err
        self.assertNotIn("Traceback", combined)
        self.assertIn("invalid CSS selector", combined)

    def test_scrape_help_documents_every_option(self) -> None:
        code, out, _ = self._run("scrape", "--help")
        self.assertEqual(code, 0)
        for flag in (
            "--selector",
            "--output",
            "--concurrency",
            "--user-agent",
            "--timeout-ms",
            "--connect-timeout-ms",
        ):
            self.assertIn(flag, out, msg=f"missing {flag} in help output")


if __name__ == "__main__":
    unittest.main()
