# CANvas

**Explore DBC signals. Control CAN traffic. Automate HMI bench checks.**

[![CI](https://github.com/Aravindraj93/CANvas/actions/workflows/ci.yml/badge.svg)](https://github.com/Aravindraj93/CANvas/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](RELEASE_CHECKLIST.md)

CANvas is an open-source CAN/CAN FD signal and HMI bench-testing tool for automotive developers and test engineers. Load your DBCs, send meaningful signal values, inspect live traffic, and turn repeatable checks into YAML scenarios with HTML reports.

Start with a virtual CAN bus, then configure a supported adapter for your development bench. The native Qt desktop app is the primary interface; a local browser UI and CLI are also included.

[Get started](#get-started) · [Write scenarios](docs/writing-tests.md) · [Bench setup](BENCH_SETUP.md) · [Contribute](CONTRIBUTING.md) · [Report a bug](https://github.com/Aravindraj93/CANvas/issues/new/choose)

## What you can do

- **Work with DBCs:** save multiple databases, organize programs, search messages and signals, and use named choices instead of raw numbers.
- **Control signals:** edit physical values, send whole messages, run cyclic transmissions, and reuse favorites and signal notes.
- **See what was sent:** inspect session signal history, encoded TX values, counts, and active cycles alongside the bus monitor.
- **Automate checks:** write YAML for signal sends, waits, received-signal assertions, and visual comparisons against prepared baselines.
- **Review results:** generate HTML reports with verdicts, step details, and durations.
- **Draft scenarios with optional AI:** use Gemini when configured or local templates otherwise. Review generated YAML before execution.

**Status: 0.4.6 alpha, desktop-first.** Hardware qualification and clean-machine executable checks remain open. CANvas is intended for authorized, isolated development benches; it is not safety-certified or hard-real-time. See the [release checklist](RELEASE_CHECKLIST.md).

## Get started

### Native desktop

Requirements: **Python 3.10+** with pip and Git. Node.js is only needed to build the browser UI. Windows is the primary desktop target.

```sh
git clone https://github.com/Aravindraj93/CANvas.git
cd CANvas
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
# Linux / macOS shell
source .venv/bin/activate
```

Install and launch:

```sh
python -m pip install -e ".[desktop]"
canvas-desktop
```

On Windows you can also use `Setup_CANvas.bat`, then `Start_CANvas.bat`. Setup installs desktop and ValueCAN dependencies; Intrepid drivers are installed separately. Start from a fresh clone: copied virtual environments are not portable.

### Try signals without hardware

1. Launch the desktop app and select a virtual bus connection.
2. Add the included synthetic DBC, [`tests/fixtures/sample.dbc`](tests/fixtures/sample.dbc), to a program and enable it.
3. Browse a message, edit a signal value, and send it.
4. Inspect **Session Signals** for transmitted values and counts. Try a cyclic send, then stop it.

A virtual bus lets you explore the workflow without an adapter. It does not simulate an ECU: received-signal assertions need a separate responder, and successful TX does not establish ECU reception or HMI behavior.

### Local browser UI

After installing the Python package, build the frontend with **Node.js 22.12+** and npm:

```sh
cd frontend
npm ci
npm run build
cd ..
canvas serve --bus virtual
```

The launcher opens `http://127.0.0.1:8765`. API documentation is at `/docs`. The server supports loopback access only; remote access is not authenticated or supported. See [security and privacy](SECURITY.md).

### Run a YAML scenario

```sh
canvas test examples/virtual-smoke.yaml --report canvas-report.html
```

This hardware-free example logs a message and waits. It deliberately returns **INCOMPLETE** and exit code **1**, because it contains no verification assertion. The CLI exits zero only for **PASS**.

For signal and visual assertions, see [Writing scenarios](docs/writing-tests.md). The [fuel-warning example](examples/fuel-warning-test.yaml) requires its matching DBC, prepared visual baselines, and an ECU/responder; it is not a standalone demo.

## Choose your interface

| Interface | Scope |
| --- | --- |
| Native desktop | Saved programs/DBCs, favorites and notes, signal controls, session TX history, bus monitor, YAML execution |
| Local browser | DBC/signal controls, live traffic, YAML execution/cancellation, optional AI generation |
| CLI | Local browser launcher and YAML execution with HTML reports |

Desktop and browser features differ. Reports contain textual results; embedded screenshot evidence is not yet included.

In the desktop, **Cancel test** interrupts waits and prevents later steps. **Stop TX** also pauses new transmission, cancels queued manual sends, and stops cycles. **Resume TX** permits new work without restarting cycles or replaying cancelled sends. An adapter call already in progress may finish; software controls are not a physical emergency stop.

## Hardware and CAN FD

CANvas uses `python-can`. Availability of an upstream backend does not mean its physical behavior has been qualified by this project.

| Backend | Current evidence |
| --- | --- |
| Virtual | Hardware-free automated test coverage |
| Intrepid ValueCAN / neoVI | Desktop integration and setup guide; adapter/driver bench qualification remains necessary |
| SocketCAN, PCAN, Kvaser, Vector and others | Configurable through CLI/API where supported upstream; physical behavior unverified by this test suite |

For ValueCAN / neoVI, install `python -m pip install -e ".[desktop,valuecan]"`, install the vendor drivers, then follow [Bench setup](BENCH_SETUP.md) for channels, bitrates, CAN FD, BRS, and verification.

## Documentation

- [Desktop and saved programs](DESKTOP_AND_PROGRAMS.md)
- [Bench setup and adapter configuration](BENCH_SETUP.md)
- [YAML actions, assertions, and verdicts](docs/writing-tests.md)
- [Security, local data, and optional AI disclosure](SECURITY.md)
- [Contributing and development setup](CONTRIBUTING.md)
- [Release and packaging checklist](RELEASE_CHECKLIST.md)
- [Changelog](CHANGELOG.md)

## Help shape CANvas

Useful contributions include sanitized bug reproductions, clearer documentation, virtual-bus regression tests, and hardware results that identify the adapter, driver, bitrates, and FD/BRS configuration. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

Never attach customer DBCs, private traces, API keys, or unredacted diagnostics to public issues. With Gemini configured, generation sends prompts and DBC-derived metadata to Google's service; review [SECURITY.md](SECURITY.md) before use.

If CANvas helps your workflow, star the repository and share it with an engineer who could use it. Real bench feedback and contributions help the project improve.

## License

[MIT](LICENSE) · Copyright 2026 CANvas contributors.

Third-party libraries and vendor drivers retain their own licenses. Review redistribution obligations before distributing packaged executables.
