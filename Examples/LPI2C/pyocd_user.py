"""DevKit-E7 HE trace lifecycle, loaded automatically by the CMSIS Debugger.

The source configuration comes from the project's generated ctrace-run file.
This script supplies the E7 sink setup and uses pyOCD's native raw file output.
Validation scope: ../../README.md, "E7 buffered trace" section.
"""

import time


BUFFER_BASE = 0x023F0000
BUFFER_SIZE = 0x10000
ETR = 0x140000
CATU = 0x150000
ITM_TCR = 0xE0000E80
SOURCE_REGS = (0xE000EDFC, ITM_TCR, 0xE0000E00, 0xE0000E40, 0xE0001000)
ROUTE_REGS = (0x100000, 0x110000, 0x110004)
_trace = None


def is_e7_debug(target):
    # This bundled gdbserver creates Session with command=None; load/erase/reset
    # set an explicit command and must not initialize the shared trace sink.
    return (session.command in (None, "gdbserver", "gdb")
            and target.part_number.upper() == "AE722F80F55D5LS")


def he_core(target):
    cores = [core for core in target.cores.values() if core.node_name == "M55_HE"]
    if len(cores) != 1:
        raise Error("E7 trace requires exactly one M55_HE core")
    return cores[0]


class E7Trace:
    """One owner of the shared SoC ETR, with bounded flush and readout."""

    def __init__(self, target):
        self.target = target
        self.dp = target.dp
        self.core = he_core(target)
        self.active = False
        self.owned = False
        self.failed = False
        self.capture_number = 0
        self.last_size = 0
        self.source = {address: self.core.read32(address) for address in SOURCE_REGS}
        self.route = {address: self.dp.read_ap(address) for address in ROUTE_REGS}
        for base, part in ((0x100000, 0x9EB), (0x110000, 0x9EC),
                           (ETR, 0x9E8), (CATU, 0x9EE)):
            actual = self.dp.read_ap(base + 0xFE0) | ((self.dp.read_ap(base + 0xFE4) & 15) << 8)
            if actual != part or self.dp.read_ap(base + 0xFA4):
                raise Error("E7 trace component is unexpected or already claimed at %#x" % base)
        if self.dp.read_ap(ETR + 0x20) & 1 or self.dp.read_ap(CATU) & 1:
            raise Error("E7 ETR/CATU is already active; refusing to replace another capture")
        LOG.info("E7 trace ready: M55_HE -> SoC ETR/CATU -> SRAM0 %#x (%d bytes)",
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
            # RRD also uses CATU: disable it only after ETR has finished.
            self.dp.write_ap(ETR + 0x20, 0)
            self.wait(ETR + 0x0C, 4, 4)
            self.dp.write_ap(CATU, 0)
            self.wait(CATU + 0x100, 0x100, 0x100)
        self.active = False

    def reset(self):
        # POST_RESET invalidates the previous capture and source configuration.
        self.disable()
        self.failed = False

    def capture(self):
        if self.failed:
            raise Error("E7 trace failed; reset the debug session before resuming")
        if self.active:
            return
        if self.core.get_state() != Target.State.HALTED:
            raise Error("E7 trace setup requires halted M55_HE")
        if not self.core.read32(0x1A602014) & (1 << 24):
            raise Error("E7 trace SRAM0 clock is disabled")
        self.wait(ETR + 0x0C, 4, 4)
        self.wait(CATU + 0x100, 0x100, 0x100)
        tcr = self.core.read32(ITM_TCR)
        if not tcr & 1 or not tcr & 0x7F0000:
            raise Error("E7 trace needs an enabled ITM source and TraceBusID in ctrace-run")

        self.owned = True
        try:
            # Hold the source while replacing the sink; re-enable SYNC after it.
            self.core.write32(ITM_TCR, tcr & ~5)
            for offset in (0x004, 0x008, 0x00C, 0x020, 0x024, 0x028, 0x02C):
                self.dp.write_ap(CATU + offset, 0)
            # Circular buffer, stop on manual flush, non-cacheable single beats.
            # AXICTL=0 was verified on this board; no AXICTL1/revision assumption.
            for offset, value in ((0x028, 0), (0x034, 0), (0x304, 0x1003),
                                  (0x01C, 0), (0x308, 0xA), (0x018, BUFFER_BASE),
                                  (0x014, BUFFER_BASE), (0x11C, 0),
                                  (0x118, BUFFER_BASE), (0x004, BUFFER_SIZE // 4),
                                  (0x110, 0), (0x03C, 0), (0x038, 0), (0x00C, 0x20)):
                self.dp.write_ap(ETR + offset, value)
            self.dp.write_ap(0x100000, (self.route[0x100000] & ~0xFF) | 4)
            self.dp.write_ap(0x110000, 0xFF)
            self.dp.write_ap(0x110004, 0)
            self.dp.write_ap(CATU, 1)
            self.dp.write_ap(ETR + 0x20, 1)
            self.target.flush()
            # A new raw file needs an initial ITM synchronization packet even
            # when pyocd has not reapplied an unchanged ctrace-run configuration.
            self.core.write32(ITM_TCR, tcr | 4)
            self.core.flush()
            self.active = True
            self.capture_number += 1
            LOG.info("E7 trace capture %d started", self.capture_number)
        except Exception:
            self.failed = True
            self.disable()
            raise

    def flush(self):
        if not self.active:
            return
        try:
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
                # Repeat reads of the same RRD register, not incrementing addresses.
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
            LOG.info("E7 trace capture %d exported: %d bytes, full=%s, PC=%#x",
                     self.capture_number, len(raw), bool(status & 1),
                     self.core.read_core_register("pc"))
        except Exception:
            self.failed = True
            raise
        finally:
            self.disable()

    def stop(self):
        try:
            if self.active:
                self.core.halt()
                self.flush()
        finally:
            self.disable()
            if self.owned:
                for address in (ITM_TCR, 0xE0000E00, 0xE0000E40,
                                0xE0001000, 0xE000EDFC):
                    self.core.write32(address, self.source[address])
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
    _trace.capture()
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


@command("e7_reset", help="Reset LPI2C M55_HE and enter its MRAM reset vector")
def e7_reset():
    if not is_e7_debug(target):
        raise Error("e7_reset is only for this E7 debug configuration")
    core = he_core(target)
    vector = 0x80000000
    sp, pc = core.read_memory_block32(vector, 2)
    if not (0x20000000 <= sp <= 0x20040000 and sp % 8 == 0
            and vector <= (pc & ~1) < vector + 0x580000 and pc & 1):
        raise Error("LPI2C has no valid M55_HE vector table at %#x" % vector)
    boot = core.memory_map.get_boot_memory()
    if boot is not None and boot.start != vector:
        raise Error("Boot memory conflicts with the LPI2C MRAM image")
    core.reset_and_halt(Target.ResetType.SYSTEM)
    # The installed cbuild-run map has no boot-region attribute. A warm reset
    # can retain VTOR=0 pointing into the loader's TCM workspace. Explicitly
    # select this project's MRAM vector before pyocd's emulated core reset.
    core.write32(0xE000ED08, vector)
    core.reset_and_halt(Target.ResetType.EMULATED)
    LOG.info("E7 HE reset at %#x, SP=%#x, VTOR=%#x",
             core.read_core_register("pc"), core.read_core_register("sp"), core.read32(0xE000ED08))
