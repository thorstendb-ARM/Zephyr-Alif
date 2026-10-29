#!/usr/bin/env python3
"""Generate fixed Mermaid trace views and validate evidence/Markdown with logs.

Markdown checks use Python's standard library plus a local Mermaid browser bundle
and Chrome/Chromium, with no rendering. Evidence validation and Mermaid generation
need only Python 3.10 or newer. Event meanings and causal associations come from
the analysis, without target defaults. This helper never exports images.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
import tempfile
from textwrap import wrap


VERSION = "0.1.0"
MIN_PYTHON = (3, 10)


SCHEMA_HELP = """Trace data input: schema_version 1

The analysis JSON maps observations to immutable CSV rows. It does not decode
RAW trace or infer register/protocol semantics. IDs are unique in each collection.
Fields ending in ? below are optional; omitted lists default to empty.
Both --validate-only and timeline generation check this same evidence contract.
Legacy overview/detail layout fields are ignored; Mermaid views select the
evidence they need through the separate --view-help contract.

Root: schema_version: 1, source, title, subtitle?, timebases, events,
      intervals?, quality?, metadata?
source: csv, sha256, origin, date?, target?, columns?
timebases[]: id, label, stream, origin_cycles, origin_line?, clock_hz?, epoch?
events[]: id, timebase, line, label, role?, channel?, occurrence?, highlight?,
          expected CSV fields: type?, index?, value?, pc?, address?
intervals[]: id, start, end, label, occurrence?, highlight?
quality: notes: [string, ...]
metadata: object for profile identity, source context and selection rationale

Source and timebases
- source.csv resolves relative to the analysis JSON, independently of the shell
  working directory. source.sha256 must match the exact current CSV bytes.
- source.origin states hardware, synthetic or unknown provenance; synthetic input
  remains visibly labeled. source.date is optional; omit unknown values.
- Default headers: cycles,stream,type,index,value,pc,address,note. Only cycles and
  stream are mandatory; expected raw event fields need matching source columns.
  source.columns maps normalized names to actual headers, e.g. {"cycles":"tick"}.
- Each timebase describes one stream, epoch and clock regime. stream and
  origin_cycles are nonnegative integers. origin_line, when supplied, must match
  its CSV stream and cycles. Unknown frequency is omitted or null; otherwise
  clock_hz is positive and finite.
- Local values are (cycles - origin_cycles) * 1000 / clock_hz in milliseconds,
  or cycles without a known frequency. Negative local positions are retained.
  Independent timebases do not establish cross-core latency or chronology.

Observations and measurements
- Event line counts physical CSV lines, with the header as line 1; start at 2.
  The script checks the stream, row and every supplied expected raw field.
  Decimal and hexadecimal numbers are accepted for raw CSV fields.
- One CSV row is one event; reuse its ID instead of counting it twice. Event
  cycles and displayed values are read/computed from the row, not invented.
- Event roles: event|send|clear. Channel names are strings; occurrence is a
  nonnegative integer. highlight is a boolean emphasis, not a diagnosis.
- Intervals need start and end event IDs on one timebase. Use null for ONE missing
  endpoint; partial spans have no measured duration. Do not supply fabricated
  duration/local_value fields.
- The loader rejects stale hashes, clock-domain subtraction and complete spans
  crossing relevant decoder error/overflow records. Decoder notes remain in quality.

Use --validate-only to check source evidence without creating output files.
The helper verifies supplied rows, not catalog completeness, source semantics or
causal claims. Review those against the capture and source. Inspect the final
native Mermaid separately; validation does not establish a firmware diagnosis
or check all visual issues in the user's viewer.
"""


MERMAID_PRESET = {'theme': 'base',
 'themeVariables': {'fontFamily': 'Arial, sans-serif',
                    'fontSize': '20px',
                    'primaryTextColor': '#102A43',
                    'actorBkg': '#1D5E96',
                    'actorBorder': '#153E63',
                    'actorTextColor': '#FFFFFF',
                    'actorLineColor': '#50657C',
                    'signalColor': '#203248',
                    'signalTextColor': '#203248',
                    'noteBkgColor': '#F5F7FA',
                    'noteBorderColor': '#50657C',
                    'noteTextColor': '#203248',
                    'sequenceNumberColor': '#FFFFFF'},
 'sequence': {'useMaxWidth': True,
              'mirrorActors': False,
              'diagramMarginX': 18,
              'diagramMarginY': 18,
              'actorMargin': 50,
              'width': 125,
              'height': 46,
              'messageMargin': 36,
              'noteMargin': 10,
              'actorFontSize': 20,
              'messageFontSize': 20,
              'noteFontSize': 18,
              'boxMargin': 16,
              'boxTextMargin': 10},
 'themeCSS': 'rect.actor {rx:9px;ry:9px;stroke-width:0!important;} rect.actor[name="S"] '
             '{fill:#1B6B49!important;} rect.actor[name="R"] {fill:#1D5E96!important;} '
             'rect.actor[name="M"] {fill:#40536A!important;} text.actor '
             '{fill:#FFFFFF!important;font-weight:700!important;} .actor-line '
             '{stroke:#A3AFBD!important;stroke-width:1.8px!important;} .messageLine0,.messageLine1 '
             '{stroke-width:3px!important;} .messageLine0 {stroke:#1B6B49!important;} '
             '.messageLine1 {stroke:#1D5E96!important;stroke-dasharray:8 5!important;} '
             '.messageText {fill:#203248!important;font-weight:700!important;} .sequenceNumber '
             '{font-weight:700!important;} rect.note '
             '{rx:7px;ry:7px;stroke:#BEC9D5!important;stroke-width:1.2px!important;} rect.rect '
             '{rx:12px;ry:12px;stroke:#DCE4ED!important;stroke-width:1px!important;} '
             '.messageLine0[data-from="R"] {stroke:#1D5E96!important;}'}


# Approved simple timeline: wide, shallow lanes on one continuous local axis.
# Keep this style fixed across reports: rounded blue spans, red findings, blue
# diamond events, short occurrence labels, left lane captions and light grid.
# useWidth defines internal geometry; useMaxWidth fits it to the page container.
SIMPLE_TIMELINE_PRESET = {
    'theme': 'base',
    'themeVariables': {
        'fontFamily': 'Arial, sans-serif', 'fontSize': '20px',
        'background': '#FFFFFF', 'primaryTextColor': '#203248',
        'sectionBkgColor': '#F2F5F9', 'altSectionBkgColor': '#FFFFFF',
        'sectionBkgColor2': '#FFFFFF', 'gridColor': '#DCE4ED',
        'taskBkgColor': '#1D5E96', 'taskBorderColor': '#1D5E96',
        'taskTextColor': '#FFFFFF', 'taskTextOutsideColor': '#203248',
        'taskTextDarkColor': '#203248', 'taskTextLightColor': '#FFFFFF',
        'critBkgColor': '#BF4936', 'critBorderColor': '#BF4936',
    },
    'gantt': {
        'useMaxWidth': True, 'useWidth': 1400, 'displayMode': 'compact',
        'barHeight': 32, 'barGap': 12, 'topPadding': 44,
        'leftPadding': 180, 'rightPadding': 80, 'gridLineStartPadding': 32,
        'fontSize': 18, 'sectionFontSize': 18, 'numberSectionStyles': 2,
    },
    'themeCSS': ('svg {background:#FFFFFF;} .task {rx:7px;ry:7px;stroke-width:1.5px;} '
                 '.taskText,.taskTextOutsideLeft,.taskTextOutsideRight '
                 '{font-family:Arial,sans-serif!important;font-weight:700!important;} '
                 '.sectionTitle {fill:#203248!important;font-weight:700!important;} '
                 '.titleText {fill:#203248!important;font-family:Arial,sans-serif!important;'
                 'font-size:20px!important;font-weight:700!important;} '
                 '.grid .tick line,.grid .domain {stroke:#DCE4ED!important;} '
                 '.tick text {fill:#50657C!important;font-family:Arial,sans-serif!important;'
                 'font-size:16px!important;}'),
}


# Compatibility name for callers using Mermaid's underlying diagram type.
GANTT_PRESET = SIMPLE_TIMELINE_PRESET


def mermaid_preset(diagram_type="sequence"):
    """Return the complete accepted style for a protocol view or a time axis."""
    if diagram_type in {"timeline", "gantt"}:
        return SIMPLE_TIMELINE_PRESET
    if diagram_type == "sequence":
        return MERMAID_PRESET
    raise ValueError(f"Unsupported Mermaid preset: {diagram_type}")


VIEW_HELP = """Native Mermaid views (JSON via --mermaid-view PATH or - for stdin)

All views: kind, title, description. Output is one fenced Mermaid block with the
complete accepted preset. No image files are written. Diagnosis stays with the
caller; labels, highlights and sequence steps must have reviewed evidence.
Both diagram types use useMaxWidth=true: fit the available page/container width,
up to their intrinsic maximum, preserving aspect ratio and scaling labels too.

timeline: scope, timebase, interval_series?, event_series?
  Fixed simple-timeline style: wide/shallow compact lanes, continuous axis,
  rounded blue ordinary spans, red highlighted spans, blue diamond milestones,
  short IDs, left lane captions, light grid, white background and Arial labels.
  The internal 1400-wide layout fixes 32-high bars, 12 gap and 180 left padding; do not
  restyle per report. Select only the series needed to explain the finding.
  interval_series[]: label, match: {label?, channel?}
  event_series[]: label, match: {label?, channel?, role?}
  Each nonempty selector includes ALL matching observations on that timebase
  from --analysis. channel matches the interval's observed endpoints. No ID lists
  or implicit zoom. CSV hash/rows/clocks are validated before drawing.
  Optional window: {start: eventId, end: eventId, reason: nonempty string} only
  for an explicitly requested range. Crossing intervals are kept whole.
  Origin is the first plotted observation. Units auto-select ms/us/ns for a
  known clock, otherwise cycles. Bars show complete intervals, open intervals
  show only their known endpoint, event series are separate milestone lanes.
  Blue is ordinary, red is explicitly highlighted. Compact lanes retain gaps.

sequence | ping-pong | comparison: participants: [{id, label}], cases: [{label, steps}]
  sequence supports real participants and one observed or explicitly derived
  case, without requiring an IPC transport or an invented comparison case.
  ping-pong requires S/M/R in sender/transport/receiver order, but does NOT
  invent a PONG, reply, clear or acknowledgment.
  comparison requires at least two visibly named cases with shared participants.
  steps[]: kind (message|note), text, evidence, basis
    message: from, to, dashed?: boolean
    note: over: [participantId, ...] (one or two)
    highlight?: boolean
    basis: observed|code|protocol|hypothesis
  Only supplied steps are drawn. Observed labels stay plain; other bases remain
  visibly qualified. Cases are stacked with visible captions, without par/alt.
  Use actual transport semantics and evidence/source references. The drawing
  conveys schematic relationships, not cross-core timing or concurrency.

--log REPORT.log saves generation failures before returning a short diagnostic.
Required for stdin, otherwise defaults to the view JSON's .log path. Successful
generation creates no log. Run --markdown REPORT.md --sanitize --require-preset
and inspect the native preview before delivery; generation is not syntax/QA proof.
"""


def _view_fields(item, allowed, context):
    _object(item, context)
    unknown = set(item) - set(allowed)
    if unknown:
        raise ValueError(f"{context} has unsupported fields: {', '.join(sorted(unknown))}")


def _mermaid_text(value, context, *, multiline=False):
    """Keep labels on one statement and encode Mermaid's special characters."""
    value = _text(value, context)
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"{context} contains control characters")
    parts = value.splitlines() if multiline else [value]
    encoded = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        rows = wrap(part, 40, break_long_words=False, break_on_hyphens=False) if multiline else [part]
        for row in rows:
            encoded.append("".join(f"#{ord(char)};" if char in '&<>:;#%`{}[]\"' else char
                                   for char in row))
    return "<br/>".join(encoded)


def _view_header(diagram_type, metadata):
    return ["```mermaid", "%% trace-view: " + json.dumps(metadata, ensure_ascii=True),
            "%%{init: " + json.dumps(mermaid_preset(diagram_type), separators=(",", ":")) + "}%%"]


def _timeline_view(view, model):
    _view_fields(view, {"kind", "title", "description", "scope", "timebase",
                        "interval_series", "event_series", "window"}, "timeline")
    _text(view.get("scope"), "timeline.scope")
    if model is None or not all(key in model for key in ("event_map", "interval_map", "timebase_map")):
        raise ValueError("timeline requires a CSV-validated analysis model")
    timebase = _reference(view.get("timebase"), model["timebase_map"], "timeline.timebase")
    events = model["event_map"]
    bounds = None
    if "window" in view:
        window = view["window"]
        _view_fields(window, {"start", "end", "reason"}, "timeline.window")
        _text(window.get("reason"), "timeline.window.reason")
        endpoints = [_reference(window.get(key), events, f"window.{key}") for key in ("start", "end")]
        if any(event["timebase"] != timebase["id"] for event in endpoints):
            raise ValueError("timeline window crosses a timebase")
        bounds = tuple(event["cycles"] for event in endpoints)
        if bounds[1] < bounds[0]:
            raise ValueError("timeline window has reversed endpoints")
    lanes, selected, plotted = [], {"intervals": [], "events": []}, []
    for field, collection in (("interval_series", "intervals"), ("event_series", "events")):
        for index, series in enumerate(_list(view.get(field, []), field)):
            context = f"{field}[{index}]"
            _view_fields(series, {"label", "match"}, context)
            label = _mermaid_text(series.get("label"), context + ".label")
            match = series.get("match")
            _view_fields(match, {"label", "channel"} | ({"role"} if collection == "events" else set()),
                         context + ".match")
            if not match:
                raise ValueError(f"{context}.match must be a nonempty semantic selector")
            for key, value in match.items():
                _text(value, context + ".match." + key)
            members = []
            for item in model[collection]:
                if item["timebase"] != timebase["id"]:
                    continue
                points = ([events[item[key]] for key in ("start", "end") if item[key] is not None]
                          if collection == "intervals" else [item])
                if any((any(point.get("channel") != value for point in points) if key == "channel"
                        else item.get(key) != value) for key, value in match.items()):
                    continue
                low, high = min(p["cycles"] for p in points), max(p["cycles"] for p in points)
                if bounds and (high < bounds[0] or low > bounds[1]):
                    continue
                members.append((low, high, item, points))
            if not members:
                raise ValueError(f"{context} has no matching observations on this timebase/window")
            members.sort(key=lambda member: (member[0], member[3][0]["line"]))
            for _, _, item, points in members:
                if item["id"] in selected[collection]:
                    raise ValueError(f"Duplicate {collection} selection: {item['id']}")
                selected[collection].append(item["id"])
                plotted.extend(points)
            lanes.append((label, collection, members))
    if not plotted:
        raise ValueError("timeline requires at least one interval or event series")
    origin = min(event["cycles"] for event in plotted)
    span_cycles = max(event["cycles"] for event in plotted) - origin
    frequency = timebase.get("clock_hz")
    unit, scale = "cycles", 1
    if frequency:
        span_ms = span_cycles * 1000 / frequency
        unit, scale = (("ms", 1000 / frequency) if span_ms >= 10 else
                       ("us", 1000000 / frequency) if span_ms >= .01 else
                       ("ns", 1000000000 / frequency))
    span = span_cycles * scale
    if span * 1000 > 8640000000000000:
        raise ValueError("timeline exceeds JavaScript Date range in the selected unit")
    # Keep ticks integral in the displayed unit, with a minimum 1-unit range.
    tick = next((value for value in (1, 2, 5, 10, 15, 20, 30, 60) if value >= span / 18), 60)
    if span / 18 > 60:
        tick = 60 * math.ceil(span / (18 * 60))
    tick_interval = f"{tick}second" if tick < 60 else f"{tick // 60}minute"
    metadata = {"kind": "timeline", "timebase": timebase["id"], "origin_cycles": origin,
                "unit": unit, "scope": view["scope"], **selected}
    if bounds:
        metadata["window"] = view["window"]
    lines = _view_header("timeline", metadata)
    lines.extend(["gantt", "    title " + _mermaid_text(view["title"], "title"),
                  "    accTitle: " + _mermaid_text(view["title"], "title"),
                  "    accDescr: " + _mermaid_text(view["description"], "description"),
                  "    dateFormat x", f"    axisFormat %s {unit}",
                  f"    tickInterval {tick_interval}", "    todayMarker off",
                  "    %% Relative coordinates: 1000 Date milliseconds = 1 displayed unit.",
                  "    %% Positions round to 0.001 displayed units. Calendar dates have no meaning."])
    task = 0
    for label, collection, members in lanes:
        lines.append("    section " + label)
        for low, high, item, points in members:
            task += 1
            position, end = round((low - origin) * scale * 1000), round((high - origin) * scale * 1000)
            caption = f"#{item['occurrence']}" if "occurrence" in item else item["id"]
            caption = _mermaid_text(caption, "observation caption")
            # Use literal # for the familiar concise occurrence labels, safe in Gantt task text.
            if "occurrence" in item:
                caption = f"#{item['occurrence']}"
            lines.append("    %% Evidence: " + json.dumps({"id": item["id"],
                         "lines": [point["line"] for point in points]}, ensure_ascii=True))
            if collection == "events" or item.get("partial"):
                if item.get("partial"):
                    caption += " (open)"
                lines.append(f"    {caption} :milestone, v{task}, {position}, 0ms")
            else:
                if high > low and end == position:
                    raise ValueError(f"Interval {item['id']} is below plot resolution, use a separate finer-unit view")
                emphasis = "crit, " if item.get("highlight") else ""
                lines.append(f"    {caption} :{emphasis}v{task}, {position}, {end}")
    return "\n".join(lines + ["```", ""])


def _sequence_view(view):
    _view_fields(view, {"kind", "title", "description", "participants", "cases"}, "sequence view")
    participants = _list(view.get("participants"), "participants")
    ids = []
    for participant in participants:
        _view_fields(participant, {"id", "label"}, "participant")
        identifier = _text(participant.get("id"), "participant.id")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", identifier) or identifier in ids:
            raise ValueError("Participant IDs must be unique simple identifiers")
        ids.append(identifier)
    if not ids:
        raise ValueError("A sequence view requires at least one participant")
    if view["kind"] == "ping-pong" and ids != ["S", "M", "R"]:
        raise ValueError("ping-pong requires participants S/M/R in sender/transport/receiver order")
    cases = _list(view.get("cases"), "cases")
    if not cases:
        raise ValueError("A sequence view requires at least one named case")
    if view["kind"] == "comparison" and len(cases) < 2:
        raise ValueError("comparison requires at least two named cases")
    lines = _view_header("sequence", {"kind": view["kind"]})
    lines.extend(["sequenceDiagram", "    accTitle: " + _mermaid_text(view["title"], "title"),
                  "    accDescr: " + _mermaid_text(view["description"], "description"),
                  "    autonumber", "    box rgb(255, 255, 255)"])
    for participant in participants:
        lines.append(f"        participant {participant['id']} as "
                     + _mermaid_text(participant.get("label"), "participant.label", multiline=True))
    lines.append("    end")
    labels = set()
    for case in cases:
        _view_fields(case, {"label", "steps"}, "case")
        label = _mermaid_text(case.get("label"), "case.label", multiline=True)
        if label in labels:
            raise ValueError("Cases require distinct visible labels")
        labels.add(label)
        caption_over = ids[0] if len(ids) == 1 else f"{ids[0]},{ids[-1]}"
        lines.append(f"    Note over {caption_over}: {label}")
        steps = _list(case.get("steps"), "case.steps")
        if not steps:
            raise ValueError("Each case requires evidence-backed steps")
        for step in steps:
            _view_fields(step, {"kind", "from", "to", "over", "text", "evidence", "basis",
                                "highlight", "dashed"}, "step")
            basis = step.get("basis")
            if basis not in {"observed", "code", "protocol", "hypothesis"}:
                raise ValueError("step.basis must be observed, code, protocol or hypothesis")
            evidence = _text(step.get("evidence"), "step.evidence")
            _flag(step, "highlight", "step")
            _flag(step, "dashed", "step")
            text = step.get("text")
            if basis != "observed":
                qualifier = "hypothesis" if basis == "hypothesis" else f"{basis}-derived"
                text = _text(text, "step.text") + f" ({qualifier})"
            text = _mermaid_text(text, "step.text", multiline=True)
            if step.get("highlight"):
                lines.append("    rect rgb(255, 238, 232)")
            lines.append("    %% Evidence: " + json.dumps({"basis": basis, "reference": evidence}, ensure_ascii=True))
            if step.get("kind") == "message":
                if step.get("from") not in ids or step.get("to") not in ids:
                    raise ValueError("message endpoints must reference declared participants")
                arrow = "-->>" if step.get("dashed") else "->>"
                lines.append(f"    {step['from']}{arrow}{step['to']}: {text}")
            elif step.get("kind") == "note":
                over = _list(step.get("over"), "note.over")
                if not 1 <= len(over) <= 2 or any(identifier not in ids for identifier in over):
                    raise ValueError("note.over requires one or two declared participants")
                lines.append(f"    Note over {','.join(over)}: {text}")
            else:
                raise ValueError("step.kind must be message or note")
            if step.get("highlight"):
                lines.append("    end")
    return "\n".join(lines + ["```", ""])


def render_mermaid_view(view, model=None):
    """Generate a fixed semantic view; never infer diagnosis, steps or subwindows."""
    _object(view, "view")
    _text(view.get("title"), "view.title")
    _text(view.get("description"), "view.description")
    if view.get("kind") == "timeline":
        return _timeline_view(view, model)
    if view.get("kind") in {"sequence", "ping-pong", "comparison"}:
        return _sequence_view(view)
    raise ValueError("view.kind must be timeline, sequence, ping-pong or comparison")


# Evidence validation


CSV_FIELDS = {"cycles", "stream", "type", "index", "value", "pc", "address", "note"}


BASIS_KINDS = {"code", "protocol", "hypothesis"}


def _object(value, context):
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _list(value, context):
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return value


def _text(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a nonempty string")
    return value


def _integer(value, context, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _number(value, context, positive=False):
    try:
        finite = isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if (isinstance(value, bool) or not finite or (positive and value <= 0)):
        qualifier = "positive finite" if positive else "finite"
        raise ValueError(f"{context} must be a {qualifier} number")
    return value


def _raw_integer(value, context):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{context} is not an integer")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{context} is not an integer")
    try:
        value = value.strip()
        return int(value, 16 if value.lower().startswith(("0x", "-0x", "+0x")) else 10)
    except ValueError as error:
        raise ValueError(f"{context} is not an integer") from error


def _strings(value, context):
    for index, item in enumerate(_list(value, context)):
        _text(item, f"{context}[{index}]")
    return value


def _flag(item, name, context):
    if name in item and not isinstance(item[name], bool):
        raise ValueError(f"{context}.{name} must be boolean")


def _catalog(items, context):
    result = {}
    for index, item in enumerate(_list(items, context)):
        _object(item, f"{context}[{index}]")
        identifier = _text(item.get("id"), f"{context}[{index}].id")
        if identifier in result:
            raise ValueError(f"Duplicate {context} ID: {identifier}")
        result[identifier] = item
    return result


def _reference(identifier, catalog, context):
    _text(identifier, context)
    if identifier not in catalog:
        raise ValueError(f"Unknown {context}: {identifier}")
    return catalog[identifier]


def _check_number(item, name, actual, context):
    if name in item:
        expected = _number(item[name], f"{context}.{name}")
        matches = (expected == actual if name.endswith("_cycles") else
                   math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-8))
        if not matches:
            raise ValueError(f"{context}.{name} does not match the source endpoints")


def _read_capture(source, analysis_path):
    _object(source, "source")
    capture = Path(_text(source.get("csv"), "source.csv"))
    if not capture.is_absolute():
        capture = analysis_path.parent / capture
    capture = capture.resolve()
    expected_hash = _text(source.get("sha256"), "source.sha256")
    actual_hash = hashlib.sha256(capture.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("The source CSV changed; regenerate the analysis first")
    _text(source.get("origin"), "source.origin")
    for field in ("date", "target"):
        if field in source:
            _text(source[field], f"source.{field}")
    mapping = _object(source.get("columns", {}), "source.columns")
    if not set(mapping).issubset(CSV_FIELDS):
        raise ValueError("source.columns contains an unknown normalized CSV field")
    for key, value in mapping.items():
        _text(value, f"source.columns.{key}")
    columns = {field: mapping.get(field, field) for field in CSV_FIELDS}
    if len(set(columns.values())) != len(columns):
        raise ValueError("source.columns maps multiple normalized fields to one column")
    rows = {}
    decoder_records = []
    with capture.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("The source CSV needs unique column names")
        for field in ("cycles", "stream"):
            if columns[field] not in reader.fieldnames:
                raise ValueError(f"Missing CSV column: {columns[field]}")
        for field in mapping.values():
            if field not in reader.fieldnames:
                raise ValueError(f"Mapped CSV column does not exist: {field}")
        for record in reader:
            line = reader.line_num
            if None in record:
                raise ValueError(f"Unexpected extra CSV fields at line {line}")
            row = {field: record.get(column) for field, column in columns.items()}
            rows[line] = row
            kind = (row["type"] or "").strip().lower()
            if kind in {"info", "error", "overflow"}:
                raw_stream = row["stream"]
                record_stream = _raw_integer(raw_stream, f"CSV line {line} stream") if raw_stream else None
                decoder_records.append({"line": line, "type": kind,
                                        "stream": record_stream,
                                        "note": row["note"] or "No decoder message"})
    source["csv"] = str(capture)
    return rows, decoder_records


def _same_raw(expected, actual, field):
    if expected is None:
        return actual is None or actual == ""
    if field == "type":
        return isinstance(expected, str) and expected == actual
    try:
        return _raw_integer(expected, field) == _raw_integer(actual, field)
    except ValueError:
        return False


def _measure(start, end, timebases, decoder_records, context):
    if start["timebase"] != end["timebase"]:
        raise ValueError(f"{context} crosses clock domains or epochs")
    cycles = end["cycles"] - start["cycles"]
    if cycles < 0 or end["line"] < start["line"]:
        raise ValueError(f"{context} has reversed endpoints")
    timebase = timebases[start["timebase"]]
    for record in decoder_records:
        if (record["type"] in {"error", "overflow"}
                and start["line"] < record["line"] < end["line"]
                and record["stream"] in {None, 0, timebase["stream"]}):
            raise ValueError(f"{context} spans decoder {record['type']} at CSV line {record['line']}")
    frequency = timebase.get("clock_hz")
    duration = cycles * 1000 / frequency if frequency else cycles
    _number(duration, f"{context} derived duration")
    return {"timebase": timebase["id"], "duration_cycles": cycles,
            "duration": duration,
            "unit": timebase["unit"]}


def validate_model(data, analysis_path, *, evidence_only=True):
    """Normalize a schema-v1 object; resolve source paths beside its JSON.

    Mutates the supplied object and returns it with computed values and ID
    maps. Callers adapting another format must supply source-backed events.
    """
    if not evidence_only:
        raise ValueError("Legacy layout validation belongs to the project image renderer")
    _object(data, "analysis")
    analysis_path = Path(analysis_path).resolve()
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported trace diagram schema_version; expected 1")
    _text(data.get("title"), "title")
    if "subtitle" in data:
        _text(data["subtitle"], "subtitle")
    rows, decoder_records = _read_capture(data.get("source"), analysis_path)
    timebases = _catalog(data.get("timebases"), "timebases")
    if not timebases:
        raise ValueError("At least one timebase is required")
    for name, timebase in timebases.items():
        _text(timebase.get("label"), f"timebase {name}.label")
        _integer(timebase.get("stream"), f"timebase {name}.stream")
        _integer(timebase.get("origin_cycles"), f"timebase {name}.origin_cycles")
        if timebase.get("clock_hz") is not None:
            _number(timebase["clock_hz"], f"timebase {name}.clock_hz", positive=True)
        if "epoch" in timebase:
            _text(timebase["epoch"], f"timebase {name}.epoch")
        timebase["unit"] = "ms" if timebase.get("clock_hz") else "cycles"
        if "origin_line" in timebase:
            line = _integer(timebase["origin_line"], f"timebase {name}.origin_line", 2)
            if line not in rows or any(
                    _raw_integer(rows[line][field], f"CSV line {line} {field}") != expected
                    for field, expected in (("cycles", timebase["origin_cycles"]),
                                            ("stream", timebase["stream"]))):
                raise ValueError(f"timebase {name} origin does not match its source line")

    events = _catalog(data.get("events"), "events")
    observed_lines = set()
    for name, event in events.items():
        context = f"event {name}"
        timebase = _reference(event.get("timebase"), timebases, f"{context} timebase")
        line = _integer(event.get("line"), f"{context}.line", 2)
        if line not in rows:
            raise ValueError(f"{context} references missing CSV line {line}")
        if line in observed_lines:
            raise ValueError(f"Duplicate observation of CSV line {line}; reuse one event ID")
        observed_lines.add(line)
        row = rows[line]
        if (row["type"] or "").strip().lower() in {"info", "error", "overflow"}:
            raise ValueError(f"{context} references a decoder record, not a program event")
        cycles = _raw_integer(row["cycles"], f"CSV line {line} cycles")
        if cycles < 0:
            raise ValueError(f"CSV line {line} has negative cycles")
        if _raw_integer(row["stream"], f"CSV line {line} stream") != timebase["stream"]:
            raise ValueError(f"Core/stream mismatch for {context} at CSV line {line}")
        if "cycles" in event and _raw_integer(event["cycles"], f"{context}.cycles") != cycles:
            raise ValueError(f"Cycle mismatch for {context} at CSV line {line}")
        for field in ("type", "index", "value", "pc", "address"):
            if field in event and not _same_raw(event[field], row[field], field):
                raise ValueError(f"{context}.{field} does not match CSV line {line}")
        _text(event.get("label"), f"{context}.label")
        if event.setdefault("role", "event") not in {"event", "send", "clear"}:
            raise ValueError(f"Invalid {context}.role")
        if "channel" in event:
            _text(event["channel"], f"{context}.channel")
        if "occurrence" in event:
            _integer(event["occurrence"], f"{context}.occurrence")
        _flag(event, "highlight", context)
        local_cycles = cycles - timebase["origin_cycles"]
        frequency = timebase.get("clock_hz")
        local_value = local_cycles * 1000 / frequency if frequency else local_cycles
        _number(local_value, f"{context} derived local value")
        if frequency:
            _check_number(event, "local_ms", local_value, context)
        _check_number(event, "local_value", local_value, context)
        event.update(cycles=cycles, local_cycles=local_cycles,
                     local_value=local_value, unit=timebase["unit"])

    intervals = _catalog(data.setdefault("intervals", []), "intervals")
    for name, interval in intervals.items():
        context = f"interval {name}"
        _text(interval.get("label"), f"{context}.label")
        endpoints = []
        for key in ("start", "end"):
            if key not in interval:
                raise ValueError(f"{context}.{key} is required (use null for a partial span)")
            endpoints.append(_reference(interval[key], events, f"{context}.{key}")
                             if interval[key] is not None else None)
        start, end = endpoints
        if start is None and end is None:
            raise ValueError(f"{context} has no observed endpoint")
        if "occurrence" in interval:
            _integer(interval["occurrence"], f"{context}.occurrence")
        _flag(interval, "highlight", context)
        if start is not None and end is not None:
            measured = _measure(start, end, timebases, decoder_records, context)
            _check_number(interval, "duration_cycles", measured["duration_cycles"], context)
            _check_number(interval, "duration", measured["duration"], context)
            interval.update(measured, partial=False)
        else:
            endpoint = start or end
            if any(interval.get(field) is not None for field in ("duration_cycles", "duration")):
                raise ValueError(f"{context} cannot declare a duration without both endpoints")
            interval.update(timebase=endpoint["timebase"], duration_cycles=None,
                            duration=None, unit=endpoint["unit"], partial=True)

    return _finish_model(data, timebases, events, intervals, decoder_records)


def _finish_model(data, timebases, events, intervals, decoder_records, columns=None, nodes=None):
    quality = _object(data.setdefault("quality", {}), "quality")
    notes = _strings(quality.setdefault("notes", []), "quality.notes")
    for record in decoder_records:
        message = f"CSV line {record['line']} · {record['type']}: {record['note']}"
        if message not in notes:
            notes.append(message)
    quality["decoder_records"] = decoder_records
    if "metadata" in data:
        _object(data["metadata"], "metadata")
    data.update(timebase_map=timebases, event_map=events, interval_map=intervals,
                column_map=columns or {}, node_map=nodes or {})
    return data


def load_model(path, *, evidence_only=True):
    """Read a schema-v1 JSON and verify its CSV evidence using only the stdlib.

    Adds ID maps, event cycles/local_cycles/local_value/unit, and local interval
    durations. Partial intervals have null durations. Known clock
    frequencies use milliseconds; unknown frequencies retain cycle units.
    Every call checks the CSV-backed catalog without a legacy drawing layout.
    The evidence_only=True keyword is retained for existing Mermaid callers.
    """
    path = Path(path).resolve()
    data = _object(json.loads(path.read_text(encoding="utf-8")), "analysis")
    return validate_model(data, path, evidence_only=evidence_only)


def _mermaid_blocks(markdown):
    """Locate real Markdown fences, excluding examples inside other fences."""
    blocks, opened = [], None
    offset = 0
    for line_number, line in enumerate(markdown.splitlines(keepends=True), 1):
        if opened is None:
            match = re.match(r"^ {0,3}(\x60{3,}|~{3,})([^\r\n]*)", line)
            if match:
                fence, info = match.groups()
                opened = {"marker": fence[0], "width": len(fence),
                          "mermaid": info.strip().lower() == "mermaid",
                          "start": offset, "body": offset + len(line),
                          "line": line_number}
        elif re.match(r"^ {0,3}" + re.escape(opened["marker"])
                      + r"{" + str(opened["width"]) + r",}\s*$", line):
            if opened["mermaid"]:
                blocks.append({"start": opened["start"], "end": offset + len(line),
                               "line": opened["line"],
                               "source": markdown[opened["body"]:offset]})
            opened = None
        offset += len(line)
    if opened and opened["mermaid"]:
        blocks.append({"start": opened["start"], "end": len(markdown),
                       "line": opened["line"], "source": markdown[opened["body"]:],
                       "unclosed": True})
    return blocks


class MermaidParserError(RuntimeError):
    def __init__(self, message, engine):
        super().__init__(message)
        self.engine = engine


class _ParserResult(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.value = ""

    def handle_starttag(self, tag, attrs):
        if tag == "pre" and dict(attrs).get("id") == "result":
            self.active = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.active = False

    def handle_data(self, value):
        if self.active:
            self.value += value


def _mermaid_library(mermaid_js=None):
    """Find an official local distribution; never download or rewrite JavaScript."""
    configured = mermaid_js or os.environ.get("TRACE_MERMAID_JS")
    library = (Path(configured).expanduser() if configured else
               Path.cwd() / "node_modules/mermaid/dist/mermaid.esm.min.mjs")
    if not library.is_file():
        raise RuntimeError("Mermaid parser unavailable; supply --mermaid-js or TRACE_MERMAID_JS "
                           "with the installed mermaid/dist/mermaid.esm.min.mjs (keep its chunks)")
    return library.resolve()


def _mermaid_browser(browser=None):
    configured = browser or os.environ.get("TRACE_MERMAID_BROWSER")
    if configured:
        return str(Path(configured).expanduser())
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "chrome", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "Google/Chrome/Application/chrome.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Browser unavailable; supply --browser or TRACE_MERMAID_BROWSER "
                       "with Chrome or Chromium")


def _mermaid_engine(library, browser, operation):
    engine = {"library": str(library), "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
              "browser": browser, "operation": operation, "version": "unknown"}
    warnings = []
    package = library.parent.parent / "package.json"
    if package.is_file():
        try:
            metadata = json.loads(package.read_text(encoding="utf-8"))
            if metadata.get("name") != "mermaid" or not isinstance(metadata.get("version"), str):
                raise ValueError("expected the official mermaid package name and version")
            engine["version"] = metadata["version"]
        except (OSError, ValueError, AttributeError) as error:
            warnings.append(f"Cannot read Mermaid version metadata: {error}")
    # ESM entry points import chunks. Fingerprint the distribution, not just its entry.
    digest = hashlib.sha256()
    for asset in sorted(library.parent.rglob("*")):
        if asset.is_file() and asset.suffix in {".js", ".mjs"}:
            digest.update(asset.relative_to(library.parent).as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(asset.read_bytes()).digest())
    engine["distribution_sha256"] = digest.hexdigest()
    return engine, warnings


def _mermaid_page(library, page):
    """Serve only the transient page and local Mermaid assets on loopback."""
    from contextlib import contextmanager
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import unquote, urlsplit

    @contextmanager
    def serve():
        root = library.parent.resolve()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                route = unquote(urlsplit(self.path).path)
                if route == "/check.html":
                    content, mime = page.encode("utf-8"), "text/html; charset=utf-8"
                elif route.startswith("/mermaid/"):
                    asset = (root / route[len("/mermaid/"):]).resolve()
                    if (not asset.is_relative_to(root) or not asset.is_file()
                            or asset.suffix not in {".js", ".mjs", ".json"}):
                        self.send_error(404)
                        return
                    content = asset.read_bytes()
                    mime = "application/json" if asset.suffix == ".json" else "text/javascript"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Content-Security-Policy", "default-src 'none'; "
                                 "script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                                 "connect-src 'self'")
                self.end_headers()
                self.wfile.write(content)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_port}/check.html"
            finally:
                server.shutdown()
                thread.join(timeout=1)
    return serve()


def run_mermaid_browser(javascript, mermaid_js=None, browser=None, timeout=30,
                        operation="Mermaid browser check"):
    """Run an async body with initialized ``engine``; return JSON, never image files.

    The body can use ``engine``, ``warnings`` and ``initializationWarnings`` and
    must return an object. The parser uses only parse(); integration tests can
    inspect rendered browser DOM without writing diagram exports.
    """
    from urllib.parse import quote

    library = _mermaid_library(mermaid_js)
    executable = _mermaid_browser(browser)
    engine, metadata_warnings = _mermaid_engine(library, executable, operation)
    entry = "/mermaid/" + quote(library.name)
    # Official ESM has a default export; a supplied standalone browser bundle
    # may expose the same documented API as window.mermaid.
    module = library.suffix == ".mjs" or ".esm." in library.name
    load = (f"const engine = (await import({json.dumps(entry)})).default;" if module else
            "const engine = window.mermaid;")
    preload = "" if module else '<script src=' + json.dumps(entry) + '></script>'
    boot = r"""
(async () => {
  const warnings = [];
  console.warn = (...items) => warnings.push(items.map(String).join(" "));
  try {
    LOAD_ENGINE
    if (!engine || typeof engine.parse !== "function" || typeof engine.initialize !== "function") {
      throw new Error("The local bundle does not expose the Mermaid initialize/parse API");
    }
    engine.initialize({startOnLoad: false});
    const initializationWarnings = warnings.slice();
    const response = await (async () => { BODY })();
    response.warnings = initializationWarnings.concat(response.warnings || []);
    document.getElementById("result").textContent = JSON.stringify(response);
  } catch (error) {
    document.getElementById("result").textContent = JSON.stringify({fatal: String(error)});
  }
})();
""".replace("LOAD_ENGINE", load).replace("BODY", javascript)
    page = ('<!doctype html><meta charset="utf-8"><pre id="result">PENDING</pre>'
            + preload + '<script type="module">' + boot + '</script>')
    with tempfile.TemporaryDirectory(prefix="trace-mermaid-check-") as directory:
        try:
            with _mermaid_page(library, page) as url:
                command = [executable, "--headless", "--disable-gpu", "--no-first-run",
                           "--no-default-browser-check", "--disable-background-networking",
                           "--user-data-dir=" + str(Path(directory) / "browser-profile"),
                           "--virtual-time-budget=10000", "--dump-dom", url]
                process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MermaidParserError(str(error), engine) from error
        if process.returncode:
            raise MermaidParserError(
                f"Mermaid browser process exited {process.returncode}\n{process.stderr}", engine)
        result = _ParserResult()
        result.feed(process.stdout)
        try:
            response = json.loads(result.value)
        except ValueError as error:
            raise MermaidParserError("Mermaid browser returned no completed result\n"
                                     + process.stderr + "\n" + result.value, engine) from error
        if not isinstance(response, dict):
            raise MermaidParserError("Mermaid browser returned a non-object result", engine)
        if response.get("fatal"):
            raise MermaidParserError(response["fatal"], engine)
    return dict(response, engine=engine,
                warnings=metadata_warnings + response.get("warnings", []))


def parse_mermaid_blocks(blocks, mermaid_js=None, browser=None, timeout=30):
    """Validate with the documented Mermaid API in an isolated browser; never render."""
    sources = json.dumps([block["source"] for block in blocks]).replace("</", "<\\/")
    javascript = r"""
const results = [];
for (const source of SOURCES) {
  const firstWarning = warnings.length;
  try {
    const parsed = await engine.parse(source);
    if (parsed === false) throw new Error("Mermaid rejected the diagram");
    results.push({ok: true, warnings: warnings.slice(firstWarning)});
  } catch (error) {
    results.push({ok: false, error: String(error), warnings: warnings.slice(firstWarning)});
  }
}
return {results};
""".replace("SOURCES", sources)
    response = run_mermaid_browser(javascript, mermaid_js, browser, timeout,
                                   operation="mermaid.parse (no rendering)")
    if len(response.get("results", [])) != len(blocks):
        raise MermaidParserError("Mermaid parser returned an incomplete result", response["engine"])
    return response


def check_markdown(path, *, log_path=None, mermaid_js=None, browser=None,
                   sanitize=False, timeout=30, require_preset=False):
    """Log diagnostics, then optionally withhold failed/unverified diagrams."""
    path = Path(path).resolve()
    log = Path(log_path).resolve() if log_path else path.with_suffix(".log")
    if log == path or (mermaid_js and log == Path(mermaid_js).resolve()):
        raise ValueError("The log must not overwrite a Markdown or parser input")
    markdown = path.read_text(encoding="utf-8")
    blocks = _mermaid_blocks(markdown)
    issues, rejected, engine = [], [], {"operation": "not run"}
    if require_preset:
        for index, block in enumerate(blocks, 1):
            match = re.search(r"^[ \t]*%%\{init:\s*(.*?)\}%%[ \t]*$",
                              block["source"], flags=re.M | re.S)
            body = (block["source"][:match.start()] + block["source"][match.end():]
                    if match else block["source"])
            declaration = next((line.strip() for line in body.splitlines()
                                if line.strip() and not line.lstrip().startswith("%%")), "")
            diagram_type = "gantt" if declaration == "gantt" else "sequence"
            try:
                accepted = bool(match) and json.loads(match[1]) == mermaid_preset(diagram_type)
            except ValueError:
                accepted = False
            if not accepted:
                issues.append(("WARNING", index, block,
                               "Mermaid style differs from the accepted preset. Use the complete "
                               "--mermaid-preset JSON, including fonts, spacing and themeCSS."))
    try:
        parsed = parse_mermaid_blocks(blocks, mermaid_js, browser, timeout) if blocks else {
            "engine": engine, "results": []}
        engine = parsed["engine"]
        for warning in parsed.get("warnings", []):
            issues.append(("WARNING", None, None, str(warning)))
        for index, (block, result) in enumerate(zip(blocks, parsed["results"]), 1):
            if block.get("unclosed"):
                result = dict(result, ok=False, error="Unclosed Mermaid Markdown fence")
            if not result["ok"]:
                rejected.append(block)
                issues.append(("ERROR", index, block, result.get("error", "Mermaid rejected the diagram")))
            for warning in result.get("warnings", []):
                issues.append(("WARNING", index, block, str(warning)))
    except (RuntimeError, OSError, subprocess.TimeoutExpired, TimeoutError) as error:
        engine = getattr(error, "engine", engine)
        rejected = list(blocks)
        issues.append(("WARNING", None, None,
                       "Mermaid validation unavailable; diagrams remain unverified.\n" + str(error)))
    errors = sum(level == "ERROR" for level, *_ in issues)
    warnings = sum(level == "WARNING" for level, *_ in issues)
    keep_log = bool(issues) or log.exists()
    if keep_log:
        entry = ["\n=== Trace Data Markdown validation ===",
                 "UTC: " + datetime.now(timezone.utc).isoformat(),
                 "Markdown: " + str(path),
                 "SHA-256: " + hashlib.sha256(markdown.encode()).hexdigest(),
                 "Parser: " + json.dumps(engine, ensure_ascii=False),
                 f"Summary: {errors} errors, {warnings} warnings; {len(blocks)} diagram(s)"]
        for level, index, block, message in issues:
            location = f"diagram {index}, Markdown line {block['line']}" if block else "validator"
            entry.extend([f"\n{level} [{location}]", message])
            if block:
                entry.extend(["--- Mermaid source ---", block["source"], "--- End source ---"])
        if rejected and any(block is None for _, _, block, _ in issues):
            for index, block in enumerate(blocks, 1):
                entry.extend([f"--- Unverified diagram {index}, Markdown line {block['line']} ---",
                              block["source"], "--- End source ---"])
        # Persist recovery evidence before changing the user's report.
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(entry) + "\n")
    modified = False
    if sanitize:
        cleaned = markdown
        for block in reversed(rejected):
            cleaned = cleaned[:block["start"]] + cleaned[block["end"]:]
        cleaned = re.sub(r"\n?<!-- trace-data:diagnostics -->.*?"
                         r"<!-- /trace-data:diagnostics -->\n?", "", cleaned, flags=re.S)
        if keep_log:
            from urllib.parse import quote
            relative = quote(Path(os.path.relpath(log, path.parent)).as_posix(), safe="/.")
            cleaned = cleaned.rstrip() + (
                "\n\n<!-- trace-data:diagnostics -->\n"
                f"Errors / warnings: see [log]({relative}).\n"
                "<!-- /trace-data:diagnostics -->\n")
        if cleaned != markdown:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix="." + path.name, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(cleaned)
            try:
                temporary.chmod(path.stat().st_mode & 0o777)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            modified = True
    return {"errors": errors, "warnings": warnings,
            "log": log if keep_log else None, "modified": modified}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Start with --view-help for native Mermaid input examples; "
               "check CSV evidence with --analysis evidence.json --validate-only.")
    if sys.version_info < MIN_PYTHON:
        parser.exit(2, "Trace Data requires Python 3.10 or newer.\n")
    parser.add_argument("--version", action="version", version=f"Trace Data {VERSION}")
    parser.add_argument("--analysis", type=Path,
                        help="Versioned evidence JSON; CSV paths resolve beside this file")
    parser.add_argument("--markdown", type=Path, help="Check native Mermaid; no image output")
    parser.add_argument("--log", type=Path, help="Diagnostic log; default: Markdown stem.log")
    parser.add_argument("--sanitize", action="store_true",
                        help="Withhold failed/unverified diagrams and add one short log link")
    parser.add_argument("--require-preset", action="store_true",
                        help="Warn when a Markdown diagram omits or changes the accepted style")
    parser.add_argument("--mermaid-js", type=Path, help="Local Mermaid browser bundle")
    parser.add_argument("--browser", type=Path, help="Chrome/Chromium executable for parse-only validation")
    parser.add_argument("--parser-timeout", type=float, default=30,
                        help="Parser process timeout in seconds")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-only", action="store_true",
                       help="Check CSV-backed evidence without output files or a drawing layout")
    modes.add_argument("--schema", action="store_true",
                       help="Print input fields and evidence rules, without a capture")
    modes.add_argument("--mermaid-preset", nargs="?", const="sequence",
                       choices=("sequence", "timeline", "gantt"),
                       help="Print the complete style JSON; default: sequence; timeline (alias: gantt)")
    modes.add_argument("--view-help", action="store_true",
                       help="Print the timeline, sequence, ping-pong and comparison view contracts")
    modes.add_argument("--mermaid-view", metavar="JSON_OR_STDIN",
                       help="Generate one fixed Mermaid view from JSON, or - for stdin")
    args = parser.parse_args(argv)
    if args.mermaid_view:
        if (args.markdown or args.sanitize or args.require_preset
                or args.mermaid_js or args.browser or args.parser_timeout != 30):
            parser.error("--mermaid-view accepts only --analysis and --log")
        if args.mermaid_view == "-" and not args.log:
            parser.error("--mermaid-view - requires --log REPORT.log for generation diagnostics")
        path = Path(args.mermaid_view).resolve() if args.mermaid_view != "-" else None
        log = args.log.resolve() if args.log else path.with_suffix(".log")
        if log == path or (args.analysis and log == args.analysis.resolve()):
            parser.error("The log must not overwrite a view or analysis input")
        if args.analysis:
            # Protect the capture even if its hash or the view fails validation.
            # Invalid analysis syntax is diagnosed by the normal generation path.
            try:
                analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
                capture = Path(analysis["source"]["csv"])
                capture = (args.analysis.resolve().parent / capture).resolve()
            except (OSError, ValueError, TypeError, KeyError):
                pass
            else:
                if log == capture:
                    parser.error("The log must not overwrite the source CSV")
        source = ""
        try:
            source = path.read_text(encoding="utf-8") if path else sys.stdin.read()
            view = _object(json.loads(source), "view")
            if view.get("kind") == "timeline":
                if not args.analysis:
                    raise ValueError("timeline requires --analysis with CSV-backed evidence")
                model = load_model(args.analysis, evidence_only=True)
            else:
                if args.analysis:
                    raise ValueError("Sequence steps carry their evidence references; --analysis is for timeline")
                model = None
            output = render_mermaid_view(view, model)
        except (ValueError, OSError) as error:
            try:
                stamp = datetime.now(timezone.utc).isoformat()
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(f"\n[{stamp}] ERROR Mermaid view generation\n{error}\n"
                                 f"View input: {path or 'stdin'}\n"
                                 f"Input SHA-256: {hashlib.sha256(source.encode('utf-8')).hexdigest()}\n"
                                 f"Analysis: {args.analysis or 'none'}\nRejected source:\n{source}\n")
            except OSError as log_error:
                parser.exit(2, f"View generation could not save diagnostics: {log_error}\n")
            parser.exit(2, f"View generation failed; errors / warnings in {log}\n")
        print(output, end="")
        return
    if args.markdown:
        if (args.analysis or args.schema or args.mermaid_preset
                or args.validate_only or args.view_help):
            parser.error("--markdown cannot be combined with analysis or help modes")
        try:
            result = check_markdown(args.markdown, log_path=args.log, mermaid_js=args.mermaid_js,
                                    browser=args.browser, sanitize=args.sanitize,
                                    timeout=args.parser_timeout, require_preset=args.require_preset)
        except (ValueError, OSError) as error:
            parser.exit(2, f"Markdown check could not save diagnostics: {error}\n")
        summary = f"Markdown check: {result['errors']} errors, {result['warnings']} warnings"
        if result["log"]:
            summary += f"; details in {result['log']}"
        print(summary)
        if result["errors"] or result["warnings"]:
            parser.exit(2 if result["errors"] else 1)
        return
    if (args.log or args.sanitize or args.require_preset or args.mermaid_js
            or args.browser or args.parser_timeout != 30):
        parser.error("Markdown diagnostic options require --markdown")
    if args.schema or args.mermaid_preset or args.view_help:
        if args.analysis:
            parser.error("--schema, --view-help and --mermaid-preset do not accept --analysis")
        print(SCHEMA_HELP if args.schema else VIEW_HELP if args.view_help
              else json.dumps(mermaid_preset(args.mermaid_preset), indent=2))
        return
    if not args.validate_only:
        parser.error("Choose --validate-only, --mermaid-view or --markdown; no output is implicit")
    if args.analysis is None:
        parser.error("--analysis is required with --validate-only")
    try:
        model = load_model(args.analysis)
        print(f"Valid trace evidence: {len(model['events'])} events, "
              f"{len(model['intervals'])} intervals")
    except (ValueError, OSError) as error:
        parser.exit(2, f"Trace evidence validation failed: {error}\n")


if __name__ == "__main__":
    main()
