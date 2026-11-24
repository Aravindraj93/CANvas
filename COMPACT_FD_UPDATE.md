# CANvas 0.4.3 — compact CAN FD checkbox

The CAN FD checkbox beside Connect/Disconnect has a smaller indicator, less
padding and a lighter appearance. Its tick scales to the indicator size, and
the control is vertically centered. Label and checkbox remain clickable.

The default-on setting, saved explicit FD-off choice and Apply & reconnect
behavior are retained. This release also retains the 0.4.2 DBC loading recovery
and the earlier search/Enter/favorites fixes.

Close CANvas, extract this ZIP into a new folder, run Setup_CANvas.bat once,
then Start_CANvas.bat. Saved DBCs/programs/favorites use the existing data folder.
The archive includes source and Windows launch/build scripts, not a prebuilt EXE.

## Validation for this small UI change

Linux offscreen Qt checks measured the indicator from 22 to 16 logical pixels,
and the control size hint from 101x36 to 83x24. These measurements depend on
platform/style/font. Mouse and Space-key toggling work; default enabled state
and no automatic connection are preserved. Layout was checked at 100% and 150%
scale with a 1000x700 logical window. Windows/physical hardware were not accessed.
The complete 82-test result in DBC_LOADING_FIX.md applies to the previous 0.4.2
release; that full suite was not rerun for this styling-only patch.

## Proposed next improvements — not included in this release

1. Correct YAML verdicts and enforce the requested hardware/profile before
   sending. A missing required check must produce ERROR/INCOMPLETE rather than
   an unqualified PASS. Reject invalid signal names/actions/values before TX.
2. Keep Stop/Cancel available during tests and queued sends. Stop cyclic work,
   cancel unsent requests and report any driver call already in progress.
3. Record timestamped CAN TX/echo/RX independently of the open UI tab, with raw
   payloads, channel, queue drops, requested/actual cyclic timing and run export.
   Use traces to investigate intermittent behavior rather than guessing CRC or
   counter requirements from signal names.
4. Add named bench profiles and explicit HSCAN/HSCAN2 routing. Show the selected
   channel per send; design independent receive state and cyclic ownership before
   adding simultaneous channels. A DBC file alone does not select a CAN port.
5. Add signal presets: Ignition RUN, parked state, Pitch/Roll scenarios, ramps
   and repeat counts. Preview all messages and apply only through an explicit
   user action. Store presets per program without replaying them at startup.
6. Add an ADB device/display selector, direct Android screenshots, region-based
   text/icon/value checks and before/after evidence linked to SONIC/VF/CFTS IDs.
7. Add requirement-grounded AI drafts using the configured corporate models
   after execution and evidence are dependable. Validate generated tests against
   actual loaded DBCs and supported actions before running them.

These priorities build on the earlier review. YAML verdict gaps, cancellation,
recording and Android capture remain pending; this UI patch does not implement
them. More detailed DBC precision/multiplexer and Windows distribution work from
the review also remains necessary.
