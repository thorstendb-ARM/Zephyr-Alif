"""Check reusable Mermaid view semantics without producing image artifacts.

These tests check selection coverage, local coordinates and supplied protocol
steps. Mermaid syntax and browser appearance are separate integration checks.
"""

import copy
import csv
import hashlib
import importlib.util
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
SCRIPT = REPOSITORY / ".agents/skills/trace-visualization/trace_data.py"
FIXTURES = Path(__file__).resolve().parent / "data"
SPEC = importlib.util.spec_from_file_location("trace_views", SCRIPT)
TRACE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACE)


def make_timeline_capture(directory):
    """Write synthetic local clocks and twelve spaced operations, never hardware data."""
    directory = Path(directory)
    capture = directory / "timeline.csv"
    analysis = directory / "timeline.json"
    origin, frequency = 120_000_000, 120_000_000
    timebases = [
        {"id": "worker-local", "label": "Worker CPU", "stream": 4,
         "origin_cycles": origin, "clock_hz": frequency},
        {"id": "producer-local", "label": "Producer CPU", "stream": 9,
         "origin_cycles": 8000, "clock_hz": 48_000_000},
    ]
    streams = {item["id"]: item["stream"] for item in timebases}
    rows, events, intervals = [], [], []

    def event(identifier, timebase, cycles, label, role="event", channel="blue"):
        rows.append({"cycles": cycles, "stream": streams[timebase], "type": "dwt",
                     "index": 2, "value": 1, "pc": "0x1000", "address": "", "note": ""})
        events.append({"id": identifier, "timebase": timebase, "line": len(rows) + 1,
                       "label": label, "role": role, "channel": channel,
                       "type": "dwt", "index": 2, "value": 1})

    # A valid but unselected channel must not change the plotted origin/coverage.
    event("orange.entry", "worker-local", origin - 600_000, "RX entry", channel="orange")
    event("orange.exit", "worker-local", origin - 120_000, "RX exit", channel="orange")
    intervals.append({"id": "orange.rx", "start": "orange.entry", "end": "orange.exit",
                      "label": "Entire RX handler"})
    for number, start_ms in enumerate((0, 15, 31, 64, 78, 95, 113, 132, 180, 200, 219, 241), 1):
        duration_ms = {3: 18, 8: 34}.get(number, 4)
        start = origin + start_ms * 120_000
        end = start + duration_ms * 120_000
        event(f"producer.send.{number}", "producer-local", 8000 + (number - 1) * 500_000,
              "Publish blue", role="send")
        event(f"worker.rx.{number}.entry", "worker-local", start, "RX entry")
        event(f"worker.clear.{number}", "worker-local", end - 12_000, "Clear blue", role="clear")
        event(f"worker.rx.{number}.exit", "worker-local", end, "RX exit")
        intervals.append({"id": f"worker.rx.{number}", "start": f"worker.rx.{number}.entry",
                          "end": f"worker.rx.{number}.exit", "label": "Entire RX handler",
                          "occurrence": number, "highlight": number in {3, 8}})
    with capture.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    analysis.write_text(json.dumps({
        "schema_version": 1, "title": "Synthetic twelve-operation capture",
        "source": {"csv": capture.name, "sha256": hashlib.sha256(capture.read_bytes()).hexdigest(),
                   "origin": "synthetic", "target": "Offline protocol model"},
        "timebases": timebases, "events": events, "intervals": intervals,
    }), encoding="utf-8")
    return analysis


def metadata(markdown):
    line = next(line for line in markdown.splitlines()
                if line.startswith("%% trace-view: "))
    return json.loads(line.removeprefix("%% trace-view: "))


def tasks(markdown):
    """Read generated Gantt records while ignoring directives and comments."""
    result = []
    for line in markdown.splitlines():
        match = re.fullmatch(r"\s*(.*?)\s+:\s*(.+)", line)
        if not match or line.lstrip().startswith("%%"):
            continue
        fields = [field.strip() for field in match[2].split(",")]
        if len(fields) < 3 or not re.fullmatch(r"-?\d+", fields[-2]):
            continue
        if not re.fullmatch(r"-?\d+|0ms", fields[-1]):
            continue
        result.append({"label": match[1], "flags": fields[:-3],
                       "start": int(fields[-2]), "end": fields[-1]})
    return result


class TraceViewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="trace synthetic timeline ")
        self.addCleanup(directory.cleanup)
        self.capture = make_timeline_capture(directory.name)

    def timeline(self):
        return {
            "kind": "timeline",
            "title": "Blue-channel receive events",
            "description": "Observed entry/exit spans and clear events on one local clock.",
            "scope": "All mapped blue-channel operations in the synthetic run",
            "timebase": "worker-local",
            "interval_series": [{"label": "RX IRQ spans", "match": {
                "label": "Entire RX handler", "channel": "blue"}}],
            "event_series": [{"label": "CLEAR events", "match": {
                "role": "clear", "channel": "blue"}}],
        }

    def sequence(self, kind="ping-pong"):
        return {
            "kind": kind,
            "title": "Mailbox operation",
            "description": "Schematic protocol order using supplied evidence.",
            "participants": [{"id": "S", "label": "Producer"},
                             {"id": "M", "label": "Mailbox"},
                             {"id": "R", "label": "Consumer"}],
            "cases": [{"label": "Observed exchange", "steps": [
                {"kind": "message", "from": "S", "to": "M",
                 "text": "Write A", "evidence": "capture.csv:2",
                 "basis": "observed"},
                {"kind": "message", "from": "R", "to": "M",
                 "text": "Read A", "evidence": "capture.csv:4",
                 "basis": "observed"},
            ]}],
        }

    def test_full_timeline_keeps_all_intervals_and_clear_events(self):
        model = TRACE.load_model(self.capture)
        output = TRACE.render_mermaid_view(self.timeline(), model)
        selection = metadata(output)
        expected_intervals = {f"worker.rx.{number}" for number in range(1, 13)}
        expected_events = {f"worker.clear.{number}" for number in range(1, 13)}
        self.assertEqual(set(selection["intervals"]), expected_intervals)
        self.assertEqual(set(selection["events"]), expected_events)
        self.assertEqual(len(selection["intervals"]), 12)
        self.assertEqual(len(selection["events"]), 12)
        self.assertEqual(selection["timebase"], "worker-local")
        self.assertEqual(selection["origin_cycles"], 120_000_000)
        self.assertEqual(selection["unit"], "ms")

        records = tasks(output)
        intervals = [task for task in records if "milestone" not in task["flags"]]
        milestones = [task for task in records if "milestone" in task["flags"]]
        self.assertEqual((len(intervals), len(milestones)), (12, 12))
        expected_positions = []
        expected_highlights = set()
        for identifier in expected_intervals:
            span = model["interval_map"][identifier]
            start = model["event_map"][span["start"]]["cycles"]
            end = model["event_map"][span["end"]]["cycles"]
            positions = tuple(round((cycle - selection["origin_cycles"]) / 120)
                              for cycle in (start, end))
            expected_positions.append(positions)
            if span.get("highlight"):
                expected_highlights.add(positions[0])
        self.assertEqual(sorted((task["start"], int(task["end"])) for task in intervals),
                         sorted(expected_positions))
        self.assertEqual({task["start"] for task in intervals if "crit" in task["flags"]},
                         expected_highlights)
        self.assertEqual(len(expected_highlights), 2)
        self.assertEqual(min(task["start"] for task in records), 0)
        self.assertEqual(max(int(task["end"]) for task in intervals), 245000)
        self.assertIn("section CLEAR events", output)
        self.assertNotIn("flowchart", output)

    def test_explicit_window_keeps_real_spacing_inside_user_range(self):
        model = TRACE.load_model(self.capture)
        view = self.timeline()
        view["window"] = {
            "start": "worker.rx.2.entry", "end": "worker.rx.3.exit",
            "reason": "The user explicitly requested exchanges 2 through 3.",
        }
        output = TRACE.render_mermaid_view(view, model)
        selection = metadata(output)
        self.assertEqual(set(selection["intervals"]), {"worker.rx.2", "worker.rx.3"})
        intervals = [task for task in tasks(output) if "milestone" not in task["flags"]]
        self.assertEqual(min(task["start"] for task in intervals), 0)
        self.assertGreater(max(task["start"] for task in intervals), 0)

    def test_cross_domain_window_cannot_establish_a_shared_axis(self):
        model = TRACE.load_model(self.capture)
        view = self.timeline()
        view["window"] = {
            "start": "producer.send.1", "end": "worker.rx.3.exit",
            "reason": "Invalid attempt to span independent counters.",
        }
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view, model)

    def test_unsupported_selectors_cannot_silently_reduce_the_overview(self):
        model = TRACE.load_model(self.capture)
        for field, value in (("ids", ["worker.rx.2", "worker.rx.3"]),
                             ("limit", 2), ("timebase", "producer-local")):
            with self.subTest(field=field):
                view = self.timeline()
                view["interval_series"][0]["match"][field] = value
                with self.assertRaises(ValueError):
                    TRACE.render_mermaid_view(view, model)

    def test_empty_series_is_rejected_instead_of_inventing_data(self):
        model = TRACE.load_model(self.capture)
        view = self.timeline()
        view["event_series"][0]["match"]["channel"] = "unmapped channel"
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view, model)

    def test_duplicate_series_cannot_draw_the_same_observations_twice(self):
        model = TRACE.load_model(self.capture)
        for field in ("interval_series", "event_series"):
            with self.subTest(field=field):
                view = self.timeline()
                duplicate = copy.deepcopy(view[field][0])
                duplicate["label"] = "Duplicate observation lane"
                view[field].append(duplicate)
                with self.assertRaises(ValueError):
                    TRACE.render_mermaid_view(view, model)

    def test_generic_early_clear_keeps_marker_inside_the_handler(self):
        model = TRACE.load_model(FIXTURES / "early-clear.json")
        view = self.timeline()
        view.update(timebase="worker-local", title="Early clear",
                    scope="All worker receive intervals in the synthetic fixture")
        view["interval_series"][0]["match"] = {"label": "Entire RX handler"}
        view["event_series"][0]["match"] = {"role": "clear", "channel": "7"}
        output = TRACE.render_mermaid_view(view, model)
        selection = metadata(output)
        self.assertEqual(selection["intervals"], ["rx"])
        self.assertEqual(selection["events"], ["clear"])
        self.assertEqual(selection["origin_cycles"], 500000)
        interval, = [task for task in tasks(output) if "milestone" not in task["flags"]]
        marker, = [task for task in tasks(output) if "milestone" in task["flags"]]
        self.assertLess(interval["start"], marker["start"])
        self.assertLess(marker["start"], int(interval["end"]))
        self.assertNotIn("M55", output)
        self.assertNotIn("30 ms", output)

    def test_unknown_clock_retains_cycles_and_uses_first_plotted_observation(self):
        model = TRACE.load_model(FIXTURES / "local-cycles.json")
        view = self.timeline()
        view.update(timebase="sensor-epoch-1", title="Sensor IRQ",
                    scope="Complete handler and its preceding observed sample")
        view["interval_series"][0]["match"] = {"label": "Complete IRQ handler"}
        view["event_series"][0]["match"] = {"label": "Sample ready"}
        output = TRACE.render_mermaid_view(view, model)
        selection = metadata(output)
        self.assertEqual(selection["unit"], "cycles")
        self.assertEqual(selection["origin_cycles"], model["event_map"]["sample"]["cycles"])
        self.assertEqual(selection["intervals"], ["complete"])
        self.assertEqual(selection["events"], ["sample"])
        self.assertIn("axisFormat %s cycles", output)
        self.assertEqual(min(task["start"] for task in tasks(output)), 0)

    def test_partial_interval_draws_only_the_observed_endpoint(self):
        model = TRACE.load_model(FIXTURES / "local-cycles.json")
        view = self.timeline()
        view.update(timebase="sensor-epoch-1", title="Incomplete sensor IRQ",
                    scope="The mapped handler has no captured exit")
        view["interval_series"][0]["match"] = {"label": "Open IRQ handler"}
        view["event_series"] = []
        output = TRACE.render_mermaid_view(view, model)
        selection = metadata(output)
        self.assertEqual(selection["intervals"], ["partial"])
        self.assertEqual(selection["events"], [])
        self.assertEqual(selection["origin_cycles"], model["event_map"]["entry-2"]["cycles"])
        marker, = tasks(output)
        self.assertIn("milestone", marker["flags"])
        self.assertIn("(open)", marker["label"])
        self.assertEqual((marker["start"], marker["end"]), (0, "0ms"))

    def test_generators_include_the_complete_accepted_presets(self):
        outputs = [
            (TRACE.render_mermaid_view(self.sequence()), "sequence"),
            (TRACE.render_mermaid_view(self.timeline(), TRACE.load_model(self.capture)), "gantt"),
        ]
        for output, kind in outputs:
            with self.subTest(kind=kind):
                directive, = re.findall(r"^%%\{init: (.+)\}%%$", output, re.M)
                self.assertEqual(json.loads(directive), TRACE.mermaid_preset(kind))

    def test_sequence_does_not_add_a_reply_or_completion(self):
        view = self.sequence()
        output = TRACE.render_mermaid_view(view)
        arrows = re.findall(r"^\s*([A-Za-z_]\w*)\s*(?:--?>>)\s*([A-Za-z_]\w*):", output, re.M)
        self.assertEqual(arrows, [("S", "M"), ("R", "M")])
        self.assertNotIn("PONG", output)
        self.assertNotIn("ACK", output)
        self.assertNotRegex(output, re.compile(r"^\s*(?:par|alt|else)(?:\s|$)", re.M))
        self.assertLess(output.index("participant S"), output.index("participant M"))
        self.assertLess(output.index("participant M"), output.index("participant R"))

    def test_generic_sequence_keeps_only_the_observed_actors_and_case(self):
        view = self.sequence("sequence")
        view["participants"] = [{"id": "IRQ", "label": "Interrupt handler"},
                                {"id": "Worker", "label": "Worker task"}]
        view["cases"] = [{"label": "Observed wakeup", "steps": [
            {"kind": "message", "from": "IRQ", "to": "Worker",
             "text": "Wake worker", "evidence": "capture.csv:8",
             "basis": "observed"},
        ]}]
        output = TRACE.render_mermaid_view(view)
        self.assertEqual(metadata(output)["kind"], "sequence")
        self.assertEqual(re.findall(r"^\s*participant (\w+) as ", output, re.M),
                         ["IRQ", "Worker"])
        self.assertEqual(re.findall(r"^\s*(\w+)(?:--?>>)(\w+):", output, re.M),
                         [("IRQ", "Worker")])
        self.assertEqual(re.findall(r"^\s*Note over .+: (.+)$", output, re.M),
                         ["Observed wakeup"])

    def test_single_actor_sequence_keeps_state_note_and_self_message(self):
        view = self.sequence("sequence")
        view["participants"] = [{"id": "Task", "label": "Worker task"}]
        view["cases"] = [{"label": "Observed state change", "steps": [
            {"kind": "note", "over": ["Task"], "text": "State is waiting",
             "evidence": "capture.csv:3", "basis": "observed"},
            {"kind": "message", "from": "Task", "to": "Task",
             "text": "Enter running state", "evidence": "capture.csv:4",
             "basis": "observed"},
        ]}]
        output = TRACE.render_mermaid_view(view)
        self.assertEqual(re.findall(r"^\s*participant (\w+) as ", output, re.M),
                         ["Task"])
        self.assertEqual(re.findall(r"^\s*Note over ([^:]+): (.+)$", output, re.M),
                         [("Task", "Observed state change"), ("Task", "State is waiting")])
        self.assertEqual(re.findall(r"^\s*(\w+)(?:--?>>)(\w+):", output, re.M),
                         [("Task", "Task")])

    def test_sequence_requires_a_source_for_each_step(self):
        view = self.sequence()
        view["cases"][0]["steps"][0].pop("evidence")
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view)

    def test_sequence_rejects_undeclared_participants(self):
        view = self.sequence()
        view["cases"][0]["steps"][0]["to"] = "other-core"
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view)

    def test_ping_pong_roles_cannot_be_reordered(self):
        view = self.sequence()
        view["participants"].reverse()
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view)

    def test_comparison_requires_two_visible_scenarios_with_shared_participants(self):
        view = self.sequence("comparison")
        with self.assertRaises(ValueError):
            TRACE.render_mermaid_view(view)
        second = copy.deepcopy(view["cases"][0])
        second["label"] = "Delayed operation"
        second["steps"][0]["highlight"] = True
        view["cases"].append(second)
        output = TRACE.render_mermaid_view(view)
        self.assertIn("Observed exchange", output)
        self.assertIn("Delayed operation", output)
        self.assertEqual(len(re.findall(r"^\s*participant ", output, re.M)), 3)
        self.assertEqual(len(re.findall(r"^\s*[SMR](?:--?>>)[SMR]:", output, re.M)), 4)

    def test_unsafe_label_cannot_inject_a_mermaid_statement(self):
        view = self.sequence()
        view["cases"][0]["steps"][0]["text"] = "Write A; pending\nR->>S: forged reply"
        try:
            output = TRACE.render_mermaid_view(view)
        except ValueError:
            # Rejecting unsafe user text is also safe, as long as it is not emitted.
            return
        self.assertNotIn("Write A; pending", output)
        self.assertNotIn("\nR->>S: forged reply", output)
        arrows = re.findall(r"^\s*([A-Za-z_]\w*)(?:--?>>)([A-Za-z_]\w*):", output, re.M)
        self.assertEqual(arrows, [("S", "M"), ("R", "M")])

    def test_copied_cli_accepts_stdin_without_site_packages_or_output_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="trace view standalone ") as directory:
            work = Path(directory)
            script = work / "trace_data.py"
            shutil.copy2(SCRIPT, script)
            before = {path for path in work.rglob("*") if path.is_file()}
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            environment.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-S", str(script), "--mermaid-view", "-",
                 "--log", str(work / "explanation.log")],
                cwd=work, env=environment, input=json.dumps(self.sequence()),
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.startswith("```mermaid\n"))
            self.assertIn("sequenceDiagram", result.stdout)
            self.assertEqual(before, {path for path in work.rglob("*") if path.is_file()})

    def test_generation_failure_logs_recovery_input_without_partial_diagram(self):
        with tempfile.TemporaryDirectory(prefix="trace view failure ") as directory:
            work = Path(directory)
            log = work / "explanation.log"
            view = self.sequence()
            view["cases"][0]["steps"][1]["to"] = "undeclared-participant"
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, "-S", str(SCRIPT), "--mermaid-view", "-", "--log", str(log)],
                cwd=work, env=environment, input=json.dumps(view),
                text=True, capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(log), result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn("undeclared-participant", result.stderr)
            self.assertIn("undeclared-participant", log.read_text())
            self.assertEqual(list(work.iterdir()), [log])

    def test_copied_timeline_cli_validates_external_analysis_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory(prefix="trace timeline standalone ") as directory:
            work = Path(directory)
            script = work / "copied-skill" / "trace_data.py"
            script.parent.mkdir()
            shutil.copy2(SCRIPT, script)
            inputs = work / "external-inputs"
            shutil.copytree(FIXTURES, inputs)
            analysis = inputs / "normal-transfer.json"
            unrelated = work / "unrelated-workspace"
            unrelated.mkdir()
            view = self.timeline()
            view.update(timebase="dsp-local", title="DSP mailbox receives",
                        scope="All mapped receives in the independent synthetic capture")
            view["interval_series"][0]["match"] = {"label": "Entire RX handler"}
            view["event_series"][0]["match"] = {"role": "clear"}
            before = {path for path in work.rglob("*") if path.is_file()}
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            environment.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-S", str(script), "--mermaid-view", "-",
                 "--analysis", str(analysis), "--log", str(unrelated / "explanation.log")],
                cwd=unrelated, env=environment, input=json.dumps(view),
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selection = metadata(result.stdout)
            self.assertEqual(set(selection["intervals"]), {"rx-1", "rx-2"})
            self.assertEqual(set(selection["events"]), {"clear-1", "clear-2"})
            self.assertEqual(len(tasks(result.stdout)), 4)
            self.assertEqual(before, {path for path in work.rglob("*") if path.is_file()})

    def test_generation_log_cannot_modify_capture_even_when_validation_fails(self):
        with tempfile.TemporaryDirectory(prefix="trace protected input ") as directory:
            work = Path(directory)
            analysis = make_timeline_capture(work)
            data = json.loads(analysis.read_text())
            capture = work / data["source"]["csv"]
            before = capture.read_bytes()
            for invalid_hash in (False, True):
                with self.subTest(invalid_hash=invalid_hash):
                    if invalid_hash:
                        data["source"]["sha256"] = "0" * 64
                        analysis.write_text(json.dumps(data))
                    result = subprocess.run(
                        [sys.executable, "-S", str(SCRIPT), "--mermaid-view", "-",
                         "--analysis", str(analysis), "--log", str(capture)],
                        cwd=work, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                        input='{"kind":"timeline","unsupported":true}',
                        text=True, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("log must not overwrite the source CSV", result.stderr)
                    self.assertEqual(capture.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
