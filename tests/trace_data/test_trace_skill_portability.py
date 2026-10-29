"""Exercise the single copied script with external evidence and no repository."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
SKILL = REPOSITORY / ".agents/skills/trace-visualization"
FIXTURES = Path(__file__).resolve().parent / "data"


class TraceSkillPortabilityTests(unittest.TestCase):
    def test_three_file_release_and_version_match_the_skill(self):
        files = {path.relative_to(SKILL).as_posix() for path in SKILL.rglob("*") if path.is_file()}
        self.assertEqual(files, {"SKILL.md", "references/drawing.md", "trace_data.py"})
        version = re.search(r'^  version: "([^"]+)"$',
                            (SKILL / "SKILL.md").read_text(encoding="utf-8"), re.M)[1]
        result = self.invoke("--version", no_site=True)
        self.assert_success(result)
        self.assertEqual(result.stdout.strip(), f"Trace Data {version}")
        self.assertFalse(list(self.work.iterdir()))

    def test_documented_minimal_example_runs_without_extra_artifacts(self):
        drawing = (SKILL / "references/drawing.md").read_text(encoding="utf-8")
        example = re.search(r'```python\n(.*?)\n```', drawing, re.S)[1]
        shutil.copy2(self.script, self.work / "trace_data.py")
        before = {path for path in self.work.rglob("*") if path.is_file()}
        result = subprocess.run([sys.executable, "-S", "-c", example], cwd=self.work,
                                env=self.environment, text=True, capture_output=True, timeout=30)
        self.assert_success(result)
        self.assertTrue(result.stdout.startswith("```mermaid\n"))
        self.assertEqual(before, {path for path in self.work.rglob("*") if path.is_file()})

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="trace skill isolated ")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.skill = self.directory / "copied-skill"
        self.skill.mkdir()
        self.script = self.skill / "trace_data.py"
        shutil.copy2(SKILL / "trace_data.py", self.script)
        self.inputs = self.directory / "external-inputs"
        shutil.copytree(FIXTURES, self.inputs)
        self.work = self.directory / "unrelated-workspace"
        self.work.mkdir()
        self.environment = dict(os.environ)
        self.environment.pop("PYTHONPATH", None)
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"

    def invoke(self, *args, no_site=False, script=None):
        command = [sys.executable]
        if no_site:
            command.append("-S")
        command.extend([str(script or self.script), *map(str, args)])
        return subprocess.run(command, cwd=self.work, env=self.environment,
                              text=True, capture_output=True, timeout=30)

    def example(self, name):
        return self.inputs / f"{name}.json"

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validation_works_without_site_packages_from_an_unrelated_directory(self):
        before = {path: path.read_bytes() for path in self.directory.rglob("*")
                  if path.is_file()}
        for name, counts in (("early-clear", "6 events, 1 intervals"),
                             ("local-cycles", "5 events, 2 intervals"),
                             ("normal-transfer", "10 events, 2 intervals")):
            with self.subTest(scenario=name):
                result = self.invoke("--analysis", self.example(name),
                                     "--validate-only", no_site=True)
                self.assert_success(result)
                self.assertIn(counts, result.stdout)
        self.assertEqual(before, {path: path.read_bytes() for path in self.directory.rglob("*")
                                  if path.is_file()})

    def test_schema_is_available_without_analysis_or_site_packages(self):
        before = {path for path in self.directory.rglob("*") if path.is_file()}
        result = self.invoke("--schema", no_site=True)
        self.assert_success(result)
        self.assertIn("schema_version", result.stdout)
        self.assertIn("timebases", result.stdout)
        self.assertIn("source", result.stdout)
        self.assertEqual(before, {path for path in self.directory.rglob("*") if path.is_file()})

    def test_mermaid_preset_is_available_without_analysis_or_site_packages(self):
        before = {path for path in self.directory.rglob("*") if path.is_file()}
        result = self.invoke("--mermaid-preset", no_site=True)
        self.assert_success(result)
        preset = json.loads(result.stdout)
        self.assertIsInstance(preset["sequence"], dict)
        self.assertGreater(preset["sequence"]["messageFontSize"], 0)
        self.assertIsInstance(preset["themeVariables"], dict)
        self.assertEqual(before, {path for path in self.directory.rglob("*") if path.is_file()})

    def test_validation_still_rejects_a_changed_csv_without_graphics(self):
        analysis = self.example("early-clear")
        data = json.loads(analysis.read_text())
        capture = analysis.parent / data["source"]["csv"]
        capture.write_bytes(capture.read_bytes() + b"\n")
        result = self.invoke("--analysis", analysis, "--validate-only", no_site=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source CSV changed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_standalone_requires_an_explicit_analysis_instead_of_a_demo_default(self):
        result = self.invoke("--validate-only", no_site=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--analysis", result.stderr)
        self.assertFalse(list(self.directory.rglob("*.svg")))

    def test_standalone_rejects_legacy_input_with_a_schema_diagnostic(self):
        analysis = self.work / "legacy.json"
        analysis.write_text(json.dumps({"csv": "historical.csv", "csv_sha256": "0" * 64}))
        result = self.invoke("--analysis", analysis, "--validate-only", no_site=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema_version", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_validation_ignores_legacy_layout_but_checks_source(self):
        analysis = self.example("early-clear")
        data = json.loads(analysis.read_text())
        data.update(detail="unused image layout", overview="unused image layout")
        analysis.write_text(json.dumps(data))
        self.assert_success(self.invoke("--analysis", analysis, "--validate-only", no_site=True))
        data["events"][0]["line"] = 99999
        analysis.write_text(json.dumps(data))
        result = self.invoke("--analysis", analysis, "--validate-only", no_site=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing CSV line", result.stderr)

    def test_analysis_without_an_explicit_operation_creates_nothing(self):
        before = {path: path.read_bytes() for path in self.directory.rglob("*")
                  if path.is_file()}
        result = self.invoke("--analysis", self.example("local-cycles"), no_site=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("no output is implicit", result.stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in self.directory.rglob("*")
                                  if path.is_file()})

    def test_image_options_are_not_part_of_the_portable_cli(self):
        for option in ("--svg", "--png"):
            with self.subTest(option=option):
                output = self.work / ("output." + option[2:])
                result = self.invoke("--analysis", self.example("local-cycles"),
                                     option, output, no_site=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("unrecognized arguments", result.stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
