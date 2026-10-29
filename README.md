# Zephyr-Alif (Work in Progress)

This repository contains an example CMSIS solution that builds two basic Zephyr examples for Alif development boards.
It can be easily adapted to other boards or examples. It uses Zephyr's `west` build system to create the application
image and the [Arm CMSIS Debugger](https://marketplace.visualstudio.com/items?itemName=Arm.vscode-cmsis-debugger) to
download the image to flash memory and run it on the target hardware.

## Quick start

The example setup uses an Arm [ULINKplus debug adapter](https://www.arm.com/products/development-tools/debug-probes/ulink-plus) connected to the
[Alif Semiconductor DevKit-E7](https://www.keil.arm.com/boards/alif-semiconductor-devkit-e7-d1-cd88670/guide/).

- Install the [Arm Keil Studio Pack for VS Code](https://marketplace.visualstudio.com/items?itemName=Arm.keil-studio-pack),
  then clone this repository and open its folder in VS Code.
- [Install Alif Zephyr SDK 2.3](#zephyr-installation) and [configure its environment variables](#configure-vs-code).
- Restart VS Code, then select **CMSIS > ... > Open Solution in Workspace** and open the example's
  `*-gcc.csolution.yml` or `*-ac6.csolution.yml` file for the compiler you want to use.
- Use **Manage Solution Settings** to select the board and application, then **Build solution**.
- Connect the board and select **Load & Debug application**. See [Work with the example](#work-with-the-example) for
  dual-core projects.

> [!NOTE]
> Use **Arm CMSIS Solution 1.72.0+** and **Arm CMSIS Debugger 1.10.0+**.
> The debugger includes the trace decoder and automatic CSV export.

> [!TIP]
> If configuration or build errors occur, use **Clean All 'out' and 'tmp' directories** from the CMSIS view menu to
> remove stale CMake cache files before rebuilding.

## Zephyr installation

The following instructions apply to Linux, macOS, and Windows. Install a supported version of Python 3 and Git before
continuing.

> [!WARNING]
> On Windows, use Python 3.13 or earlier because the `windows-curses` package is not yet available for Python 3.14.

### Create the workspace

- Open a terminal as a regular user. On Windows, use `cmd.exe` for the commands below.

- In any suitable working directory, create an `sdk-alif` directory and change into it:

  ```console
  mkdir sdk-alif
  cd sdk-alif
  ```

- Create a virtual environment. Use the command for your operating system:

  Linux and macOS:

  ```sh
  python3 -m venv .venv
  ```

  Windows:

  ```bat
  python -m venv .venv
  ```

- Activate the virtual environment.

  Linux and macOS:

  ```sh
  source .venv/bin/activate
  ```

  Windows (`cmd.exe`):

  ```bat
  .venv\Scripts\activate.bat
  ```

  Once activated, the shell prompt is prefixed with `(.venv)`. Activate the environment again whenever you open a
  new terminal. Run `deactivate` to leave it.

- Install `west`. After activation, `python` refers to the virtual environment on every supported operating system:

  ```console
  python -m pip install west
  ```

- Get the Zephyr source code using the Alif SDK:

  ```console
  west init -m https://github.com/alifsemi/sdk-alif.git --mr v2.3.0
  west update
  ```

- Apply the Arm Compiler linker compatibility patch required by Alif SDK 2.3. Replace `/path/to/Zephyr-Alif-1` with
  the absolute path to this repository:

  ```console
  git -C zephyr apply /path/to/Zephyr-Alif-1/.github/patches/sdk-alif-v2.3.0-armclang-linker.patch
  ```

  The patch is harmless for GCC builds and is also applied by this repository's CI workflow.

- Install the Python dependencies required by Zephyr:

  ```console
  python -m pip install -r zephyr/scripts/requirements.txt
  ```

### Configure VS Code

The CMSIS Solution extension needs the Zephyr workspace and virtual environment paths when it runs `west`.

1. In VS Code, open **Settings** and search for **Cmsis-Csolution: Environment Variables**.
2. Select the **User** or **Workspace** setting and choose **Add Item** for each variable below. Replace `<work-dir>`
   with the directory in which you created your `sdk-alif` workspace.

   | Variable | Linux and macOS | Windows |
   |---|---|---|
   | `ZEPHYR_BASE` | `/<work-dir>/sdk-alif/zephyr` | `C:\<work-dir>\sdk-alif\zephyr` |
   | `PATH` | `/<work-dir>/sdk-alif/.venv/bin` | `C:\<work-dir>\sdk-alif\.venv\Scripts` |
   | `VIRTUAL_ENV` | `/<work-dir>/sdk-alif/.venv` | `C:\<work-dir>\sdk-alif\.venv` |

3. Fully restart VS Code so that the extension uses the new environment.

For more information, see [Work with Zephyr applications](https://mdk-packs.github.io/vscode-cmsis-solution-docs/zephyr.html#set-environment-variables).

### C library selection

Each example has a separate CMSIS solution for each compiler and explicitly selects that compiler's default C
library:

| Solution filename | Compiler | C library |
|---|---|---|
| `*-gcc.csolution.yml` | GCC | Full Newlib |
| `*-ac6.csolution.yml` | Arm Compiler 6 | Arm Compiler C library |

GCC solutions select full Newlib:

```yml
west-defs:
  - CONFIG_NEWLIB_LIBC: y
  - CONFIG_NEWLIB_LIBC_NANO: n
```

AC6 projects use the Arm Compiler C library:

```yml
west-defs:
  - CONFIG_ARMCLANG_STD_LIBC: y
```

These definitions are passed to Zephyr by `west build`. The selection is explicit because
`CONFIG_REQUIRES_FULL_LIBC` only requests any complete C library and may select Picolibc instead of the library
provided by the compiler toolchain.

## SETOOLS

Before flashing an example to the DevKit-E7 board, program the device's ATOC using Alif SETOOLS. This process only has
to be performed once for each single- or dual-core project.

Refer to the section [Usage](https://github.com/alifsemi/alif_ensemble-cmsis-dfp/blob/main/docs/Overview.md#usage)
on the Alif Semiconductor Ensemble DFP/BSP overview page for information about how to set up these tools.

In VS Code, select **Terminal > Run Task** and run:

- **Alif: Install M55_HE and M55_HP debug stubs (dual core configuration)**

## DevKit-E7 UART console

The DevKit-E7 routes one application UART at a time to the second channel of the on-board USB-to-UART bridge. Connect
the **PRG USB** port and configure header **J26** for the core whose `printk` output you want to monitor:

| Core | Console UART | J26 jumpers |
|---|---|---|
| M55_HE (RTSS-HE), including LPI2C | UART2 | Pins 1-3 and 2-4 |
| M55_HP (RTSS-HP) | UART4 | Pins 3-5 and 4-6 (factory default) |

These core assignments come from the Alif SDK 2.3 E7 board devicetrees.
The SETOOLS single-/dual-core configuration does not change the physical UART
routing. The factory J26 setting therefore selects the HP console for these builds.

Open the application UART serial port at **115200 baud, 8 data bits, no parity, and 1 stop bit (8-N-1)**. Do not use
the other USB serial channel, which is the SEUART used by SETOOLS for programming. Power off the board before moving
the J26 jumpers.

Open the terminal before starting the application to see its startup output.
The examples do not print continuously: LPI2C runs one transfer test,
and IPM runs ten message-exchange iterations before returning. Debug stubs alone do not run
these examples, and a core halted at `main()` has not executed their main output yet.

J26 cannot connect UART2 and UART4 to the on-board bridge simultaneously. To monitor output from both cores in the
`IPM_ARM_MHUv2` example, connect a separate **1.8 V-compatible** USB-to-UART adapter and a common ground to the UART
that is not selected by J26.

## E7 buffered trace

The IPM targets provide short, repeatable trace investigations:

| IPM target | What to show |
| --- | --- |
| **DevKit-E7** | Original ten-round exchange; reference behavior. |
| **DevKit-E7-NoWait** | Nine acknowledged pairs, then two writes before acknowledgment: HP receives one merged word. |
| **DevKit-E7-NoWaitMulti** | Twelve rounds; two PINGs before one PONG in rounds 4 and 9. [Mermaid comparison](./docs/examples/ipm-ping-pong-multi-2026-10-28.md) · [hardware CSV](./docs/examples/ipm-ping-pong-multi-2026-10-28.csv). |
| **DevKit-E7-TraceDelay** | A 50 ms delay in the fifth HE receive callback; all ten rounds complete. |
| **DevKit-E7-TraceDelayMulti** | Twelve rounds; 15 ms and 30 ms delays in HE channel-0 receives 3 and 8. [Mermaid explanation and timeline](./docs/examples/ipm-trace-delay-multi-2026-10-28.md) · [hardware CSV](./docs/examples/ipm-trace-delay-multi-2026-10-28.csv). |
| **DevKit-E8** | Existing board target; the E7 trace demonstrations and debug hooks are not validated here. |

Select the target in either IPM compiler solution; no source edit is needed.
The [trace overview](./docs/README.md) links the figures, CSVs and validation notes.

The project-local [Trace Data skill](./.agents/skills/trace-visualization/SKILL.md)
explains captures together with source using native Mermaid. Codex discovers it
from `.agents/skills/`; other agents can follow [AGENTS.md](./AGENTS.md).

The NoWait and TraceDelay scenarios passed earlier AC6 Debug hardware capture
checks. The [NoWaitMulti](./docs/README.md#hardware-validation-twelve-rounds-and-two-nowait-events)
and [TraceDelayMulti](./docs/README.md#hardware-validation-twelve-rounds-and-two-delays)
validation notes record the tested runs, capture limits and debugger diagnostics.

**LPI2C / DevKit-E7** remains a single-core trace introduction: HE PC sampling,
ITM and automatic buffered capture. Previous validation covered startup, idle
and repeated capture/export; no I2C fault diagnosis was established.

## Example descriptions

| Example name                              | Description   |
|---                                        |---            |
| [IPM_ARM_MHUv2](./Examples/IPM_ARM_MHUv2/) | This example demonstrates dual-core debugging and inter-core communication between two Cortex-M55 cores using Arm's Message Handling Unit v2 (MHUv2). It uses Zephyr's Inter-Processor Mailbox (IPM) API to exchange messages and trigger interrupts between the cores. More details in [Alif-Zephyr-SDK/ipm_arm_mhuv2](https://github.com/alifsemi/sdk-alif/tree/v2.3.0/samples/drivers/ipm/ipm_arm_mhuv2). |
| [LPI2C](./Examples/LPI2C/) | LPI2C (Low Power Inter-Integrated Circuit) is a low-power version of the standard I2C bus controller. This example uses two threads to emulate an I2C master and slave communicating through the LPI2C driver. All data transfers occur internally via hardware loopback. More details in [Alif-Zephyr-SDK/lpi2c](https://github.com/alifsemi/sdk-alif/tree/v2.3.0/samples/drivers/lpi2c). |

## Work with the example

For an **IPM / DevKit-E7 target / Debug** configuration:

1. Select the target and available board probe, wait for target setup to finish,
   then **Build** both images.
   The debugger automatically converts the committed `.cmsis/*.ctrace.yml` profile
   against the selected target's build output; no manual conversion or generated
   trace configuration is required after cloning.
2. Use **Load & Debug application**. The HP launch loads both images, resets
   both cores together, starts HE and stops HP at `main()`. After a target change,
   verify that the loaded ELF and cbuild-run belong to the selected target.
3. **Continue HP**. NoWait and NoWaitMulti stop at their completion breakpoint; verify
   `trace_demo_result == 1`. Normal and TraceDelay finish ten rounds;
   TraceDelayMulti finishes twelve. **Pause** or stop afterwards. The debugger
   automatically decodes the buffer to `.trace/<solution>+<target>.TB.csv`
   and opens the trace data. No separate export command is needed.
4. Preserve `.TB.raw`, `.TB.csv` and `.ctrace-run.yml` from the example's
   `.trace/` directory before another Continue replaces the capture.
   Use **Reset** in the HP launch or a fresh **Load & Debug** to repeat.

The project-local reset and trace hooks use a shared 64 KiB SRAM0 buffer;
GDB controls HP while both cores are traced. The installed Pack and pyOCD are
unchanged. Keep `updateConfiguration` set to `auto`; after changing a launch
or task drop-in, run **Update Debug Tasks and Launch Configurations**.
The E7 hooks require adaptation before use with E8 or different image addresses.

For **LPI2C / DevKit-E7 / Debug**, select its compiler solution, build, then
**Load & Debug** and **Continue HE**. Pause after the transfer test to obtain the
CSV in that example's `.trace/` directory. The SDK environment, selected probe
and one-time board preparation above are the only machine-specific prerequisites;
capture profiles, buffer reservations and debug hooks are supplied by this repository.
