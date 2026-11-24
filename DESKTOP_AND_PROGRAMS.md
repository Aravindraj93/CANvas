# CANvas 0.4.2: native desktop, programs, saved DBCs and favorites

For saved DBC loading recovery and the persistent error banner, read **DBC_LOADING_FIX.md**.

See **DESKTOP_UPDATE.md** for the redesigned layout, faster search, Enter / + / -
sending, zero-scale DBC import handling and CAN FD setup.

For the latest search-focus fix, tolerant matching, favorites filter button and
default-on FD checkbox, read **UI_SEARCH_AND_RX.md**.

## Start the Windows desktop application

1. Stop the previous CANvas web server so the desktop app can open your ValueCAN.
2. Extract this ZIP into a new folder. Keep your old project folder until your
   bench check passes.
3. Double-click **Setup_CANvas.bat** once. It creates or updates the local Python
   environment with the desktop and ValueCAN dependencies. Python 3.10 or newer
   must be installed and available as `python`.
4. Double-click **Start_CANvas.bat**. It opens a native Qt desktop window. The
   desktop does not open a browser and does not run a local HTTP server.
5. Select **Intrepid ValueCAN / neoVI**, set the wired ICS network (for example,
   HSCAN), nominal bitrate, and CAN FD/data bitrate/BRS settings matching the bench.
   Enter the device serial only if needed. Click Connect.

Your existing Intrepid Product Drivers are still required. Do not select Virtual
when you intend to send to the physical bench.

You can also launch it from an activated environment:

```bat
python -m pip install -e ".[desktop,valuecan]"
canvas-desktop
```

If startup fails before the window opens, inspect
`%USERPROFILE%\.canvas\desktop-startup.log`.

## Build an executable on Windows

Double-click **Build_Windows_EXE.bat**. It builds:

```text
dist\CANvas\CANvas.exe
```

Keep the entire `dist\CANvas` folder together when copying the app; its supporting
files are required. The resulting executable bundles Python and Qt. Intrepid
Product Drivers remain a separate installation on the target bench PC.

This ZIP contains source, the native launcher and the Windows build script;
it does **not** contain a prebuilt Windows executable. The native Qt interactions
were tested in Linux offscreen mode. Windows executable packaging and the new
release's physical bench behavior still need validation on your Windows PC.

## Programs / applications

- Choose an existing program in the Program / app list, or click **New program**.
- A new program starts with the current DBC selection and an empty favorites list.
- Each program remembers its active DBCs, favorite messages and favorite signals.
- Switching programs stops cyclic transmission and resets the editing context.
  Transmissions never resume automatically on startup.
- Existing saved favorites migrate into the **Default** program.

Use programs such as Powertrain, HVAC, Trailer Tow or your own application names.
DBC files are shared across programs; their active selection and favorites are
separate. Removing a stored DBC removes its references and favorites from all
programs, so the Remove action asks for confirmation.

## Saved DBCs and favorites

Use **Add DBC files** to import several files at once. Check the files to activate
them in the selected program. Files are stored once on the computer running
CANvas and restored after the application closes or the browser refreshes.

The default data location is `%USERPROFILE%\.canvas\workspace.sqlite3` on Windows.
It stays available when you extract a newer CANvas project into another folder.
Set `CANVAS_DATA_DIR` to an absolute directory before launch if you need another
location. Close CANvas before copying the data directory as a backup.

Identical uploads are deduplicated. Different DBCs defining the same CAN ID can
now be active together. Every message row identifies its source DBC; TX uses the
selected row’s definition. Only one cyclic stream may own a CAN ID at a time.
The monitor flags shared IDs until you select a decoding DBC. Traffic counters
are per CAN ID, not per definition. See DESKTOP_UPDATE.md for details.

Click a star beside a message or signal, then enable **Favorites only**. A starred
message shows all its signals. If only individual signals are starred, the view
shows those signals. Sending visible values retains the last sent values of the
other signals in the same message.

## Text choices and raw values

Signals with DBC value tables offer choices such as Initialization, ACC, RUN,
START and SNA. The dropdown displays each label with its raw code. The numeric
editor uses the physical value after applying the DBC scale and offset; the
native desktop also shows the raw value in a separate column.

For example, `CmdIgnSts = RUN` may encode raw value 4 when that mapping is defined
in the loaded DBC. CANvas reads the mapping; it does not hardcode these labels.
Signals without a value table use a numeric editor. Arbitrary formulas and the
reference tool's Equation option are not implemented.

The API and YAML send steps also accept a defined choice label:

```yaml
- action: send_signal
  message: BCM_FD_10
  signal: CmdIgnSts
  value: RUN
```

If a message name appears in several active DBCs, supply its `dbc_id` in YAML/API
steps. The desktop and browser select the DBC automatically. Full IDs are
available from `GET /api/dbc/state` when using the browser server.

## The MAP_4_BAR = 511 error

The reported error says a value of 511 was encoded while the DBC numeric maximum
is 408. The old code could use an out-of-range DBC initial value for an unchanged
companion signal and prevent the entire message from being sent.

This version validates initial values and uses a valid, representable default
when an initial value is invalid. The signal's notes show the adjustment. Named
initial values are converted from their raw codes using the DBC scale and offset,
so a raw SNA code is not mistaken for a physical measurement. A
regression test reproduces `ENGINE_FD_8` with `MAP_4_BAR` initialized to 511 and
range 0..408, then verifies that changing another signal sends successfully.

Explicit invalid input is still rejected with the signal name and allowed range.
Validation is not disabled and explicit numeric inputs are not silently clamped.
If the DBC explicitly defines raw 511 as a named SNA/reserved choice, that choice
remains selectable even outside the ordinary numeric range. Without your actual
DBC, we cannot establish whether 511 is intended as an SNA value in that file.

## Message status and verification

Message status separates:

- **TX:** sends accepted by the CAN backend.
- **TX echo:** a transmitted-frame echo reported by the adapter.
- **RX:** a frame received from the bus, with its latest age and decoded values.
- **Stale / decode error / TX error:** traffic age, format problems or send failures.

A message becomes stale after three DBC cycle times or 1000 ms, whichever is
longer. Disconnecting, changing active definitions or switching programs resets
live evidence so old frames cannot verify a new session.

**Verify latest RX** compares the visible expected values with the latest fresh
received frame. Set the maximum RX age as appropriate for the message. Numeric
comparisons allow half the DBC signal resolution. Missing, stale, malformed or
mismatching RX data fails verification. A send or TX echo alone cannot pass.

This checks bus evidence, not HMI consumption. A receiving HMI may not retransmit
the same message. In that case use TX echo / an independent CAN trace for message
transmission, and check the HMI display separately.

The YAML `assert_signal` action now checks actual fresh RX data rather than
returning a placeholder PASS. Example:

```yaml
- action: assert_signal
  message: BCM_FD_10
  signal: CmdIgnSts
  expected: RUN
  max_age_ms: 1000
```

## Browser interface remains available

The saved DBC list, programs, favorites, text choices and RX status are also
available through `canvas serve`. The built frontend is included. To rebuild it:

```bat
cd frontend
npm ci
npm run build
```

Use one controller at a time for a given adapter. Close the desktop before
starting the browser server to work with that adapter, and vice versa.

## Validation

The automated suite covers ValueCAN configuration, CAN FD frames, signal value
retention, saved-file restoration, scoped favorites, program migration and
selection, named/scaled choices, invalid initial values, cyclic workers, fresh RX
verification, native Qt controls and monitor delivery. A real HTTP server restart
also restored saved DBCs and a favorite without replaying transmissions.

Run the tests, including native controls, with:

```bat
python -m pip install -e ".[dev,desktop]"
python -m pytest -q
```

Official references:
- https://python-can.readthedocs.io/en/stable/interfaces/neovi.html
- https://cantools.readthedocs.io/en/latest/
- https://doc.qt.io/qtforpython-6/gettingstarted.html
