"""Real Mermaid parsing and native DOM checks; never export diagram images."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "trace_release_integration", ROOT / ".agents/skills/trace-visualization/trace_data.py")
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


def example_views():
    """Use synthetic, hardware-independent evidence for each supported view."""
    sequence = {
        "kind": "sequence", "title": "Synthetic worker operation",
        "description": "Observed event order in a synthetic fixture, not elapsed time.",
        "participants": [{"id": "ISR", "label": "Interrupt handler"},
                         {"id": "Task", "label": "Worker task"}],
        "cases": [{"label": "Observed operation", "steps": [
            {"kind": "message", "from": "ISR", "to": "Task", "text": "Notify worker",
             "basis": "observed", "evidence": "synthetic.csv:2"},
            {"kind": "note", "over": ["Task"], "text": "Process captured data",
             "basis": "code", "evidence": "synthetic_worker.c:10"},
        ]}],
    }
    ping = {
        "kind": "ping-pong", "title": "Synthetic acknowledged transfer",
        "description": "Protocol order from a synthetic fixture; independent local clocks.",
        "participants": [{"id": "S", "label": "Producer"},
                         {"id": "M", "label": "Mailbox"},
                         {"id": "R", "label": "Consumer"}],
        "cases": [{"label": "Observed transfer", "steps": [
            {"kind": "message", "from": "S", "to": "M", "text": "Write A",
             "basis": "observed", "evidence": "synthetic.csv:2"},
            {"kind": "message", "from": "R", "to": "M", "text": "Read A and clear",
             "basis": "observed", "evidence": "synthetic.csv:3-4"},
            {"kind": "message", "from": "M", "to": "S", "text": "Completion permits next send",
             "basis": "protocol", "evidence": "synthetic_transport.c:20"},
        ]}],
    }
    comparison = copy.deepcopy(ping)
    comparison.update(kind="comparison", title="Synthetic reference and reuse")
    finding = copy.deepcopy(comparison["cases"][0])
    finding["label"] = "Finding: reuse before completion"
    finding["steps"].insert(1, {
        "kind": "message", "from": "S", "to": "M", "text": "Write B before completion",
        "basis": "observed", "evidence": "synthetic.csv:8", "highlight": True,
    })
    comparison["cases"].append(finding)
    timeline = {
        "kind": "timeline", "title": "Synthetic local receive timeline",
        "description": "Measured local spans and clear events in a synthetic fixture.",
        "scope": "All mapped DSP receives in the synthetic capture", "timebase": "dsp-local",
        "interval_series": [{"label": "Receive spans", "match": {"label": "Entire RX handler"}}],
        "event_series": [{"label": "CLEAR events", "match": {"role": "clear"}}],
    }
    model = TRACE.load_model(HERE / "data/normal-transfer.json")
    model["interval_map"]["rx-2"]["highlight"] = True
    return [("sequence", TRACE.render_mermaid_view(sequence)),
            ("ping-pong", TRACE.render_mermaid_view(ping)),
            ("comparison", TRACE.render_mermaid_view(comparison)),
            ("timeline", TRACE.render_mermaid_view(timeline, model))]


class MermaidIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("TRACE_REQUIRE_BROWSER") != "1":
            raise unittest.SkipTest("Set TRACE_REQUIRE_BROWSER=1 for mandatory real-browser checks")
        # Required mode fails rather than skipping when installation is missing.
        cls.library = TRACE._mermaid_library()
        cls.browser = TRACE._mermaid_browser()

    def test_official_parser_accepts_published_reports_and_full_presets(self):
        reports = sorted((ROOT / "docs/examples").glob("*.md"))
        self.assertTrue(reports, "The published example reports are missing")
        for source in reports:
            with self.subTest(report=source.name):
                original = source.read_bytes()
                self.assertTrue(TRACE._mermaid_blocks(original.decode("utf-8")),
                                "The published report needs native Mermaid graphics")
                with tempfile.TemporaryDirectory(prefix="trace-published-report-") as directory:
                    report = Path(directory) / source.name
                    report.write_bytes(original)
                    result = TRACE.check_markdown(
                        report, mermaid_js=self.library, browser=self.browser,
                        require_preset=True, sanitize=True)
                    diagnostics = result["log"].read_text(encoding="utf-8") if result["log"] else ""
                    self.assertEqual((result["errors"], result["warnings"]), (0, 0), diagnostics)
                    self.assertEqual(report.read_bytes(), original)
                    self.assertEqual(list(Path(directory).iterdir()), [report])

    def test_official_parser_accepts_all_generated_views_and_full_presets(self):
        with tempfile.TemporaryDirectory(prefix="trace-release-parser-") as directory:
            report = Path(directory) / "report.md"
            report.write_text("# Synthetic examples\n\n" + "\n".join(
                markdown for _, markdown in example_views()), encoding="utf-8")
            original = report.read_bytes()
            result = TRACE.check_markdown(report, require_preset=True, sanitize=True)
            self.assertEqual((result["errors"], result["warnings"]), (0, 0))
            self.assertEqual(report.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [report])

    def test_real_parse_error_is_logged_without_leaking_into_explanation(self):
        with tempfile.TemporaryDirectory(prefix="trace-release-diagnostic-") as directory:
            report = Path(directory) / "explanation.md"
            good = example_views()[0][1]
            bad = "```mermaid\nsequenceDiagram\n    S--?R: invalid syntax\n```\n"
            report.write_text("# Synthetic evidence\n\nMeasured values stay here.\n\n" + good + bad,
                              encoding="utf-8")
            result = TRACE.check_markdown(report, sanitize=True)
            self.assertGreater(result["errors"], 0)
            published = report.read_text(encoding="utf-8")
            self.assertIn("Measured values stay here.", published)
            self.assertIn(good, published)
            self.assertNotIn("S--?R", published)
            self.assertNotIn("Parse error", published)
            self.assertEqual(published.count("Errors / warnings: see [log]"), 1)
            log = report.with_suffix(".log").read_text(encoding="utf-8")
            self.assertIn("S--?R", log)
            self.assertIn("distribution_sha256", log)
            self.assertEqual({p.suffix for p in Path(directory).iterdir()}, {".md", ".log"})

    def test_native_dom_preserves_responsive_geometry_and_accepted_styles(self):
        views = [{"kind": kind, "source": TRACE._mermaid_blocks(markdown)[0]["source"]}
                 for kind, markdown in example_views()]
        javascript = r"""
const inputs = INPUTS;
const samples = [];
document.getElementById('result').style.display = 'none';
document.body.style.margin = '0';
for (const [index, input] of inputs.entries()) {
  const host = document.createElement('div');
  host.style.width = '1600px';
  document.body.appendChild(host);
  const rendered = await engine.render('traceReleaseView' + index, input.source);
  host.innerHTML = rendered.svg;
  const svg = host.querySelector('svg');
  const box = svg.viewBox.baseVal;
  const fills = Array.from(svg.querySelectorAll('rect')).map(el => getComputedStyle(el).fill);
  const actors = Array.from(svg.querySelectorAll('text.actor')).map(el => ({
    fill: getComputedStyle(el).fill, weight: getComputedStyle(el).fontWeight
  }));
  const rounded = Array.from(svg.querySelectorAll('rect.actor,rect.task')).some(
    el => parseFloat(getComputedStyle(el).rx) > 0);
  for (const width of [360, 600, 1000, 1600]) {
    host.style.width = width + 'px';
    await new Promise(resolve => setTimeout(resolve, 20));
    const bounds = svg.getBoundingClientRect();
    const clipping = Array.from(svg.querySelectorAll('text')).filter(el => {
      const text = el.getBoundingClientRect();
      return text.width > 0 && (text.left < bounds.left - 2 || text.right > bounds.right + 2);
    }).map(el => el.textContent);
    samples.push({kind: input.kind, width, renderedWidth: bounds.width,
      renderedHeight: bounds.height, ratio: box.width / box.height,
      widthAttribute: svg.getAttribute('width'), fills, actors, rounded, clipping});
  }
  host.remove();
}
return {samples, warnings};
""".replace("INPUTS", json.dumps(views).replace("</", "<\\/"))
        result = TRACE.run_mermaid_browser(javascript, timeout=60, operation="native Mermaid DOM QA")
        expected_version = json.loads((HERE / "package.json").read_text())["devDependencies"]["mermaid"]
        self.assertEqual(result["engine"]["version"], expected_version)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(len(result["samples"]), 16)
        for sample in result["samples"]:
            with self.subTest(kind=sample["kind"], width=sample["width"]):
                self.assertGreater(sample["renderedWidth"], 0)
                self.assertLessEqual(sample["renderedWidth"], sample["width"] + 1)
                self.assertEqual(sample["widthAttribute"], "100%")
                self.assertAlmostEqual(sample["renderedWidth"] / sample["renderedHeight"],
                                       sample["ratio"], delta=0.02)
                self.assertEqual(sample["clipping"], [])
                self.assertTrue(sample["rounded"])
                if sample["kind"] in {"ping-pong", "comparison"}:
                    for color in ("rgb(27, 107, 73)", "rgb(64, 83, 106)", "rgb(29, 94, 150)"):
                        self.assertIn(color, sample["fills"])
                if sample["kind"] == "timeline":
                    self.assertIn("rgb(29, 94, 150)", sample["fills"])
                    self.assertIn("rgb(191, 73, 54)", sample["fills"])
                else:
                    self.assertTrue(sample["actors"])
                    for actor in sample["actors"]:
                        self.assertEqual(actor, {"fill": "rgb(255, 255, 255)", "weight": "700"})


if __name__ == "__main__":
    unittest.main()
