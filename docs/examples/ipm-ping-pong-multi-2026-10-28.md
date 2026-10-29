# Ping-pong: reusing the channel before completion

**The test deliberately skips the first completion wait in rounds 4 and 9.** While HP reception is held, HE writes A and B to the same MHU bit-set channel. HP then reads `A OR B` once; two distinct words become one received value. This reproduces unsafe channel reuse in the hardware capture of `DevKit-E7-NoWaitMulti` from 2026-10-28.

**12 rounds · 24 writes → 22 reads, clears and completions.** Ten normal rounds preserve A and B separately. The captured HP result is PASS because the test expects the injected behavior; it reports twelve completed rounds, 22 receives and zero API/callback errors or fault flags.

## General behavior and comparison

HE sends a word on channel 0. HP reads it in the receive ISR, invokes the receive callback and clears the channel. The sender callback increments `trace_tx_ack_count`; normal code waits for that completion before sending the next word. A is `0x11111111`, B is `0x22222222`, and their OR is `0x33333333`.

The shared comparison uses normal round 3 and representative NoWait round 4. Round 9 repeats the same mechanism and is included in the evidence below.

```mermaid
%% trace-view: {"kind": "comparison"}
%%{init: {"theme":"base","themeVariables":{"fontFamily":"Arial, sans-serif","fontSize":"20px","primaryTextColor":"#102A43","actorBkg":"#1D5E96","actorBorder":"#153E63","actorTextColor":"#FFFFFF","actorLineColor":"#50657C","signalColor":"#203248","signalTextColor":"#203248","noteBkgColor":"#F5F7FA","noteBorderColor":"#50657C","noteTextColor":"#203248","sequenceNumberColor":"#FFFFFF"},"sequence":{"useMaxWidth":true,"mirrorActors":false,"diagramMarginX":18,"diagramMarginY":18,"actorMargin":50,"width":125,"height":46,"messageMargin":36,"noteMargin":10,"actorFontSize":20,"messageFontSize":20,"noteFontSize":18,"boxMargin":16,"boxTextMargin":10},"themeCSS":"rect.actor {rx:9px;ry:9px;stroke-width:0!important;} rect.actor[name=\"S\"] {fill:#1B6B49!important;} rect.actor[name=\"R\"] {fill:#1D5E96!important;} rect.actor[name=\"M\"] {fill:#40536A!important;} text.actor {fill:#FFFFFF!important;font-weight:700!important;} .actor-line {stroke:#A3AFBD!important;stroke-width:1.8px!important;} .messageLine0,.messageLine1 {stroke-width:3px!important;} .messageLine0 {stroke:#1B6B49!important;} .messageLine1 {stroke:#1D5E96!important;stroke-dasharray:8 5!important;} .messageText {fill:#203248!important;font-weight:700!important;} .sequenceNumber {font-weight:700!important;} rect.note {rx:7px;ry:7px;stroke:#BEC9D5!important;stroke-width:1.2px!important;} rect.rect {rx:12px;ry:12px;stroke:#DCE4ED!important;stroke-width:1px!important;} .messageLine0[data-from=\"R\"] {stroke:#1D5E96!important;}"}}%%
sequenceDiagram
    accTitle: Ping-pong#58; wait for completion versus NoWait
    accDescr: Normal round 3 preserves A and B separately. In injected round 4, HE reuses channel 0 before completion while HP reception is held#59; HP reads the combined bits and HE records one completion. Schematic protocol order, independent clocks, not to scale.
    autonumber
    box rgb(255, 255, 255)
        participant S as HE · Sender
        participant M as MHU · ch0
        participant R as HP · Receiver
    end
    Note over S,R: Normal reference · round 3
    %% Evidence: {"basis": "observed", "reference": "CSV3856; HE CH0_SET"}
    S->>M: PING · A
    %% Evidence: {"basis": "observed", "reference": "CSV3852/3853; HP CH0_ST/CH0_CLR; separate accesses"}
    R->>M: Read A + clear
    %% Evidence: {"basis": "observed", "reference": "CSV3858; HE trace_tx_ack_count=5; trace_no_wait.c:225-233 identifies callback completion, arrow denotes protocol dependency"}
    M-->>S: PONG · count 5
    %% Evidence: {"basis": "observed", "reference": "CSV3869; HE CH0_SET; follows completion at CSV3858 on HE"}
    S->>M: PING · B
    %% Evidence: {"basis": "observed", "reference": "CSV3865/3866; HP CH0_ST/CH0_CLR; separate accesses"}
    R->>M: Read B + clear
    %% Evidence: {"basis": "observed", "reference": "CSV3871; HE trace_tx_ack_count=6; callback completion, protocol dependency"}
    M-->>S: PONG · count 6
    Note over S,R: Injected NoWait · round 4
    %% Evidence: {"basis": "code", "reference": "trace_no_wait.c:270-286; HP disables RX before START_NO_WAIT, polls BURST_DONE before release; CSV3893 NO_WAIT phase"}
    Note over R: RX held by test (code-derived)
    %% Evidence: {"basis": "observed", "reference": "CSV3917; HE CH0_SET"}
    S->>M: PING · A
    rect rgb(255, 238, 232)
    %% Evidence: {"basis": "observed", "reference": "CSV3918; HE CH0_SET; follows CSV3917 before next completion at CSV3934"}
    S->>M: PING · B before PONG
    end
    %% Evidence: {"basis": "protocol", "reference": "This report: Where the issue enters; prior clear CSV3866/completion CSV3871; trace_no_wait.c:270-286,322-340; no intermediate status sample"}
    Note over M: A OR B pending (protocol-derived)
    %% Evidence: {"basis": "observed", "reference": "CSV3928; HP trace_demo_phase=6; trace_no_wait.c:285-286"}
    Note over R: RX_RELEASED phase
    %% Evidence: {"basis": "observed", "reference": "CSV3930/3931; HP CH0_ST=0x33333333 then CH0_CLR=0xffffffff; separate accesses"}
    R->>M: Read A OR B + clear
    %% Evidence: {"basis": "observed", "reference": "CSV3934; HE trace_tx_ack_count=7, delta one from prior CSV3871; callback completion, protocol dependency"}
    M-->>S: PONG · count 7
```

PING denotes the payload write. **PONG denotes the observed HE completion-counter write**, not reply data or the exact hardware-ACK instant. Its arrow depicts the completion dependency. Read/clear combines two observed accesses; the callback lies between them in the driver source. Schematic protocol order; independent clocks; not to scale.

## Where the issue enters

The first relevant divergence is in [`trace_run_he`](../../Examples/IPM_ARM_MHUv2/trace_no_wait.c), lines 325–331: `if (!no_wait)` skips the wait after A, so B reuses channel 0 before the first completion. The corresponding normal round has a captured completion between its two writes.

The test makes this deterministic in `trace_run_hp`, lines 270–286: it disables RX before sending START_NO_WAIT and releases reception only after BURST_DONE. HE sends that token after both payload writes and `DSB` (lines 322–335). Matching round IDs, phase markers and this serialized control handshake support the cross-core association; global CSV row order does not.

MHU channel writes set bits: writing one sets a bit, and zero leaves it unchanged. With the protocol-derived empty starting state, two pending writes produce **inferred `A OR B` state**. The subsequent HP read of `0x33333333` is directly observed. Prior clears/completions and the receiver gate support the inference; the intermediate pending state was not sampled. This demonstration does not imply that arbitrary consecutive writes always merge.

The register interpretation was checked through CMSIS Developer Assistant against `AlifSemiconductor::Ensemble@2.2.1`, SVD `AE722F80F55D5LS_CM55_HE_View`: CH_SET at `0x4009000c` sets bits, CH_ST at `0x40090000` retains them until clear, and the HP-view CH_CLR at `0x40080008` clears written-one bits.

To preserve separate words, wait for completion before reusing the channel. If several messages must be outstanding, use a queue with explicit ownership and acknowledgments.

## Evidence and limits

Physical [CSV](ipm-ping-pong-multi-2026-10-28.csv) lines include the header as line 1. Each read below is followed by one all-ones clear on HP; each completion is a counter write on HE.

| Round | HE writes A / B | HP reads / clears | HE completions; counter |
| --- | --- | --- | --- |
| 3 · normal | 3856 / 3869 | 3852, 3865 / 3853, 3866 | 3858, 3871; 4 → 6 |
| 4 · NoWait | 3917 / 3918 | 3930 / 3931 | 3934; 6 → 7 |
| 9 · NoWait | 4249 / 4250 | 4263 / 4264 | 4267; 15 → 16 |

Across all twelve rounds, the ten normal rounds each contain two writes, reads, clears and completions. Rounds 4 and 9 each contain two writes but one read, clear and completion. All 22 completion-counter writes are contiguous values 1–22, with no observed reset, wrap or jump; the initial zero is source-derived.

The recorded acquisition used AC6 6.24.0 and ULINKplus `L39352482A`; the snapshot was taken at **2026-10-28 10:28:20 UTC**. Its pyTS 1.0.0 profile mapped the following four-byte accesses:

| Stream | DWT0 | DWT1 | DWT2 | DWT3 |
| --- | --- | --- | --- | --- |
| 1 · HE | CH0_SET write, `0x4009000c` | `trace_demo_round` write | `trace_demo_phase` write | `trace_tx_ack_count` write |
| 2 · HP | CH0_ST read, `0x40080000` | CH0_CLR write, `0x40080008` | `trace_demo_round` write | `trace_demo_phase` write |

Round markers contain value only; the other comparators record PC and value. The [symbolic NoWaitMulti profile](../../Examples/IPM_ARM_MHUv2/.cmsis/ipm_arm_mhuv2-ac6+DevKit-E7-NoWaitMulti.ctrace.yml) is the current project configuration, not an archived generated capture profile. Source attribution relies on the recorded acquisition association and identities below; no new binary-to-source check was performed.

<details>
<summary>Recorded source identities (SHA-256)</summary>

| Source | SHA-256 |
| --- | --- |
| [NoWait firmware](../../Examples/IPM_ARM_MHUv2/trace_no_wait.c) | `0dc9a52654061080ba956149bfda30f185a72c4dba54764e40fa00372401ac94` |
| [AC6 solution](../../Examples/IPM_ARM_MHUv2/ipm_arm_mhuv2-ac6.csolution.yml) | `ade0bd83318fa5554f09e15ecd358e2919247d1ec14b529c1af19de013c35186` |
| [NoWait configuration](../../Examples/IPM_ARM_MHUv2/trace_no_wait_config.cmake) | `ed55515352d3d346be9d38d465e90f2431fdd8d6d495a3209acc82b8768e7b1f` |
| [MHU driver at recorded SDK commit](https://github.com/alifsemi/zephyr_alif/blob/3a2b84d96961b53431a78685c6ec0f0df4ddf347/drivers/ipm/ipm_arm_mhuv2.c) | `8e3b860c0c3c892369ded51a60de08e31522996039c6e97ac7f423dd5c6f39b0` |

Repository-relative links follow the checkout; these hashes identify the source reviewed for this capture.

</details>

All expected mapped events are present for the twelve rounds. Boundary decoder info at CSV2/4496 reports skipped bytes; there are no error/overflow records. This does not prove globally lossless capture. HE and HP clocks have no verified synchronization relation, so cross-core latency is unmeasured.

CSV SHA-256: `0763da8af8cd8e004d739b202a0c94bc5545ff93026a6298e3ef988d44add39c`.
