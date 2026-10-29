"""Check Markdown publication and diagnostic handling without rendering images.

Parser outcomes are mocked here to exercise publication and recovery behavior.
Real Mermaid grammar checks remain a separate integration check; these fixtures
are not substitutes for a Mermaid parser.
"""

import hashlib
from contextlib import contextmanager
from html import escape
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / ".agents/skills/trace-visualization/trace_data.py"
SPEC = importlib.util.spec_from_file_location("trace_markdown", SCRIPT)
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)

GOOD = "sequenceDiagram\n    participant S as Sender\n    S->>S: Observed event\n"
GANTT = ("gantt\n    dateFormat x\n    axisFormat %L\n"
         "    section Local clock\n    Observed interval :0, 42ms\n")
BAD = "sequenceDiagram\n    Note over S: Await completion (code-derived; IRQs run)\n"
DIAGNOSTIC = "Parse error on line 2:\nExpected NEWLINE, received IRQs\nParser stack: fixture"


class TraceMarkdownTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="trace markdown test ")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.report = self.directory / "report with spaces.md"
        self.log = self.report.with_suffix(".log")
        # Network and the actual browser belong to the integration tests. Keep
        # these publication/recovery tests independent of loopback permissions.
        @contextmanager
        def local_page(library, page):
            self.page_library, self.browser_page = library, page
            yield "http://127.0.0.1:12345/check.html"
        patch = mock.patch.object(TRACE, "_mermaid_page", side_effect=local_page)
        patch.start()
        self.addCleanup(patch.stop)

    def write_report(self, *sources):
        text = "# Trace explanation\n\nObserved values remain in the evidence table.\n\n"
        for number, source in enumerate(sources, 1):
            text += f"## Sequence {number}\n\n```mermaid\n{source}```\n\n"
        text += "Measured evidence: **42 cycles**, local clock only.\n"
        self.report.write_text(text, encoding="utf-8")
        return text

    def parser_result(self, *results):
        return {"engine": {"name": "test parser", "version": "fixture"},
                "results": list(results)}

    def fake_engine(self, package=None):
        extension = self.directory / "fake npm mermaid"
        library = extension / "dist" / "mermaid.esm.min.mjs"
        library.parent.mkdir(parents=True, exist_ok=True)
        library.write_text("export default {};\n", encoding="utf-8")
        if package is not None:
            metadata = extension / "package.json"
            metadata.parent.mkdir(parents=True, exist_ok=True)
            metadata.write_text(package, encoding="utf-8")
        browser = self.directory / "fake browser"
        browser.write_text("not executed by these tests\n", encoding="utf-8")
        return library, browser

    def browser_response(self, *, warnings=None):
        payload = {"results": [{"ok": True, "warnings": []}],
                   "warnings": warnings or []}
        output = '<pre id="result">' + escape(json.dumps(payload)) + "</pre>"
        return subprocess.CompletedProcess(["fake browser"], 0, stdout=output, stderr="")

    def check(self, result, **kwargs):
        with mock.patch.object(TRACE, "parse_mermaid_blocks", return_value=result) as parser:
            status = TRACE.check_markdown(self.report, **kwargs)
        return status, parser

    def assert_no_images(self):
        for suffix in ("*.svg", "*.png", "*.mmd"):
            self.assertFalse(list(self.directory.rglob(suffix)),
                             "Markdown validation must not create diagram exports")

    def test_valid_markdown_is_unchanged_and_creates_no_artifact(self):
        before = self.write_report(GOOD)
        files = {path for path in self.directory.rglob("*") if path.is_file()}
        status, parser = self.check(self.parser_result({"ok": True}), sanitize=True)

        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 0)
        self.assertIsNone(status["log"])
        self.assertFalse(status["modified"])
        self.assertEqual(self.report.read_text(encoding="utf-8"), before)
        self.assertEqual(files, {path for path in self.directory.rglob("*") if path.is_file()})
        blocks = parser.call_args.args[0]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["source"], GOOD)
        self.assertGreater(blocks[0]["line"], 0)
        self.assertLess(blocks[0]["start"], blocks[0]["end"])
        self.assert_no_images()

    def test_required_full_preset_is_accepted_without_new_log(self):
        preset = json.dumps(TRACE.MERMAID_PRESET, sort_keys=True, separators=(",", ":"))
        source = "%%{init: " + preset + "}%%\n" + GOOD
        before = self.write_report(source)
        status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                               require_preset=True)

        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 0)
        self.assertIsNone(status["log"])
        self.assertFalse(status["modified"])
        self.assertEqual(self.report.read_text(encoding="utf-8"), before)
        self.assertFalse(self.log.exists())
        self.assert_no_images()

    def test_required_gantt_preset_accepts_timeline_without_new_log(self):
        preset = json.dumps(TRACE.GANTT_PRESET, sort_keys=True, separators=(",", ":"))
        source = "%%{init: " + preset + "}%%\n" + GANTT
        before = self.write_report(source)
        status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                               require_preset=True)

        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 0)
        self.assertIsNone(status["log"])
        self.assertFalse(status["modified"])
        self.assertEqual(self.report.read_text(encoding="utf-8"), before)
        self.assertFalse(self.log.exists())
        self.assert_no_images()

    def test_gantt_with_sequence_preset_warns_only_in_log_and_keeps_timeline(self):
        preset = json.dumps(TRACE.MERMAID_PRESET)
        source = "%%{init: " + preset + "}%%\n" + GANTT
        self.write_report(source)
        status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                               require_preset=True)

        published = self.report.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(source, published)
        self.assertIn(".log", published)
        self.assertNotIn("WARNING", published)
        self.assertIn("WARNING", self.log.read_text(encoding="utf-8"))
        self.assert_no_images()

    def test_gantt_word_in_sequence_comment_or_description_does_not_select_timeline_style(self):
        preset = json.dumps(TRACE.MERMAID_PRESET)
        examples = ("%% gantt is only an example word\n" + GOOD,
                    GOOD.replace("sequenceDiagram\n",
                                 "sequenceDiagram\n    accDescr {\ngantt\n    }\n", 1))
        for diagram in examples:
            with self.subTest(diagram=diagram):
                source = "%%{init: " + preset + "}%%\n" + diagram
                before = self.write_report(source)
                status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                                       require_preset=True)

                self.assertEqual(status["errors"], 0)
                self.assertEqual(status["warnings"], 0)
                self.assertIsNone(status["log"])
                self.assertEqual(self.report.read_text(encoding="utf-8"), before)
                self.assert_no_images()

    def test_copied_script_exports_gantt_preset_without_site_packages_or_artifacts(self):
        copied = self.directory / "copied skill" / SCRIPT.name
        copied.parent.mkdir()
        shutil.copy2(SCRIPT, copied)
        unrelated = self.directory / "unrelated workspace"
        unrelated.mkdir()
        files = {path for path in self.directory.rglob("*") if path.is_file()}
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-S", str(copied), "--mermaid-preset", "gantt"],
            cwd=unrelated, env=environment, text=True, capture_output=True, timeout=30)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        preset = json.loads(result.stdout)
        self.assertEqual(preset, TRACE.GANTT_PRESET)
        self.assertIn("gantt", preset)
        self.assertNotIn("sequence", preset)
        self.assertEqual(files, {path for path in self.directory.rglob("*") if path.is_file()})
        self.assert_no_images()

    def test_shortened_required_preset_warns_in_log_and_keeps_diagram(self):
        source = '%%{init: {"theme":"base"}}%%\n' + GOOD
        self.write_report(source)
        status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                               require_preset=True)

        published = self.report.read_text(encoding="utf-8")
        diagnostic = self.log.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(source, published)
        self.assertIn(".log", published)
        self.assertNotIn("WARNING", published)
        self.assertIn("WARNING", diagnostic)
        self.assertIn(source, diagnostic)
        self.assert_no_images()

    def test_missing_required_preset_warns_in_log_and_keeps_diagram(self):
        self.write_report(GOOD)
        status, _ = self.check(self.parser_result({"ok": True}), sanitize=True,
                               require_preset=True)

        published = self.report.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(GOOD, published)
        self.assertIn(".log", published)
        self.assertNotIn("WARNING", published)
        self.assertIn("WARNING", self.log.read_text(encoding="utf-8"))
        self.assert_no_images()

    def test_failed_diagram_is_logged_and_replaced_by_short_reference(self):
        self.write_report(BAD)
        status, _ = self.check(self.parser_result({"ok": False, "error": DIAGNOSTIC}),
                               sanitize=True)

        self.assertEqual(status["errors"], 1)
        self.assertEqual(Path(status["log"]).resolve(), self.log.resolve())
        self.assertTrue(status["modified"])
        published = self.report.read_text(encoding="utf-8")
        diagnostic = self.log.read_text(encoding="utf-8")
        self.assertNotIn("```mermaid", published)
        self.assertNotIn("Parse error", published)
        self.assertNotIn("Parser stack", published)
        self.assertNotIn("IRQs run", published)
        self.assertIn(".log", published)
        self.assertIn("42 cycles", published)
        self.assertIn(DIAGNOSTIC, diagnostic)
        self.assertIn(BAD, diagnostic, "The rejected source must remain recoverable")
        self.assertRegex(diagnostic.lower(), r"line\D+\d+")
        self.assert_no_images()

    def test_mixed_report_preserves_valid_diagram_and_all_evidence(self):
        before = self.write_report(GOOD, BAD)
        status, _ = self.check(self.parser_result({"ok": True},
                                                 {"ok": False, "error": DIAGNOSTIC}),
                               sanitize=True)

        published = self.report.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 1)
        self.assertEqual(published.count("```mermaid"), 1)
        self.assertIn(GOOD, published)
        self.assertNotIn(BAD, published)
        for line in before.splitlines():
            if line.startswith(("#", "Observed values", "Measured evidence")):
                self.assertIn(line, published)
        self.assert_no_images()

    def test_check_without_sanitize_logs_failure_without_editing_report(self):
        before = self.write_report(BAD)
        status, _ = self.check(self.parser_result({"ok": False, "error": DIAGNOSTIC}))

        self.assertEqual(status["errors"], 1)
        self.assertFalse(status["modified"])
        self.assertEqual(self.report.read_text(encoding="utf-8"), before)
        self.assertIn(DIAGNOSTIC, self.log.read_text(encoding="utf-8"))

    def test_parser_infrastructure_failure_withholds_unverified_diagrams(self):
        failures = (RuntimeError("Parser unavailable fixture"),
                    OSError("Browser unavailable fixture"),
                    TimeoutError("Parser timed out fixture"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.write_report(GOOD, GOOD)
                with mock.patch.object(TRACE, "parse_mermaid_blocks", side_effect=failure):
                    status = TRACE.check_markdown(self.report, sanitize=True)
                published = self.report.read_text(encoding="utf-8")
                diagnostic = self.log.read_text(encoding="utf-8")
                self.assertEqual(status["errors"], 0)
                self.assertGreaterEqual(status["warnings"], 1)
                self.assertNotIn("```mermaid", published)
                self.assertNotIn(str(failure), published)
                self.assertIn(str(failure), diagnostic)
                self.assertIn("warning", diagnostic.lower())
                self.assertIn(GOOD, diagnostic)
                self.assert_no_images()

    def test_parser_warning_is_logged_without_diagnostic_text_in_report(self):
        self.write_report(GOOD)
        warning = "Parser compatibility warning fixture with internal details"
        status, _ = self.check(self.parser_result({"ok": True, "warnings": [warning]}),
                               sanitize=True)

        published = self.report.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertGreaterEqual(status["warnings"], 1)
        self.assertIn(GOOD, published)
        self.assertIn(".log", published)
        self.assertNotIn(warning, published)
        self.assertIn(warning, self.log.read_text(encoding="utf-8"))

    def test_global_parser_warning_is_logged_without_publishing_details(self):
        self.write_report(GOOD)
        warning = "Global initialization warning fixture with internal details"
        parsed = self.parser_result({"ok": True})
        parsed["warnings"] = [warning]
        status, _ = self.check(parsed, sanitize=True)

        published = self.report.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(GOOD, published)
        self.assertIn(".log", published)
        self.assertNotIn(warning, published)
        self.assertIn(warning, self.log.read_text(encoding="utf-8"))
        self.assert_no_images()

    def test_malformed_package_metadata_logs_warning_and_keeps_valid_diagram(self):
        self.write_report(GOOD)
        library, browser = self.fake_engine(package="{invalid JSON metadata")
        with mock.patch.object(TRACE.subprocess, "run", return_value=self.browser_response()):
            status = TRACE.check_markdown(self.report, mermaid_js=library,
                                           browser=browser, sanitize=True)

        published = self.report.read_text(encoding="utf-8")
        diagnostic = self.log.read_text(encoding="utf-8")
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(GOOD, published)
        self.assertIn(".log", published)
        self.assertNotIn("metadata", published.lower())
        self.assertIn("metadata", diagnostic.lower())
        self.assertIn("warning", diagnostic.lower())
        self.assert_no_images()

    def test_official_esm_api_preserves_distribution_and_reports_version(self):
        library, browser = self.fake_engine(package='{"name":"mermaid","version":"11.12.0"}')
        content = library.read_bytes()
        with mock.patch.object(TRACE.subprocess, "run", return_value=self.browser_response()) as run:
            result = TRACE.parse_mermaid_blocks([{"source": GOOD}], library, browser)

        self.assertEqual(result["engine"]["version"], "11.12.0")
        self.assertEqual(library.read_bytes(), content)
        self.assertIn('await import("/mermaid/mermaid.esm.min.mjs")', self.browser_page)
        self.assertIn("engine.parse(source)", self.browser_page)
        self.assertNotIn("engine.render", self.browser_page)
        self.assertNotIn("traceMermaid", self.browser_page)
        self.assertEqual(run.call_args.args[0][-1], "http://127.0.0.1:12345/check.html")
        self.assert_no_images()

    def test_configured_paths_work_outside_the_npm_directory(self):
        library, browser = self.fake_engine()
        settings = {"TRACE_MERMAID_JS": str(library), "TRACE_MERMAID_BROWSER": str(browser)}
        with mock.patch.dict(os.environ, settings), mock.patch.object(
                TRACE.subprocess, "run", return_value=self.browser_response()):
            result = TRACE.parse_mermaid_blocks([{"source": GOOD}])
        self.assertEqual(result["engine"]["library"], str(library.resolve()))
        self.assertEqual(result["engine"]["browser"], str(browser))

    def test_distribution_fingerprint_covers_imported_chunks(self):
        library, browser = self.fake_engine()
        chunks = library.parent / "chunks"
        chunks.mkdir()
        chunk = chunks / "sequence.mjs"
        chunk.write_text("export const revision = 1;", encoding="utf-8")
        first, _ = TRACE._mermaid_engine(library, str(browser), "test")
        chunk.write_text("export const revision = 2;", encoding="utf-8")
        second, _ = TRACE._mermaid_engine(library, str(browser), "test")
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["distribution_sha256"], second["distribution_sha256"])

    def test_windows_chrome_installation_is_found_without_path_entry(self):
        program_files = self.directory / "Program Files"
        browser = program_files / "Google/Chrome/Application/chrome.exe"
        browser.parent.mkdir(parents=True)
        browser.write_text("fixture", encoding="utf-8")
        settings = {"PROGRAMFILES": str(program_files)}
        # Exclude macOS installations on the host while simulating Windows.
        original_is_file = Path.is_file
        def is_file(candidate):
            return original_is_file(candidate) if candidate == browser else False
        with mock.patch.dict(os.environ, settings, clear=True), mock.patch.object(
                TRACE.shutil, "which", return_value=None), mock.patch.object(Path, "is_file", is_file):
            self.assertEqual(TRACE._mermaid_browser(), str(browser))

    def test_browser_initialization_warning_reaches_log(self):
        self.write_report(GOOD)
        library, browser = self.fake_engine()
        warning = "Mermaid initialize compatibility warning fixture"
        with mock.patch.object(TRACE.subprocess, "run",
                               return_value=self.browser_response(warnings=[warning])):
            status = TRACE.check_markdown(self.report, mermaid_js=library,
                                           browser=browser, sanitize=True)

        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 1)
        self.assertIn(GOOD, self.report.read_text(encoding="utf-8"))
        self.assertNotIn(warning, self.report.read_text(encoding="utf-8"))
        self.assertIn(warning, self.log.read_text(encoding="utf-8"))
        self.assert_no_images()

    def test_browser_crash_and_timeout_keep_engine_identity_in_log(self):
        library, browser = self.fake_engine()
        failures = (subprocess.CompletedProcess([str(browser)], 134,
                                                stdout="", stderr="Browser crash fixture"),
                    subprocess.TimeoutExpired([str(browser)], 1))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self.write_report(GOOD)
                arguments = ({"side_effect": failure} if isinstance(failure, Exception)
                             else {"return_value": failure})
                with mock.patch.object(TRACE.subprocess, "run", **arguments):
                    status = TRACE.check_markdown(self.report, mermaid_js=library,
                                                   browser=browser, sanitize=True, timeout=1)

                diagnostic = self.log.read_text(encoding="utf-8").rsplit(
                    "=== Trace Data Markdown validation ===", 1)[1]
                self.assertEqual(status["errors"], 0)
                self.assertGreaterEqual(status["warnings"], 1)
                self.assertIn(str(library.resolve()), diagnostic)
                self.assertIn(str(browser), diagnostic)
                self.assertIn(hashlib.sha256(library.read_bytes()).hexdigest(), diagnostic)
                self.assertIn("mermaid.parse", diagnostic)
                self.assertIn(GOOD, diagnostic)
                self.assertNotIn("```mermaid", self.report.read_text(encoding="utf-8"))
                self.assert_no_images()

    def test_custom_log_has_relative_markdown_link(self):
        self.write_report(BAD)
        custom = self.directory / "diagnostics" / "result.log"
        custom.parent.mkdir()
        status, _ = self.check(self.parser_result({"ok": False, "error": DIAGNOSTIC}),
                               sanitize=True, log_path=custom)

        self.assertEqual(Path(status["log"]).resolve(), custom.resolve())
        published = self.report.read_text(encoding="utf-8")
        self.assertIn("diagnostics/result.log", published)
        self.assertNotIn(str(self.directory), published)
        self.assertFalse(self.log.exists())

    def test_existing_log_is_preserved_and_gets_clean_check_summary(self):
        before = self.write_report(GOOD)
        history = "Previous rejected source and diagnostic must survive.\n"
        self.log.write_text(history, encoding="utf-8")
        status, _ = self.check(self.parser_result({"ok": True}))

        diagnostic = self.log.read_text(encoding="utf-8")
        self.assertTrue(diagnostic.startswith(history))
        self.assertGreater(len(diagnostic), len(history))
        self.assertEqual(status["errors"], 0)
        self.assertEqual(status["warnings"], 0)
        self.assertEqual(Path(status["log"]).resolve(), self.log.resolve())
        self.assertEqual(self.report.read_text(encoding="utf-8"), before)

    def test_repeated_sanitization_does_not_duplicate_log_notice(self):
        self.write_report(BAD)
        self.check(self.parser_result({"ok": False, "error": DIAGNOSTIC}), sanitize=True)
        published = self.report.read_text(encoding="utf-8")
        self.check(self.parser_result(), sanitize=True)

        self.assertEqual(self.report.read_text(encoding="utf-8"), published)
        self.assertIn(BAD, self.log.read_text(encoding="utf-8"))
        self.assert_no_images()

    def test_log_write_failure_leaves_report_intact(self):
        before = self.write_report(BAD)
        with mock.patch.object(TRACE, "parse_mermaid_blocks",
                               return_value=self.parser_result({"ok": False,
                                                                "error": DIAGNOSTIC})):
            try:
                status = TRACE.check_markdown(self.report, sanitize=True,
                                               log_path=self.directory)
            except OSError:
                pass
            else:
                self.assertGreater(status["errors"] + status["warnings"], 0)

        self.assertEqual(self.report.read_text(encoding="utf-8"), before)
        self.assert_no_images()

    def test_copied_script_handles_missing_parser_without_site_packages(self):
        self.write_report(GOOD)
        copied = self.directory / "copied skill" / SCRIPT.name
        copied.parent.mkdir()
        shutil.copy2(SCRIPT, copied)
        unrelated = self.directory / "unrelated workspace"
        unrelated.mkdir()
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-S", str(copied), "--markdown", str(self.report),
             "--sanitize", "--mermaid-js", str(self.directory / "missing parser.js"),
             "--browser", str(self.directory / "missing browser")],
            cwd=unrelated, env=environment, text=True, capture_output=True, timeout=30)

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertTrue(self.log.is_file())
        self.assertIn("warning", self.log.read_text(encoding="utf-8").lower())
        published = self.report.read_text(encoding="utf-8")
        self.assertNotIn("```mermaid", published)
        self.assertIn(".log", published)
        self.assert_no_images()


if __name__ == "__main__":
    unittest.main()
