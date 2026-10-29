"""Paired E7 IPM reset and dual-core buffered trace for the CMSIS Debugger.

HE waits for incoming messages; HP remains halted until GDB runs to main.
The image addresses and DTCM bounds match this example's E7 Zephyr builds.
Source configuration and RAW output are native pyOCD/ctrace-run facilities.
This hook supplies the shared E7 ETR/CATU lifecycle missing from the Pack.
"""

import time


VTOR = 0xE000ED08
MHU0_RX = 0x40080000
IMAGES = (("M55_HE", 0x80000000, 0x20040000),
          ("M55_HP", 0x80200000, 0x20100000))
BUFFER_BASE = 0x023F0000
BUFFER_SIZE = 0x10000
ETR = 0x140000
CATU = 0x150000
ITM_TCR = 0xE0000E80
DWT_CYCCNT = 0xE0001004
SOURCE_REGS = ((0xE000EDFC, ITM_TCR, 0xE0000E00, 0xE0000E40, 0xE0001000)
               + tuple(0xE0001020 + index * 16 + offset
                       for index in range(8) for offset in (0, 4, 8)))
ROUTE_REGS = (0x100000, 0x110000, 0x110004)
_trace = None


def is_e7_debug(target):
    return (session.command in (None, "gdbserver", "gdb")
            and target.part_number.upper() == "AE722F80F55D5LS")


class E7Trace:
    """One shared sink, with source setup deferred until native refs are applied."""

    def __init__(self, target):
        self.target = target
        self.dp = target.dp
        self.cores = []
        for name, _, _ in IMAGES:
            matches = [core for core in target.cores.values() if core.node_name == name]
            if len(matches) != 1:
                raise Error("E7 trace requires exactly one %s core" % name)
            self.cores.append(matches[0])
        self.he, self.hp = self.cores
        self.active = self.pending = self.owned = self.failed = False
        self.detaching = False
        self.resume_he = False
        self.capture_number = self.last_size = 0
        self.last_raw = None
        self.source = {core.node_name: {address: core.read32(address) for address in SOURCE_REGS}
                       for core in self.cores}
        self.route = {address: self.dp.read_ap(address) for address in ROUTE_REGS}
        for base, part in ((0x100000, 0x9EB), (0x110000, 0x9EC),
                           (ETR, 0x9E8), (CATU, 0x9EE)):
            actual = self.dp.read_ap(base + 0xFE0) | ((self.dp.read_ap(base + 0xFE4) & 15) << 8)
            if actual != part or self.dp.read_ap(base + 0xFA4):
                raise Error("E7 trace component is unexpected or already claimed at %#x" % base)
        if self.dp.read_ap(ETR + 0x20) & 1 or self.dp.read_ap(CATU) & 1:
            raise Error("E7 ETR/CATU is already active; refusing to replace another capture")
        session.subscribe(self.before_hp_run, Target.Event.PRE_RUN, self.hp)
        LOG.info("E7 IPM trace ready: HP + HE -> ETR/CATU -> SRAM0 %#x (%d bytes)",
                 BUFFER_BASE, BUFFER_SIZE)

    def wait(self, address, mask, expected):
        deadline = time.monotonic() + 1.0
        while True:
            value = self.dp.read_ap(address)
            if value & mask == expected:
                return value
            if time.monotonic() >= deadline:
                raise Error("E7 trace timeout at %#x: value %#x, mask %#x, expected %#x" %
                            (address, value, mask, expected))
            time.sleep(0.001)

    def disable(self):
        if self.owned:
            # RRD uses CATU, so it must remain enabled until readout finishes.
            self.dp.write_ap(ETR + 0x20, 0)
            self.wait(ETR + 0x0C, 4, 4)
            self.dp.write_ap(CATU, 0)
            self.wait(CATU + 0x100, 0x100, 0x100)
        self.active = self.pending = False

    def reset(self):
        self.disable()
        self.resume_he = self.failed = self.detaching = False
        self.last_raw = None

    def last_hp_client_detached(self):
        # v78 starts another capture when its last GDB client detaches from a
        # halted core. The native RAW sink truncates on every capture event.
        # Inspect the published server objects; never modify their lifecycle.
        servers = [server for server in session.gdbservers.values()
                   if server.target is self.hp]
        return bool(servers) and not any(client.is_attached_to_target
                                        for server in servers
                                        for client in server.client_sessions)

    def prepare(self):
        if self.failed:
            raise Error("E7 trace failed; reset the debug session before resuming")
        if self.last_hp_client_detached():
            # Native capture will reopen RAW after this delegate returns. Keep
            # the completed recording and restore it at PRE_RUN instead of
            # replacing it with a new recording of the post-detach idle loop.
            self.flush()
            self.detaching = self.pending = True
            return
        if self.active or self.pending:
            return
        if self.hp.get_state() != Target.State.HALTED:
            raise Error("E7 IPM trace capture must be controlled by halted M55_HP")
        # Native trace_capture applies both pnames after this delegate returns.
        # Keep HE stopped through those writes and until the shared sink is ready.
        self.resume_he = self.he.get_state() in (Target.State.RUNNING, Target.State.SLEEPING)
        self.he.halt()
        if self.he.get_state() != Target.State.HALTED:
            raise Error("E7 trace could not halt M55_HE for source configuration")
        self.pending = True

    def before_hp_run(self, notification):
        if not self.pending:
            return
        try:
            if self.detaching:
                if self.last_raw is not None:
                    if self.target.write_trace_buffer("", self.last_raw) != len(self.last_raw):
                        raise Error("E7 trace output did not preserve the completed capture")
                    session.notify(session.Event.TRACE_DATA_FLUSH, session)
                    LOG.info("E7 IPM capture preserved on GDB detach: %d bytes", len(self.last_raw))
                self.detaching = self.pending = False
                return
            self.capture()
            # Clear pending before HE.resume(), which sends its own PRE_RUN.
            self.pending = False
            if self.resume_he:
                self.he.resume()
            self.resume_he = False
        except Exception:
            self.failed = True
            self.pending = False
            self.disable()
            # Propagate to HP.resume(): neither image executes a partial setup.
            raise

    def capture(self):
        if self.failed:
            raise Error("E7 trace failed; reset the debug session before resuming")
        if any(core.get_state() != Target.State.HALTED for core in self.cores):
            raise Error("E7 trace setup requires both M55 cores halted")
        if not self.hp.read32(0x1A602014) & (1 << 24):
            raise Error("E7 trace SRAM0 clock is disabled")
        tcrs = [core.read32(ITM_TCR) for core in self.cores]
        ids = [(tcr >> 16) & 0x7F for tcr in tcrs]
        if not all(tcr & 1 for tcr in tcrs) or 0 in ids or len(set(ids)) != 2:
            raise Error("E7 IPM trace needs two enabled ITM sources with distinct TraceBusIDs")
        self.wait(ETR + 0x0C, 4, 4)
        self.wait(CATU + 0x100, 0x100, 0x100)
        self.owned = True
        for core, tcr in zip(self.cores, tcrs):
            core.write32(ITM_TCR, tcr & ~5)
        for offset in (0x004, 0x008, 0x00C, 0x020, 0x024, 0x028, 0x02C):
            self.dp.write_ap(CATU + offset, 0)
        # Proven LPI2C sink setup: circular, manual-flush stop, AXICTL=0.
        for offset, value in ((0x028, 0), (0x034, 0), (0x304, 0x1003),
                              (0x01C, 0), (0x308, 0xA), (0x018, BUFFER_BASE),
                              (0x014, BUFFER_BASE), (0x11C, 0),
                              (0x118, BUFFER_BASE), (0x004, BUFFER_SIZE // 4),
                              (0x110, 0), (0x03C, 0), (0x038, 0), (0x00C, 0x20)):
            self.dp.write_ap(ETR + offset, value)
        # Ensemble E7.sdf: HP port 1, HE port 2, replicator output 1 to ETR.
        self.dp.write_ap(0x100000, (self.route[0x100000] & ~0xFF) | 6)
        self.dp.write_ap(0x110000, 0xFF)
        self.dp.write_ap(0x110004, 0)
        self.dp.write_ap(CATU, 1)
        self.dp.write_ap(ETR + 0x20, 1)
        self.target.flush()
        for core, tcr in zip(self.cores, tcrs):
            core.write32(ITM_TCR, tcr | 4)
            # Native v78 sync runs before PRE_RUN and only for the GDB core.
            # Repeat its reversible CYCCNT edge for BOTH halted sources after
            # enabling the sink; unchanged ctrace-run files need this too.
            cyccnt = core.read32(DWT_CYCCNT)
            try:
                core.write32(DWT_CYCCNT, cyccnt ^ ((1 << 24) | (1 << 26) | (1 << 28)))
            finally:
                core.write32(DWT_CYCCNT, cyccnt)
            core.flush()
        self.active = True
        self.last_raw = None
        self.capture_number += 1
        LOG.info("E7 IPM capture %d started: HE stream %d, HP stream %d",
                 self.capture_number, ids[0], ids[1])

    def flush(self):
        if not self.active:
            return
        resume = []
        tcrs = []
        try:
            for core in self.cores:
                if core.get_state() in (Target.State.RUNNING, Target.State.SLEEPING):
                    resume.append(core)
                core.halt()
                if core.get_state() != Target.State.HALTED:
                    raise Error("E7 trace could not halt %s for flush" % core.node_name)
            # Stop new packets before requesting formatter flush.
            for core in self.cores:
                tcr = core.read32(ITM_TCR)
                tcrs.append((core, tcr))
                core.write32(ITM_TCR, tcr & ~1)
                core.flush()
            self.dp.write_ap(ETR + 0x304, 0x1043)
            self.wait(ETR + 0x304, 0x40, 0)
            status = self.wait(ETR + 0x0C, 4, 4)
            if status & 0x20:
                raise Error("E7 ETR memory error; trace was not exported")
            raw = bytearray()
            remaining = BUFFER_SIZE // 4 + 1
            complete = False
            while remaining:
                count = min(64, remaining)
                words = self.dp.read_ap_multiple(ETR + 0x10, count)
                remaining -= count
                for word in words:
                    if word == 0xFFFFFFFF:
                        complete = True
                        break
                    raw.extend(word.to_bytes(4, "little"))
                if complete:
                    break
            if not complete:
                raise Error("E7 ETR RRD did not terminate within the reserved buffer")
            if self.dp.read_ap(ETR + 0x0C) & 0x20:
                raise Error("E7 ETR memory error during readout")
            if raw and self.target.write_trace_buffer("", bytes(raw)) != len(raw):
                raise Error("E7 trace output did not accept the complete capture")
            self.last_size = len(raw)
            self.last_raw = bytes(raw)
            LOG.info("E7 IPM capture %d exported: %d bytes, full=%s",
                     self.capture_number, len(raw), bool(status & 1))
        except Exception:
            self.failed = True
            raise
        finally:
            self.disable()
            # Preserve source configuration for the next native capture, which
            # need not reapply unchanged refs. Preserve HE's run state on Pause.
            if not self.failed:
                for core, tcr in tcrs:
                    core.write32(ITM_TCR, tcr)
                self.target.flush()
                for core in resume:
                    core.resume()

    def stop(self):
        session.unsubscribe(self.before_hp_run, Target.Event.PRE_RUN)
        self.pending = False
        try:
            for core in self.cores:
                core.halt()
            self.flush()
        finally:
            self.disable()
            if self.owned:
                for core in self.cores:
                    saved = self.source[core.node_name]
                    core.write32(ITM_TCR, 0)
                    for address in SOURCE_REGS:
                        if address not in (ITM_TCR, 0xE000EDFC):
                            core.write32(address, saved[address])
                    core.write32(ITM_TCR, saved[ITM_TCR])
                    core.write32(0xE000EDFC, saved[0xE000EDFC])
                for address, value in self.route.items():
                    self.dp.write_ap(address, value)
                self.target.flush()


def trace_start(target, mode):
    global _trace
    if not is_e7_debug(target):
        return False
    if _trace is None:
        _trace = E7Trace(target)
    else:
        _trace.reset()
    return True


def trace_capture(target, mode):
    if _trace is None:
        return False
    _trace.prepare()
    return True


def trace_flush(target, mode):
    if _trace is None:
        return False
    _trace.flush()
    return True


def trace_stop(target, mode):
    global _trace
    if _trace is None:
        return False
    try:
        _trace.stop()
    finally:
        _trace = None
    return True


@command("e7_ipm_trace_recover", help="Stop an orphaned ETR matching this IPM project's exact buffer and route")
def e7_ipm_trace_recover():
    """Explicit recovery after a killed server, invoked with trace output off.

    This never runs automatically. The operator must first confirm that no
    other debug session owns the E7. Mismatched components, claims, routing or
    buffer allocation are rejected before either core or sink is changed.
    """
    if not is_e7_debug(target):
        raise Error("E7 IPM trace recovery requires this project's E7 debug configuration")
    if _trace is not None:
        raise Error("Disable trace output before recovering an orphaned E7 capture")
    dp = target.dp
    cores = []
    for name, _, _ in IMAGES:
        matches = [core for core in target.cores.values() if core.node_name == name]
        if len(matches) != 1:
            raise Error("E7 trace recovery requires exactly one %s core" % name)
        cores.append(matches[0])
    for base, part in ((0x100000, 0x9EB), (0x110000, 0x9EC),
                       (ETR, 0x9E8), (CATU, 0x9EE)):
        actual = dp.read_ap(base + 0xFE0) | ((dp.read_ap(base + 0xFE4) & 15) << 8)
        if actual != part or dp.read_ap(base + 0xFA4):
            raise Error("E7 trace recovery rejected unexpected or claimed component at %#x" % base)
    # The project's capture selects HP/HE ports (0x06). Bundled pyOCD v78's
    # TraceFunnel.init() enables all three inputs again on reconnect (0x07).
    # Accept only those two observed states; keep the remaining guard exact.
    if dp.read_ap(0x100000) & 0xFF not in (6, 7):
        raise Error("E7 trace recovery rejected a foreign funnel route")
    expected = ((0x110000, 0xFF, 0xFF), (0x110004, 0xFF, 0),
                (ETR + 0x118, 0xFFFFFFFF, BUFFER_BASE), (ETR + 0x11C, 0xFFFFFFFF, 0),
                (ETR + 0x004, 0xFFFFFFFF, BUFFER_SIZE // 4),
                (ETR + 0x028, 0xFFFFFFFF, 0), (ETR + 0x110, 0xFFFFFFFF, 0),
                (ETR + 0x304, 0xFFFFFFBF, 0x1003))
    for address, mask, value in expected:
        actual = dp.read_ap(address)
        if actual & mask != value:
            raise Error("E7 trace recovery rejected foreign setup at %#x: %#x" % (address, actual))
    for offset in (0x004, 0x008, 0x00C, 0x020, 0x024, 0x028, 0x02C):
        if dp.read_ap(CATU + offset):
            raise Error("E7 trace recovery rejected non-project CATU configuration")
    if not (dp.read_ap(ETR + 0x20) & 1 or dp.read_ap(CATU) & 1):
        LOG.info("E7 IPM trace sink is already stopped")
        return

    def wait_ready(address, mask):
        deadline = time.monotonic() + 1.0
        while dp.read_ap(address) & mask != mask:
            if time.monotonic() >= deadline:
                raise Error("E7 trace recovery timed out at %#x" % address)
            time.sleep(0.001)

    for core in cores:
        core.halt()
        if core.get_state() != Target.State.HALTED:
            raise Error("E7 trace recovery could not halt %s" % core.node_name)
    dp.write_ap(ETR + 0x20, 0)
    wait_ready(ETR + 0x0C, 4)
    dp.write_ap(CATU, 0)
    wait_ready(CATU + 0x100, 0x100)
    target.flush()
    LOG.info("Explicit E7 IPM orphan recovery complete; both cores and trace sink halted")


@command("e7_ipm_reset", help="Reset both E7 IPM cores, start HE, leave HP halted")
def e7_ipm_reset():
    if (session.command not in (None, "gdbserver", "gdb")
            or target.part_number.upper() != "AE722F80F55D5LS"):
        raise Error("e7_ipm_reset requires the DevKit-E7 IPM debug configuration")

    cores = []
    for name, vector, stack_top in IMAGES:
        matches = [core for core in target.cores.values() if core.node_name == name]
        if len(matches) != 1:
            raise Error("IPM requires exactly one %s core" % name)
        cores.append((matches[0], vector, stack_top))

    try:
        for core, _, _ in cores:
            core.halt()

        # Check both images before changing either core's reset state.
        vectors = []
        for core, vector, stack_top in cores:
            sp, pc = core.read_memory_block32(vector, 2)
            if not (0x20000000 <= sp <= stack_top and sp % 8 == 0
                    and vector <= (pc & ~1) < 0x80580000 and pc & 1):
                raise Error("Invalid %s application vectors at %#x" % (core.node_name, vector))
            boot = core.memory_map.get_boot_memory()
            if boot is not None and boot.start != vector:
                raise Error("Boot memory conflicts with %s application" % core.node_name)
            vectors.append((sp, pc))

        for core, _, _ in cores:
            core.reset_and_halt(Target.ResetType.SYSTEM)
            if core.get_state() != Target.State.HALTED:
                raise Error("%s did not halt after system reset" % core.node_name)

        # Warm core resets retain MHU payloads. Discard the interrupted run's
        # channels through EACH core's local receiver window before clearing
        # NVIC state below. Zephyr's sender init clears its interrupt flags.
        # AHRM0005 v2.10, sections 9.2.4.1 / 9.2.4.3.3 (PDF pp.277-280).
        for core, _, _ in cores:
            for channel in (0, 1):
                core.write32(MHU0_RX + channel * 0x20 + 8, 0xFFFFFFFF)
        for core, _, _ in cores:
            for channel in (0, 1):
                if core.read32(MHU0_RX + channel * 0x20):
                    raise Error("%s MHU0 channel %d did not clear" % (core.node_name, channel))

        # The flash loader can leave VTOR pointing at its TCM workspace.
        # Select the MRAM application explicitly before the emulated reset.
        for (core, vector, _), (sp, pc) in zip(cores, vectors):
            core.write32(VTOR, vector)
            core.reset_and_halt(Target.ResetType.EMULATED)
            if (core.get_state() != Target.State.HALTED
                    or core.read32(VTOR) != vector
                    or core.read_core_register("sp") != sp
                    or core.read_core_register("pc") & ~1 != pc & ~1):
                raise Error("%s did not enter its application reset vector" % core.node_name)

        # HE initializes its receiver while HP is held for GDB's main breakpoint.
        cores[0][0].resume()
        LOG.info("E7 IPM ready: HE running, HP halted at its application reset vector")
    except Exception:
        # Never leave one half of a partially initialized pair running.
        for core, _, _ in cores:
            try:
                core.halt()
            except Exception:
                LOG.exception("Could not halt %s after IPM reset failure", core.node_name)
        raise
