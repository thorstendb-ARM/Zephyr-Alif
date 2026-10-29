"""Check capture evidence independently of diagram layout or board access.

Synthetic fixtures cover local clocks, partial intervals, mapped CSV columns and
source identity. They do not provide evidence of hardware behavior.
"""

import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
FIXTURES = HERE / "data"
SCRIPT = REPOSITORY / ".agents/skills/trace-visualization/trace_data.py"
SPEC = importlib.util.spec_from_file_location("trace_evidence", SCRIPT)
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)


class PublishedCaptureTests(unittest.TestCase):
    def test_reports_reference_their_original_sibling_csv_and_matching_hash(self):
        directory = REPOSITORY / "docs/examples"
        reports = sorted(directory.glob("*.md"))
        self.assertTrue(reports, "The published example reports are missing")
        self.assertEqual({report.with_suffix(".csv") for report in reports},
                         set(directory.glob("*.csv")),
                         "Each published report needs its original sibling CSV")
        for report in reports:
            with self.subTest(report=report.name):
                text = report.read_text(encoding="utf-8")
                prose = re.sub(r"^```[^\n]*\n.*?^```[ \t]*$", "", text, flags=re.M | re.S)
                capture = report.with_suffix(".csv")
                references = set()
                for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", prose):
                    url = urlsplit(target)
                    if Path(unquote(url.path)).suffix.lower() == ".csv":
                        self.assertFalse(url.scheme or url.netloc,
                                         "Capture evidence must be retained locally")
                        references.add((report.parent / unquote(url.path)).resolve())
                self.assertEqual(references, {capture.resolve()},
                                 "The report must link to its original sibling CSV")
                documented = re.findall(r"CSV SHA-256:\s*`([0-9a-f]{64})`", prose)
                self.assertEqual(documented, [hashlib.sha256(capture.read_bytes()).hexdigest()],
                                 "The recorded capture hash must match the preserved CSV")


class TraceEvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="trace-evidence-test-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def data(self, name="early-clear"):
        data = json.loads((FIXTURES / f"{name}.json").read_text())
        data["source"]["csv"] = str(FIXTURES / data["source"]["csv"])
        return data

    def load(self, data):
        path = self.directory / "analysis.json"
        path.write_text(json.dumps(data))
        return MODEL.load_model(path)

    def rewrite_capture(self, data, change):
        with Path(data["source"]["csv"]).open(newline="") as source:
            reader = csv.DictReader(source)
            fields, rows = reader.fieldnames, list(reader)
        change(rows)
        path = self.directory / "changed.csv"
        with path.open("w", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        data["source"]["csv"] = str(path)
        data["source"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_early_clear_keeps_local_event_time_and_handler_duration_separate(self):
        model = MODEL.load_model(FIXTURES / "early-clear.json")
        self.assertEqual(model["interval_map"]["rx"]["duration_cycles"], 1600)
        self.assertAlmostEqual(model["interval_map"]["rx"]["duration"], 1.6)
        self.assertAlmostEqual(model["event_map"]["clear"]["local_value"], 0.05)
        self.assertTrue(Path(model["source"]["csv"]).is_absolute())

    def test_unknown_clock_keeps_cycles_negative_local_time_and_partial_span(self):
        model = MODEL.load_model(FIXTURES / "local-cycles.json")
        self.assertEqual(model["event_map"]["sample"]["local_value"], -20)
        complete = model["interval_map"]["complete"]
        self.assertEqual((complete["duration"], complete["unit"]), (120, "cycles"))
        partial = model["interval_map"]["partial"]
        self.assertTrue(partial["partial"])
        self.assertIsNone(partial["duration"])
        self.assertIsNone(partial["duration_cycles"])

    def test_custom_columns_names_channels_and_distinct_clocks(self):
        model = MODEL.load_model(FIXTURES / "normal-transfer.json")
        self.assertEqual(model["event_map"]["send-2"]["channel"], "BLUE")
        self.assertEqual(model["event_map"]["send-2"]["cycles"], 96000)
        self.assertEqual(model["event_map"]["send-2"]["local_value"], 1)
        self.assertEqual(model["event_map"]["entry-2"]["local_value"], 1)
        self.assertEqual(model["interval_map"]["rx-1"]["duration"], 0.25)
        self.assertEqual(model["interval_map"]["rx-2"]["duration"], 0.3)

    def test_stale_capture_hash_is_rejected(self):
        data = self.data()
        data["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source CSV changed"):
            self.load(data)

    def test_wrong_stream_is_rejected(self):
        data = self.data()
        data["timebases"][0]["stream"] = 99
        with self.assertRaisesRegex(ValueError, "Core/stream mismatch"):
            self.load(data)

    def test_wrong_raw_fields_or_missing_csv_line_are_rejected(self):
        for field, value in (("type", "exception"), ("index", 77), ("value", "0xBB"),
                             ("pc", "0xFFFF"), ("line", 99), ("cycles", 1100)):
            with self.subTest(field=field):
                data = self.data()
                data["events"][0][field] = value
                with self.assertRaises(ValueError):
                    self.load(data)

    def test_decimal_and_hexadecimal_evidence_are_equivalent(self):
        data = self.data()
        data["events"][0].update(value=170, pc=4112, index="0x7")
        model = self.load(data)
        self.assertEqual(model["event_map"]["send-1"]["cycles"], 1000)

    def test_intervals_cannot_subtract_independent_clocks(self):
        data = self.data()
        data["intervals"][0]["start"] = "send-1"
        with self.assertRaisesRegex(ValueError, "clock domains or epochs"):
            self.load(data)

    def test_same_stream_in_different_epochs_is_not_one_clock(self):
        data = self.data()
        later = copy.deepcopy(data["timebases"][1])
        later.update(id="worker-after-reset", epoch="capture-2")
        data["timebases"].append(later)
        next(event for event in data["events"] if event["id"] == "rx-exit")["timebase"] = later["id"]
        with self.assertRaisesRegex(ValueError, "clock domains or epochs"):
            self.load(data)

    def test_reversed_endpoints_and_fabricated_durations_are_rejected(self):
        for change in (lambda span: span.update(start="rx-exit", end="rx-entry"),
                       lambda span: span.update(duration=25),
                       lambda span: span.update(duration_cycles=999)):
            data = self.data()
            change(data["intervals"][0])
            with self.assertRaises(ValueError):
                self.load(data)

    def test_partial_interval_cannot_claim_duration(self):
        data = self.data("local-cycles")
        data["intervals"][1]["duration"] = 100
        with self.assertRaisesRegex(ValueError, "without both endpoints"):
            self.load(data)

    def test_invalid_references_and_duplicate_ids_are_rejected(self):
        for section, change in (
                ("events", lambda data: data["events"].append(copy.deepcopy(data["events"][0]))),
                ("interval", lambda data: data["intervals"][0].update(start="missing"))):
            with self.subTest(section=section):
                data = self.data()
                change(data)
                with self.assertRaises(ValueError):
                    self.load(data)

    def test_nonpositive_or_nonfinite_clocks_are_rejected(self):
        for frequency in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(frequency=frequency):
                data = self.data()
                data["timebases"][0]["clock_hz"] = frequency
                with self.assertRaisesRegex(ValueError, "positive finite"):
                    self.load(data)

    def test_one_csv_record_cannot_be_counted_as_two_events(self):
        data = self.data()
        duplicate = dict(data["events"][0], id="invented-second-send")
        data["events"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate observation of CSV line"):
            self.load(data)

    def test_decoder_record_cannot_be_a_program_milestone(self):
        data = self.data()
        self.rewrite_capture(data, lambda rows: rows[0].update(type="info", note="Decoder status"))
        data["events"][0]["type"] = "info"
        with self.assertRaisesRegex(ValueError, "decoder record, not a program event"):
            self.load(data)

    def test_observed_values_cannot_be_replaced_by_wrong_local_time(self):
        data = self.data()
        data["events"][0]["local_value"] = 100
        with self.assertRaisesRegex(ValueError, "does not match the source"):
            self.load(data)

    def test_decoder_messages_remain_visible_in_quality(self):
        data = self.data()
        self.rewrite_capture(data, lambda rows: rows.append({
            "cycles": "0", "stream": "0", "type": "info", "index": "", "value": "",
            "pc": "", "address": "", "note": "6 bytes skipped at end of capture"}))
        model = self.load(data)
        self.assertTrue(any("6 bytes skipped" in note for note in model["quality"]["notes"]))
        self.assertEqual(model["quality"]["decoder_records"][0]["type"], "info")

    def test_measurement_spanning_known_trace_loss_is_rejected(self):
        data = self.data()
        # The completion record lies physically inside the receiver interval.
        self.rewrite_capture(data, lambda rows: rows[3].update(
            stream="2", cycles="500100", type="overflow", note="Trace data lost"))
        data["events"] = [event for event in data["events"] if event["id"] != "completion"]
        with self.assertRaisesRegex(ValueError, "spans decoder overflow"):
            self.load(data)


if __name__ == "__main__":
    unittest.main()
