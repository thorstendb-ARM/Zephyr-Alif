---
name: trace-visualization
description: "Analyze decoded embedded traces with source and configuration to explain runtime behavior and locate timing, delay or protocol problems. Select evidence-based explanations and native Mermaid views; acquire new captures through the project's debugging workflow."
license: Apache-2.0
metadata:
  version: "0.1.0"
---

# Trace Data

Use for requests such as "Explain from the trace and source where the issue is."
Honor the requested focus, format and destination; use English artifact labels.
This file defines **which finding needs which explanation and graphic**.
[Drawing and delivery](references/drawing.md) defines **how those graphics look,
how to generate them and how to validate them**. Keep the package to these two
instruction files and the [Python helper](trace_data.py) beside this file.

Release 0.1.0 uses Python 3.10 or newer; see the drawing reference for parser
setup and a runnable example. Resolve helper paths relative to this skill directory.

## Select the capture

Use an explicitly supplied capture first. Otherwise identify the requested
solution/target (or the active configuration when unspecified) and read the
project's capture/export instructions. Inspect its capture directory explicitly,
even when hidden or Git-ignored. For CMSIS buffered trace, check the solution
folder's `.trace/<solution-stem>+<target>.TB.csv`; the stem excludes
`.csolution.yml` and retains any compiler suffix. Confirm this convention against
the project configuration; other projects may use a different destination.

Match the capture to the requested run, compiler/build configuration and producing
profile, using the evidence checks below. A filename or newest modification time
alone does not identify a run. Report missing, ambiguous or unverifiable inputs;
do not silently substitute an archived example or another target's newest CSV.
Before authorized execution can overwrite a selected capture, preserve its CSV
and associated profile/raw evidence. Request only the missing information or
capture needed for the explanation; finding no CSV does not authorize a new run.
Pass the selected CSV path and hash explicitly to the helper's evidence input.

## Workflow and explanation

1. Verify capture/profile mappings, provenance, source and active configuration.
   Apply the evidence checks below. Filenames, familiar payloads and previous
   figures do not establish a diagnosis.
2. Reconstruct the operation: actual participants, ISR/thread/task context,
   boundaries and the condition allowing the next operation. Compare like
   observations, then [route the problem](#route-the-problem) using the user's
   symptom, CSV signature and source-supported gate.
3. Follow that gate through source calls, callbacks, waits, locks or queues.
   Localize the narrowest supported region with source/trace references. Classify
   the result as expected, deliberately injected, unintended defect, unexplained
   anomaly or insufficient evidence. An unverified source match makes the cause
   conditional; an enclosing interval does not identify an exact fault instruction.
4. Deliver one compact Markdown explanation: **supported conclusion → general
   operation → localized mechanism → measured evidence and limits → focused remedy
   or next observation**. Choose views below; every additional graphic must answer
   a distinct question. An explanation alone does not request firmware changes
   or a new capture.

## Graphic types and default appearance

Use the helper's complete presets; adapt evidence and concise labels. Read the
drawing reference before generating a view. All graphics are native Mermaid,
responsive to the page width, with white background, Arial labels and the fixed
palette. The timeline's 1400-unit width describes internal geometry.

| Helper kind / output | Purpose and default shape |
| --- | --- |
| `sequence` | One supported operation with its real participants, including a single participant. Rounded participant cards, numbered arrows and short notes; vertical schematic order, not elapsed time. No invented transport or comparison case. |
| `ping-pong` | IPC specialization of a sequence: sender `S` (green), transport `M` (slate), receiver `R` (blue), left to right. Show actual writes/reads/clear/completion; a PONG label must name its real meaning. |
| `comparison` | Reference and finding in one sequence, with the same participants and visibly captioned cases stacked vertically. Use S/M/R for mapped IPC; highlight only supported anomalous steps. |
| `timeline` | Wide, shallow, continuous horizontal local time axis. Rounded blue measured spans, red findings, separate blue diamond event lanes, short IDs, left lane captions and a light grid. Preserve measured gaps. |
| Evidence table / prose | Exact values, counter deltas, budgets, source rows, repeat occurrences or unresolved facts. This may be the complete answer when a graphic would add no explanatory value. |

A reference may be an observed normal case or an explicitly code/protocol-derived
expectation; label which. Do not present an expected case as observed. "OK" needs
a supported correctness criterion; otherwise use "normal reference". Without a
reference, use a single sequence/timeline or evidence table rather than inventing
one. Repeated instances of the same mechanism need one representative comparison
and a complete occurrence/count summary, not duplicated diagrams.

## Route the problem

Treat the user's problem description as a hypothesis and search focus. Inspect
mapped CSV values, counts, ordering, durations and coverage before choosing the
matching internal procedure below; follow its source/protocol checks before
accepting a cause. Keywords, target names and familiar payloads are not evidence.
If the observations contradict the reported symptom, explain the supported finding.

The linked Delay and Ping-ping-pong procedures are included in this skill. The
agent selects and applies them; Python validates supplied evidence and generates
views, without automatically diagnosing arbitrary CSVs. If both patterns match,
investigate both and connect them only through a supported dependency. If neither
fits, use the general rows and shared checks; incomplete evidence stays explicit.
Keep one explanation and avoid duplicate views of the same mechanism. Register a
new problem procedure with its CSV signature, source gate, output and limits.

| Trace/source finding and evidence gate | Procedure, default views and explanation |
| --- | --- |
| [Delay](#delay) or long operation: valid local endpoints plus a comparable reference or justified budget; source identifies work or a progress gate | Usually one behavior `comparison` plus a `timeline` of all matching intervals and relevant boundary events. If interactions add nothing, explain the mechanism in prose. Separate configured wait, whole measured span, excess over reference and downstream progress. |
| [Ping-ping-pong](#ping-ping-pong): premature channel/buffer reuse, merged or overwritten data; associated writes/read/completion and actual transport semantics | One combined normal/finding `comparison`, or `ping-pong` for a single supported IPC case. Add a values/counts table covering repeated occurrences. A timeline is optional only when it supplies distinct, valid timing evidence. |
| Wrong value, ordering or state transition: observed value/order and a supported expected value, ownership or transition rule | `sequence` for the observed path, or `comparison` against a clearly identified reference/expectation; annotate relevant values/states and cite the responsible source boundary. Equal values or interleaved rows alone do not prove a race. |
| Missing completion, timeout or stalled progress: expected progress plus a sufficiently covered window/deadline | Show the last observed boundary in a `sequence`; add a `timeline` only for meaningful observed spans/window endpoints. Put an uncaptured deadline in prose/table, not a fabricated event. Without coverage, report missing evidence rather than a proven hang/loss. |
| Contention, queue buildup, retries or scheduling delay: corresponding owner/state/counter or ready/running observations | `sequence` for ownership/release dependencies; `timeline` for measured waits/runs when endpoints are valid; table for observed queue levels/retry counts. Do not infer lock owners, queue depth or scheduling states from duration alone. |
| Expected behavior or deliberately injected behavior | Use the row matching the observed phenomenon; label the test/expected cause in the conclusion and case captions. Injection can demonstrate a real dependency without proving an unintended product defect. |
| Clean, ambiguous or incomplete trace; uncertain source/profile association | State supported behavior, the missing mapping/boundary and next discriminating observation. Use a single grounded view only if it helps; otherwise prose/table. Do not force a defect, counterpart or cause. |

For a selected timeline, include every matching observation across the full
relevant supplied run, including normal spans between findings and every affected
span. Keep only the series needed to explain the finding; complete coverage does
not require plotting every trace type. Zoom only on explicit user request, retain
real spacing and state the range. Unobserved internal wait boundaries stay unknown:
highlight their measured containing span instead of inventing a delay segment.

Sequence rows express supported relationships, not cross-core chronology. Connect
only observed or source/protocol-supported dependencies; leave independent
continuations unordered. Use a local timeline or separate labeled axes for
unsynchronized clocks. Do not promise a state-machine, dependency-graph or other
renderer the helper does not provide; use grounded notes/table if the supported
views cannot express the finding.

## Evidence and recognition checks

**Provenance and coverage.** Preserve the input and record path/SHA-256,
hardware/synthetic/unknown origin, producing profile, core/stream mappings,
source revision/hashes, selected physical CSV rows and association rules. Label
synthetic data visibly. Verify source/configuration against capture provenance;
matching current files alone is not a fresh binary match. Source code does not
prove an uncaptured event ran. Distinguish observed events, derived states,
hypotheses and unknowns. Populate the complete relevant catalog before selection:
the helper checks supplied entries against CSV, not whether entries were omitted.

**Clock and loss boundaries.** Partition by core, reset epoch and clock regime;
use a local observed origin and preserve unresolved ties. Unwrap only with known
counter width and continuity. Unknown frequency permits cycles; configured clocks
are uncalibrated. Independent counters, aligned origins and global CSV order prove
neither cross-core chronology nor latency. A cross-domain measurement needs a
verified synchronization relation and uncertainty. Distinguish decoder info from
error/overflow, retain partial spans and never bridge known loss. Missing trace
is not proof of missing execution, loss, hang or reset. Complete mapped counts
do not establish global losslessness.

## Problem procedures

These internal sub-skills share the capture, evidence and drawing rules above.
The worked examples are deliberately injected hardware cases from 2026-10-28;
their values illustrate the reasoning, not recognition constants. Recompute all
values, repetitions and associations for the selected capture. They need no
external example files to be understood.

### Delay

Use when a valid local span is long relative to comparable observations or a
justified budget. Locate the first delayed progress boundary, then follow the
source's work, callback, lock or wait up to the condition that releases progress.
Establish the execution context and separate slow processing from scheduling or
uncaptured latency; a long IRQ alone does not identify the slow instruction.

**Timing.** Pair IRQ entry/exit using same-core nesting; a return record is not
another exit. A handler span includes callbacks, logging and nested work, not
trigger-to-entry latency. Send spacing includes intervening work, not pure ACK/wait
latency. Measure `end_cycles - start_cycles`; convert with
`cycles * 1000 / clock_hz` only within a constant local clock. Keep partial/loss-
affected spans out of complete-duration statistics. Compare like core/epoch/
clock/operation/channel groups; count multi-channel IRQs once.

Prefer the user's focus or a supplied budget. Otherwise, with at least five
complete intervals, use median `m`, MAD `d` and threshold
`m + max(6 * 1.4826 * d, 0.5 * m, 1 cycle)`; record samples and exclusions.
With fewer samples describe the longest without an outlier claim. Use at least
three other nonflagged spans for a comparison median. Neither statistical contrast
nor an injected wait alone establishes an unintended defect.

**Worked example.** HP sends and waits for completion. HE's RX driver performs
read → callback → CLEAR; cleared status enables HP's completion and next send.
The callback deliberately busy-waits in two of twelve receive operations:

| HE receive | Configured callback wait | Observed whole RX handler |
| --- | ---: | ---: |
| #2, normal reference | 0 ms | 3.559 ms |
| #3 | 15 ms | 18.397 ms |
| #8 | 30 ms | 33.397 ms |

Source places the added work before CLEAR; the trace observes later CLEAR and
longer local spans. This demonstrates a delayed release condition, not an
unintended transport defect. The wait's own endpoints were not captured, so its
exact position inside the handler and cross-core latency remain unknown.

**Deliver:** general operation, narrow supported source location, normal/delayed
`comparison` and a continuous horizontal `timeline` of every matching receive
span plus CLEAR events. Highlight whole measured spans when internal wait
boundaries are unknown. Keep configured wait, measured span and excess over the
reference distinct. A single local operation may need only timeline and prose.

### Ping-ping-pong

Use two associated writes to the same channel/buffer before completion as an
investigation candidate. First check whether the protocol permits multiple
outstanding transfers; a valid FIFO or queue may make this order normal. Follow
the send/wait/ownership branch and receiver path to the first unsupported reuse.
Use these association checks for other IPC findings as well:

**IPC/data associations.** Map direction, channel, write/read, clear and completion
from the actual transport. ACK differs from reply data; clear need not prove a
payload read; a TX IRQ need not equal one ACK. Correlate by meaningful run/message/
round IDs, or serialized protocol order with sufficient coverage. Equal counts,
payloads, ordinals or timestamps alone are insufficient. Completion-counter deltas
need initialization and reset/wrap/jump checks; a jump provides no individual event
timestamps. Preserve callback/read/clear/completion order and next-send permission.
Clear may release a sender before receiver IRQ exit; an awaiting main may still run IRQs.

Several writes before completion identify a reuse candidate. A merge claim also
needs receiver association, pending-state order and transport semantics. For bit-set
channels, compare the OR of known writes and known initial state with the actual
read; pending/OR state remains inferred. A matching OR value alone is insufficient.
FIFO/overwrite transports require their own rules. Distinguish deliberate receiver
gating from a claim that arbitrary consecutive writes always merge.

**Worked example.** HE sends A=`0x11111111` and B=`0x22222222` through a bit-set
channel. PING is a payload write; PONG here is the observed sender completion-
counter write. Normal order is PING A → PONG → PING B → PONG. The test skips
A's wait while holding HP reception until both writes, producing PING A → PING B
→ PONG. Prior clear/completion supports an empty starting state; A OR B pending
is protocol-derived, while the later HP read of `0x33333333` is observed.

| Case | Writes | Reads / clears / completions | Received values |
| --- | ---: | ---: | --- |
| One normal round | 2 | 2 each | A, then B |
| One gated no-wait round | 2 | 1 each | A OR B once |
| Complete example: 12 rounds, no-wait in 4 and 9 | 24 | 22 each | Two merged rounds |

The skipped wait and receiver gate deliberately reproduce premature reuse.
Neither the matching OR value nor two writes alone establishes that mechanism
in another capture; FIFO/overwrite semantics or missing observations change it.

**Deliver:** one normal/finding `comparison` using actual sender/transport/receiver
roles, plus a values/counts table covering every affected round. State PONG's
observed meaning and distinguish measured reads from inferred pending state.
Add a timeline only for a separate, valid timing question; otherwise the shared
comparison is sufficient. Recommend completion/ownership before reuse or an
explicit queue only when the source and protocol support that remedy.

## Delivery and validation

Follow [Drawing and delivery](references/drawing.md) for generation, real Mermaid
parsing, complete-preset checks and native visual inspection, including page-width
scaling. Check measured numbers, associations and source links independently of
rendering. Reuse existing captures/evidence; create analysis JSON only when
repeatable calculations justify it. Keep diagrams directly in the one explanation;
do not create SVG, PNG or separate `.mmd` copies.

Technical tool/parser/renderer diagnostics belong in one optional adjacent log,
with one short "Errors / warnings: see log" link in the Markdown. Keep substantive
trace errors, uncertain causes and evidence gaps visible in the explanation.
A clean report creates no diagnostic log; preserve history when repairing a failure.
