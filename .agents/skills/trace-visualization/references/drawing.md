# Drawing and delivery

Use after the main skill's problem routing and graphic catalog have established
a finding and selected its output.
Keep analysis separate from rendering: a diagram expresses the evidence rather
than supplying a diagnosis. Commands below run from the skill directory.

## Runtime and first use

Release **0.1.0** requires **Python 3.10+**. Evidence validation and Mermaid
generation use only the standard library. The reference parser is official
**Mermaid 11.17.2**, with Chrome/Chromium; the reproducible release checks pin
Playwright 1.64.1 and its Chromium 156. Other Markdown viewers may apply different
Mermaid versions or restrict theme settings, so inspect the actual delivery viewer.
The helper checks supplied CSV evidence and calculations; sequence references,
source associations, catalog completeness and diagnosis remain the agent's work.

This minimal synthetic example runs from the skill directory on all supported
hosts and prints one Mermaid block without creating a report or log on success:

```python
import json
import subprocess
import sys

view = {
    "kind": "sequence", "title": "Synthetic worker example",
    "description": "Source-derived behavior, not a measured capture.",
    "participants": [{"id": "Task", "label": "Worker"}],
    "cases": [{"label": "Expected operation", "steps": [{
        "kind": "note", "over": ["Task"], "text": "Process the next item",
        "basis": "code", "evidence": "synthetic_worker.c:10",
    }]}],
}
subprocess.run([sys.executable, "trace_data.py", "--mermaid-view", "-",
                "--log", "explanation.log"], input=json.dumps(view), text=True, check=True)
```

## Generate canonical Mermaid

Embed diagrams directly in fenced `mermaid` blocks in one explanation. This is
the canonical source. Do not create SVG, PNG or adjacent `.mmd` copies, embed
exported images, or duplicate views of the same mechanism.

Generate the selected semantic view with the Python helper. Read its input
contract, then pass the JSON specification on stdin; only a timeline needs
CSV-backed analysis:

```sh
python3 trace_data.py --view-help
python3 trace_data.py --mermaid-view - --analysis /path/analysis.json --log /path/explanation.log
python3 trace_data.py --mermaid-view - --log /path/explanation.log
```

Insert stdout, one complete fenced block including its preset and evidence
comments, directly into the explanation. No permanent view-specification file
is needed; an existing JSON file can also replace `-`. The helper validates
timeline CSV hashes, rows and timebases; the evidence-only input needs no legacy
`detail` layout. It does not infer diagnosis or sequence steps.
Use `--analysis /path/analysis.json --validate-only` to check this same evidence
without generating a view. `--analysis` alone produces no output; there are no
SVG/PNG options. `--version` prints the package version.

The semantic layouts below and their complete presets are mandatory. Keep the
accepted palette, typography, rounded shapes, white background and strong lines.
Sequence views have role-colored cards, white bold labels, colored arrows and
numbered badges; timelines have rounded blue spans and red highlights. Adapt
evidence and wording, not the layout or preset. For an existing block, the full
styles remain available with `--mermaid-preset` and `--mermaid-preset gantt`;
never abbreviate or reconstruct their init JSON or accept Mermaid defaults.

Both presets require `useMaxWidth: true` in their `sequence`/`gantt` settings.
Mermaid fits the available page/container width up to the intrinsic maximum,
preserving aspect ratio and scaling text, shapes and spacing together. Keep the
timeline's `useWidth: 1400` as internal layout geometry, not a fixed display width.
Use native Mermaid sizing rather than adding exported images or per-report
width overrides. The Markdown viewer supplies the available container width.

## Sequences, ping-pong and comparisons

Choose `sequence` for an operation with its actual participants and one supported
case, including a single participant. It needs neither an IPC transport nor a
normal/finding pair. Choose `ping-pong` for mapped sender/transport/receiver interactions: IDs `S/M/R`
stay in that left-to-right order, with actual labels. Choose `comparison` for
reference/finding cases in any operation, using their real participants (and
`S/M/R` for mapped IPC). It requires at least two cases;
do not invent a normal case when none is supported. No view invents a
transport, reply or PING/PONG. The generator adds numbering, accessibility labels
and the white participant box.

Supply messages and notes with evidence references and their `observed`, `code`,
`protocol` or `hypothesis` basis. Derived/hypothetical steps stay visibly qualified.
A PONG label must identify the supported completion/dependency, not imply reply
data or exact hardware timing. Separate read and clear when combining them hides
relevant work. Retain payload aliases, counts and longer evidence in the prose.

Reference and finding use the same participants in vertically stacked cases,
each introduced by a visible full-width caption. Preserve the steps needed to
explain the mechanism; highlight only supported anomalous steps. When findings
repeat the same mechanism, use one representative finding in the comparison;
quantify every occurrence in prose/table and retain them all when a measured
overview is selected. A protocol/data finding does not require a timeline.
For premature reuse or merged data, show write/read/clear/completion relationships
in one normal/finding comparison; keep full payloads, counter deltas and repeated
rounds in the evidence table. Label an unobserved expected case as code/protocol-
derived throughout. Do not use
`par`/`alt` frames for case layout or align independent continuations into an
invented cross-core order. State "Schematic protocol order; independent clocks;
not to scale" where applicable. Keep labels concise; long sequence labels wrap
at word boundaries, and supplied newlines become safe line breaks. The generator
encodes Mermaid-sensitive label characters;
generation still requires the parser and preview checks below.

## Continuous horizontal timeline

Choose `timeline`: native Mermaid `gantt` with a continuous horizontal scaled
axis, compact measured-interval lanes and separate event-milestone lanes. This
is the approved style for simple event timelines, fixed in Python as
`SIMPLE_TIMELINE_PRESET` (export: `--mermaid-preset timeline`, alias `gantt`):

- Wide, shallow internal layout: width 1400, bar height 32, gap 12, left padding
  180; display scales proportionally with the page width.
- Rounded blue measured bars; red highlighted containing spans; blue diamond
  milestones. Use short occurrence IDs on or beside marks, with white labels
  inside colored shapes.
- White background, Arial typography, faint vertical grid, lane names on the
  left, title above and a shared unit-labeled axis below. Keep the full preset's
  fonts, colors and spacing; do not tune them per report.
- Start with the operation's interval lane and relevant event lane(s), such as
  CLEAR. Add series only when they help explain the finding; the overview covers
  every match in those selected series, rather than every unrelated trace type.

Keep all matching intervals across the full relevant supplied capture/run, including
normal spans between every finding. Include the relevant boundary events, such
as clear/completion, rather than showing only bars. Preserve real gaps; do not
replace this overview with two isolated intervals, a flowchart or a sequence.

Populate the complete relevant catalog first, then select series semantically
by timebase and labels/channel/role as described by `--view-help`. Every match is
drawn; do not prefilter the catalog to a convenient reference and finding.
Evidence comments record selected IDs and source rows. An explicit user-requested
range may supply `window` endpoints and reason; crossing intervals remain whole.
The scope statement describes the selection, not permission to zoom implicitly.

The first plotted observation is zero. The helper chooses ms/us/ns for a known
clock and cycles otherwise; it records origin, unit and selection. Declare the
clock source, bar endpoints and rounding in the explanation. Use one valid local
timebase per view; unsynchronized cores require separate labeled axes. Retain
loss boundaries and show an open interval only at its known endpoint.

Highlight the measured containing span when wait boundaries are uncaptured;
annotate the configured wait without inventing its exact placement. Closely
spaced events may coincide visually; explain their exact distinction in prose.
The generator maps 1000 Date milliseconds to one displayed unit and rounds to
0.001 displayed units. Its relative dates have no calendar meaning. Check axis
scaling and marker positions in the preview.

## Validate and publish

Check measurements, event associations, source references and local links, then
run the actual Mermaid parser and complete-style check before delivery:

```sh
python3 trace_data.py --markdown /path/explanation.md --sanitize --require-preset
```

Install the official Mermaid distribution once, outside the skill, for example
`npm install --prefix /path/trace-tools --ignore-scripts --save-exact mermaid@11.17.2`.
Keep its complete `node_modules/mermaid/dist` directory, including module chunks.
Supply `--mermaid-js /path/trace-tools/node_modules/mermaid/dist/mermaid.esm.min.mjs`
or set `TRACE_MERMAID_JS`. Without either, the helper looks under the current
directory's `node_modules`. It uses the documented `initialize`/`parse` API
without modifying the distribution or depending on a VS Code extension.

Chrome/Chromium is discovered on Linux, macOS and Windows; use
`--browser /path/to/chromium` or `TRACE_MERMAID_BROWSER` for another installation.
The helper serves the local modules on a temporary loopback port and starts an
isolated browser profile. Execution downloads nothing and exports no images.
JSON/fence checks and source review alone do not validate syntax. Missing or changed preset settings
produce a warning; restore the complete appropriate preset before delivery.

Technical parser/renderer/tool errors and warnings go to one adjacent
`<explanation>.log` (or `--log PATH`). Keep raw messages, stack traces and error
screenshots out of the explanation. The helper logs the input hash, parser
identity, diagram/fence location, full diagnostics and rejected source. With
`--sanitize`, it withholds failed blocks; an unavailable/crashed/timed-out parser
logs a warning and withholds unverified blocks. Valid diagrams and evidence stay.
It saves recovery evidence before editing Markdown; a log-write failure leaves
the report intact. Keep just one short diagnostic notice in the Markdown:
`Errors / warnings: see [log](explanation.log).` Exit status: 0 clean, 1 warnings,
2 errors. This technical-log rule does not hide substantive trace errors,
evidence gaps, uncertain causes or unsynchronized clocks; summarize those in
the explanation because they affect its interpretation.

Repair failed source from the log and re-run validation. Preserve failure
history and its short link after repair. Clean reports without prior diagnostics
create no log. Preserve captures and reuse existing evidence; the optional log
is the only extra diagnostic artifact.

Prefer the environment's native Markdown/Mermaid preview. If unavailable, render
the exact fenced source with the installed Mermaid engine in a temporary local
HTML page and inspect it in an available browser. Keep this transient preview
outside the report folder; rendering stays in the browser DOM, without exported
SVG/PNG/.mmd files. Remove the transient preview after checking.

Inspect rendered native Mermaid without exporting images. Parser success and
matching JSON do not prove visual fidelity. Check colors, fonts, shapes, arrows,
axis labels/scaling, spacing and clipping. Repair ignored style or unreadable
layout before delivery. Record preview failures/unavailable visual checks in
the same log and link, and do not claim visual verification. Return the Markdown
link and supported conclusion.
