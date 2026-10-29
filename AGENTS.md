# Project agent guidance

For explanations based on decoded trace data and source, use the project-local
[Trace Data skill](.agents/skills/trace-visualization/SKILL.md). It selects the
evidence checks and native Mermaid views; its linked drawing reference and the
adjacent `trace_data.py` define generation and validation.

Find current captures relative to the selected example's `.csolution.yml`:
`.trace/<solution-stem>+<target>.TB.csv`. The solution stem retains `-ac6` or
`-gcc`; for example, IPM AC6 TraceDelayMulti exports to
`Examples/IPM_ARM_MHUv2/.trace/ipm_arm_mhuv2-ac6+DevKit-E7-TraceDelayMulti.TB.csv`.
The producing `.ctrace-run.yml` and `.TB.raw` share that solution/target prefix.
Match the requested run and configuration before reuse; follow the
[capture workflow](README.md#work-with-the-example) when a new capture is requested.

Keep finished example analyses and their original CSV captures together in
`docs/examples/`. Record essential capture provenance directly in each analysis.
These are historical references, not automatic substitutes for a current capture.
