# Trace examples

The portable **Trace Data 0.1.0** package lives in
`.agents/skills/trace-visualization/` and has three files:

- [SKILL.md](../.agents/skills/trace-visualization/SKILL.md): capture selection,
  problem routing, diagnosis checks and graphic vocabulary. User symptoms and
  CSV/source evidence select the included [Delay](../.agents/skills/trace-visualization/SKILL.md#delay)
  or [Ping-ping-pong](../.agents/skills/trace-visualization/SKILL.md#ping-ping-pong)
  procedure, each with a worked example. Other findings use the general checks.
  Delay normally uses comparison plus timeline; premature reuse uses a shared
  normal/finding comparison with exact values/counts. The procedures are sections
  in the skill, so the portable package includes both cases without extra files.
- [drawing.md](../.agents/skills/trace-visualization/references/drawing.md): how to draw and
  validate the selected views, including fixed semantic layouts, Mermaid styles
  and diagnostic logs.
- [trace_data.py](../.agents/skills/trace-visualization/trace_data.py):
  CSV-backed evidence validation, deterministic native Mermaid generation and
  Markdown checks. `--view-help` describes `timeline`, `sequence`, `ping-pong` and `comparison`;
  `--mermaid-view - --log report.log` reads JSON from stdin and prints a complete
  fenced view. Timelines additionally use `--analysis evidence.json`.

Codex discovers this repository-local skill automatically, including when started
in an example subdirectory. Invoke it explicitly as `$trace-visualization` or ask
for a trace/source explanation. See the [Codex skill discovery documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
Other assistants that read [AGENTS.md](../AGENTS.md) can follow the same entry point;
discovery in other hosts depends on their Agent Skills support.

Timelines show all matching intervals in the relevant supplied run, with normal
and highlighted spans together and relevant events in milestone lanes. Their
origin is the first plotted event; there is no automatic zoom. Sequence views
retain fixed participants and visibly named cases without artificial parallel
frames. Populate complete relevant evidence first: the generator cannot detect
observations left out of the analysis. Specifications can stay on stdin, so
generating a view needs no additional permanent files.

Evidence validation, generation and schema help need only Python 3.10+ and its
standard library. Native validation uses official Mermaid 11.17.2 and Chrome/Chromium
in parse-only mode. Run `--markdown report.md --sanitize --require-preset` before delivery: failed
or unverified diagrams are withheld, diagnostics and recoverable source go to
one adjacent `.log`, and Markdown gets one short log link. Clean reports create
no log; repair runs preserve earlier diagnostics. The style check prevents a
reduced init directive from silently restoring Mermaid's default appearance.
The helper supports only Mermaid; `--analysis` alone creates nothing, and
`--validate-only` checks CSV-backed evidence without rendering. The
[drawing reference](../.agents/skills/trace-visualization/references/drawing.md) contains
runtime setup and a runnable minimal example. Package version is available with
`python3 .agents/skills/trace-visualization/trace_data.py --version`.

Current explanations in [examples](examples/) contain native Mermaid in Markdown,
with no SVG/PNG exports or separate `.mmd` copies.

## Release checks

Portable tests and synthetic fixtures are in [tests/trace_data](../tests/trace_data/).
The checks are grouped by the behavior they protect:

| Test module | Purpose |
| --- | --- |
| [Evidence](../tests/trace_data/test_trace_evidence.py) | CSV hashes, row mappings, clocks, loss boundaries and partial intervals; published report/CSV pairs. |
| [Views](../tests/trace_data/test_trace_views.py) | All four Mermaid view types, complete timelines, presets and evidence-backed generation. |
| [Markdown](../tests/trace_data/test_trace_markdown.py) | Diagnostic logs, recovery, unchanged valid content and parser/platform failures. |
| [Mermaid integration](../tests/trace_data/test_mermaid_integration.py) | Official parser, finished reports and native browser style/scaling checks. |
| [Portability](../tests/trace_data/test_trace_skill_portability.py) | Three-file package and standalone Python execution without repository or site-package dependencies. |

The three synthetic CSV/JSON pairs cover early CLEAR, unknown clocks with partial
intervals, and custom columns with independent core clocks.
The semantic tests need no board or graphics dependencies:

```sh
python3 tests/trace_data/run_checks.py
```

This also checks the example CSV references/hashes and the portable three-file
package contract. All tests use the helper directly beside `SKILL.md` in
`.agents/skills/trace-visualization/`; they are not part of the portable package.

For the required real-parser and native DOM checks, install the locked development
dependencies (Node.js 22+) and their pinned Chromium once in a cache outside the
checkout. From the repository root, for example in a POSIX shell:

```sh
export TRACE_TEST_TOOLS="$HOME/.cache/trace-data-tests"
mkdir -p "$TRACE_TEST_TOOLS"
cp tests/trace_data/package*.json "$TRACE_TEST_TOOLS/"
npm ci --prefix "$TRACE_TEST_TOOLS" --ignore-scripts --no-audit --no-fund
PLAYWRIGHT_BROWSERS_PATH="$TRACE_TEST_TOOLS/.browser-cache" \
  node "$TRACE_TEST_TOOLS/node_modules/playwright/cli.js" install --with-deps --no-shell chromium
python3 tests/trace_data/run_checks.py --browser-checks --tools-dir "$TRACE_TEST_TOOLS"
```

`--tools-dir` selects the external installation and discovers its `.browser-cache`.
An explicit `PLAYWRIGHT_BROWSERS_PATH` or `--browser` still takes precedence.
After dependency updates, copy the two package files and repeat installation.
CI installs into its temporary checkout and uses the test directory default.

These checks cover all four view kinds, actual syntax rejection and diagnostic
recovery, fixed colors/shapes and proportional sizing at 360/600/1000/1600 px.
They also parse every finished report in `docs/examples` and require its complete
Mermaid style preset; temporary validation copies keep reports free of test logs.
They inspect native browser DOM without producing SVG/PNG files. The lockfile
pins Mermaid 11.17.2, Playwright 1.64.1 and Chromium 156.0.8078.4. Development
dependencies and the browser are not part of the three-file skill.

The [CI workflow](../.github/workflows/trace-data.yml) runs Linux/Python 3.10 and
3.14, Windows/Python 3.13 and macOS/Python 3.14, then supplies the skill and license
as a review artifact. Local checks have run on macOS arm64/Python 3.14.5;
the hosted cross-platform matrix still needs its first run before publication.
Changes to the skill, its tests or finished reports trigger these checks.

## Hardware trace explanations

Each finished analysis sits beside its original, unmodified CSV in
[examples](examples/). Capture mappings, source identities, CSV hashes and
measurement limits are recorded directly in the analysis.
For board setup and capture steps, see the repository
[README](../README.md#work-with-the-example).

| Case | Analysis | Original CSV |
| --- | --- | --- |
| TraceDelayMulti | [Normal/delayed comparison and continuous horizontal timeline](examples/ipm-trace-delay-multi-2026-10-28.md) | [2026-10-28 capture](examples/ipm-trace-delay-multi-2026-10-28.csv) |
| NoWaitMulti ping-pong | [Normal/NoWait comparison and per-round evidence](examples/ipm-ping-pong-multi-2026-10-28.md) | [2026-10-28 capture](examples/ipm-ping-pong-multi-2026-10-28.csv) |

## IPM capture profiles

These mappings are specific to the matching Zephyr-Alif capture/profile. Confirm
the producing profile and run before reuse; they are not portable skill defaults.

| Profile | Stream 1 / M55_HE | Stream 2 / M55_HP |
| --- | --- | --- |
| [NoWait round markers](../Examples/IPM_ARM_MHUv2/.cmsis/ipm_arm_mhuv2-ac6+DevKit-E7-NoWaitMulti.ctrace.yml) | DWT0 payload write; DWT1 round; DWT2 phase; DWT3 completion-counter write | DWT0 payload read; DWT1 clear; DWT2 round; DWT3 phase |
| [TraceDelay](../Examples/IPM_ARM_MHUv2/.cmsis/ipm_arm_mhuv2-ac6+DevKit-E7-TraceDelayMulti.ctrace.yml) | DWT0/1 CH_SET on channels 0/1; DWT2/3 CH_CLR on channels 0/1 | Same access mapping |

NoWait behavior comes from [trace_no_wait.c](../Examples/IPM_ARM_MHUv2/trace_no_wait.c).
The receiver gating and bit-set semantics must support any payload-merge claim.
Older control-channel profiles use different comparator slots.

TraceDelay maps exceptions 57/58 to RX/TX, with values 1/2/3 meaning entry/exit/return.
It captures neither payload reads nor exact completion callbacks. The
[HE](../Examples/IPM_ARM_MHUv2/rtss_he/src/for_rtss_hp_mhu0.c) and
[HP](../Examples/IPM_ARM_MHUv2/rtss_hp/src/for_rtss_he_mhu0.c) sources establish
callback-before-clear and completion-gated sends; a TX IRQ is not a unique ACK.
Use the capture's context for clocks, injected waits and provenance.

## Hardware validation: twelve rounds and two NoWait events

Historical validation on **2026-10-27** used DevKit-E7, ULINKplus `L39352482A`
and AC6 Debug. Two `DevKit-E7-NoWaitMulti` runs each contained 24 writes,
22 reads, 22 clears and 22 completions, with merged reads only in rounds 4 and 9.
The original ten-round NoWait regression also passed. All three runs reached
the completion breakpoint and exported RAW/CSV automatically. GCC was not built.
The retained example capture is from 2026-10-28; the earlier NoWaitMulti
validation captures are not retained.

The first launch lacked the generated trace profile; subsequent launches and
reconnects succeeded. Startup `evaluate` and disconnect `adapter error: read error`
diagnostics were recorded but not investigated. Expected mapped exchanges were
present; this does not establish globally lossless capture. Independent core
clocks provide no measured cross-core latency.

## Hardware validation: twelve rounds and two delays

Historical validation on **2026-10-27** used the same board, probe and compiler.
Two `DevKit-E7-TraceDelayMulti` runs each contained all 48 sends and 48 receive
clears. HE channel-0 receive IRQs 3 and 8 lasted about 18.397 ms and 33.396 ms
in the first run, including handler overhead around the configured 15/30 ms
waits. Durations use the configured 160 MHz HE clock; there is no measured
cross-core latency. The retained example capture is from 2026-10-28.

Build, Load & Debug, Continue, Pause/export and reconnect succeeded; HP reached
idle with no fault flags. Historical startup/pause `evaluate`, disconnect and
editor diagnostics were not investigated. The AC6 build and repeat capture
passed. Expected IPC writes were present, but decoder boundary notes do not
establish globally lossless capture.
