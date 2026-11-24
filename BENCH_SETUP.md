# CANvas: ValueCAN bench setup

For the native Windows desktop, programs, saved DBCs, favorites and text choices,
start with [DESKTOP_AND_PROGRAMS.md](DESKTOP_AND_PROGRAMS.md).

## What caused the symptom

The uploaded project starts with `--bus virtual`. Its connection UI did not offer
Intrepid ValueCAN / neoVI, so the green connection banner only confirmed a
software simulation. Connecting an ADB cable and a ValueCAN USB cable does not
change that bus selection.

ADB accesses Android for logs, shell commands and screenshots. The CAN send path
is CANvas → Intrepid driver → ValueCAN → bench CAN wiring → target ECU / gateway → HMI.
The backend must run on the Windows computer with the ValueCAN connected.

The original sender also omitted CAN FD frame flags, reset companion signals on
individual sends, and swallowed cyclic transmission errors.

## Install on Windows

1. Extract this archive into a new folder. It includes the updated source and a
   built frontend. Keep your existing checkout until the bench check passes.
2. Install the **Intrepid Product Drivers** for your device:
   Use the Intrepid Product Drivers link in the official setup documentation:
   https://python-can.readthedocs.io/en/stable/interfaces/neovi.html
   Confirm your device appears in the Intrepid utility.
3. Open Command Prompt in the extracted `canvas` folder:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[valuecan]"
canvas serve
```

Install into the same Python environment that runs CANvas. If `python-ics` has no
compatible build for your Python version, use a version supported by that package
and recreate the environment. Do not reuse the `.venv` from the original ZIP.

The server opens http://127.0.0.1:8765. Startup still selects Virtual for simulation;
it now clearly says that no physical bench frames are transmitted.

If you modify the frontend later, rebuild it from `canvas\frontend`:

```bat
npm ci
npm run build
```

## Connect to the physical bench

1. Click **Disconnect** to leave Virtual.
2. Select **Intrepid ValueCAN / neoVI**.
3. Enter the ICS network name for the wired port. Start with **HSCAN** for CAN1.
   For CAN2, verify its network name in the Intrepid device configuration;
   **HSCAN2** is a possible ICS name. Do not assume physical port 2 means net ID 2.
4. Leave the serial field blank when only one adapter is connected, or enter its
   exact serial to select it explicitly.
5. Set the nominal bitrate to the bench's actual configuration. Enable **CAN FD**
   only for an FD-capable adapter and network. Set the FD data bitrate and **BRS**
   to match the bench. The field defaults are examples, not detected bus settings.
6. Click **Connect**. The banner must show **neovi**, the channel, and the adapter
   description. A failed hardware connection stays failed; it never falls back
   to Virtual.
7. Load your actual DBC, set PitchAngle / RollAngle and click **Send All**. This
   sends one complete frame. To send periodically, set the required cycle time
   and click **Cyclic**. The DBC cycle time is used when present; otherwise the
   initial field value is 100 ms. Set the value your ECU specification requires.
8. During cyclic sending, edit values and click **Apply & Send**. Stop transmission
   before changing channel or bitrates. The Disconnect action also stops cyclic
   workers automatically.

For an example network configured for **500 kbit/s nominal, 2 Mbit/s data, FD with
BRS**, you can connect at startup instead of using the form:

```bat
canvas serve --bus neovi --channel HSCAN --bitrate 500000 --fd --data-bitrate 2000000 --bitrate-switch
```

Those rates are an example. Use your bench's rates and omit the FD options for a
classical CAN network. Add `--serial YOUR_DEVICE_SERIAL` if needed.

## Verify the path to the HMI

- **Connection:** `neovi` confirms the physical adapter was opened. ADB connection
  state is independent of this.
- **Transmission:** check the send error text and accepted-send counter. In Bus
  Monitor, filter for `0x41B` and compare payload bytes before and after changing
  the angles. RX and adapter TX echo are labeled separately. An adapter accepting
  a frame or reporting its transmission does not prove the HMI consumed it.
- **Independent bus check:** use a suitable external CAN trace or receiver on the
  same network to establish that the expected frame reaches the bench wiring.
- **ECU acceptance:** if the correct frame is present but the HMI does not update,
  check routing/gateway configuration, ignition/network wake-up, DBC version,
  frame format, cycle time, validity bits, alive counters, application checksums,
  and another bench node transmitting the same ID.
- **Driver/network error:** a `bad net ID` or bitrate-setting failure is shown with
  the original error. Check the ICS network name and adapter settings, and verify
  the device works in the Intrepid utility.

CAN FD is determined by DBC metadata (or payloads longer than eight bytes), not
by a message name containing `_FD_`. An eight-byte FD message needs the correct
DBC frame-format metadata. CANvas does not automatically implement ECU-specific
alive counters, application CRCs or wake-up sequences.

## Changes and validation

- Added ValueCAN / neoVI UI settings, optional serial, FD data bitrate and BRS.
- Propagated connection settings through the API and startup CLI to python-can.
- Applied DBC frame-format information to transmitted frames; an FD frame on a
  classical connection produces an explicit error.
- Retained companion signal values and used defaults within declared ranges.
- Validated the first cyclic send, reported later failures, and stopped cyclic
  workers on disconnect and DBC replacement.
- Corrected forwarding from the CAN reader thread to the WebSocket event loop.
- Made failed sends fail YAML send steps instead of reporting PASS.
- Added `tests/test_can_bench.py`; 18 tests passed locally using real virtual CAN
  buses and mocked hardware initialization. TypeScript compilation and the Vite
  production build passed. Interactive browser checks were not completed because
  the test browser download was unavailable. No physical ValueCAN or Android bench
  was available in the test environment.

In version 0.2, YAML `assert_signal` uses fresh received CAN data. A send or TX
echo alone cannot pass it. It does not prove HMI consumption. The HMI capture
module is not an ADB CAN transport.

Run the regression tests after installing the development extra:

```bat
python -m pip install -e ".[dev]"
python -m pytest -q
```

Reference: https://python-can.readthedocs.io/en/stable/interfaces/neovi.html
