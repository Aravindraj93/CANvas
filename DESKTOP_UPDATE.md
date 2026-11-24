# CANvas 0.4 desktop update

Close the older CANvas application/server, extract into a new folder, run
**Setup_CANvas.bat** once, then **Start_CANvas.bat**. Existing DBCs, programs and
favorites remain in `%USERPROFILE%\.canvas`, or your configured `CANVAS_DATA_DIR`.
Python 3.10+ and the existing Intrepid Product Drivers are required. Source,
launch scripts and a Windows executable build script are included; a prebuilt
Windows executable is not included.

## Multiple DBC files, including your shared 0x5B0 ID

The error screenshot shows the same standard CAN ID 0x5B0 in PMASAH_E3A_R1_FD-CAN8
and PDT7_E2A_R6_FDCAN8. Earlier versions rejected that overlap. Version 0.4 allows
both DBCs to remain active and keeps each definition associated with its source.

- In **Add DBC files**, use Ctrl/Shift to choose several files, or add them one
  at a time. Previously stored files do not need uploading again.
- In the saved-file list, **Enable all** activates every saved DBC in the program.
- Alternatively Ctrl/Shift-select files, then **Use selected** activates those
  files. Individual checkboxes still work.
- The DBC column identifies the source for every message row. Sending encodes
  using the selected row's definition. Identical names in different DBCs remain
  separate; API/YAML callers must supply dbc_id for ambiguous message names.
- Shared IDs display a source note. Only one cyclic definition can transmit a
  given CAN ID at a time; stop that stream before sending another definition.
- The monitor's **Auto DBC** mode flags shared IDs instead of silently choosing
  a decoder. Choose the desired DBC in its source dropdown to decode them.

CAN traffic does not contain the DBC filename. TX/echo/RX counters and raw evidence
are shared by CAN ID, not independent proof that either DBC matches the bench.
Fresh RX verification decodes against the selected definition; it does not verify
which DBC the receiving ECU expects.

## Configure FD beside Connect / Disconnect

**Configure FD** is always visible in the top connection bar. It checks the FD
option and opens settings while leaving the current connection unchanged.

1. Choose the correct network (such as HSCAN for the wired CAN1 connection).
2. Confirm nominal bitrate, data bitrate and BRS using the bench specification.
3. Click **Apply & reconnect** if already connected, or **Apply & connect** if
   disconnected. Apply stops cyclic sends and opens the adapter with the new
   settings. The top summary reports the resulting connection configuration.

The old Connect/Disconnect button still connects or disconnects normally.
Editing a setting alone does not reconfigure the active connection. Successful
settings are saved and restored next launch; connection/transmission never
starts automatically. Failed settings do not replace the last successful setup,
although the failed attempt leaves the adapter disconnected and shows its error.

If a ValueCAN is already correctly configured in neoVI Explorer and bitrate
writes fail, **Use adapter's saved bitrates (ValueCAN)** skips nominal/data
bitrate writes. CAN FD permission and transmitted BRS flags still follow the
checkboxes. The summary explicitly says saved rates are not read back; configure
and confirm the actual adapter rates/mode in neoVI Explorer first. This option
does not repair an incorrect hardware configuration.

FD frames remain blocked on a Classical CAN connection. Classical frames stay
Classical even on an FD-enabled connection. CANvas does not guess bench bitrates,
BRS requirements or vendor-specific device FD-mode enums.

## Enter, text choices, and clear favorite controls

Numeric Enter is captured directly from the actual line-edit child, so it does
not depend on a platform forwarding Enter to the surrounding spin box. Typing
alone stays local. Enter sends once per press; - / + steps send each new value.
Text choices send on actual user activation, including selecting the same choice
again. Rebuilding widgets or restoring selections does not transmit anything.

Favorites are bordered, labeled, checkable buttons: **☆ Add** and **★ Saved**.
Tooltips identify the message/signal and whether clicking adds or removes it.
Favorites remain separate for each program.

**Last action** beside each signal reports Queued, TX accepted, Blocked or Error
with a request number. It retains the latest result when widgets are refreshed;
hover for the value/source or exact error. A successful driver send is labeled
TX accepted, not HMI verified. Repeated Enter/choice actions are separate requests.

## Trace the one-or-two-updates problem

This release fixes desktop event handling and adds evidence for failures beyond
the UI. Without your physical bench, the intermittent HMI response is not yet
confirmed fixed. If it continues:

1. Send several different values and watch Last action and TX counts.
2. Check TX echo, RX age and decoded values, or an independent physical bus trace.
3. Click **Save diagnostics** beside Connect. The JSON includes the latest 200
   UI requests/results, selected message/DBC metadata, versions, connection and
   receiver errors, TX/echo/RX counts and latest raw payloads. Raw DBC files and
   ADB screenshots are not collected.
4. Share that JSON with the affected DBC/message and the configured bench rates.

If requests are blocked or erroring, the result identifies the local reason. If
TX/echo rises but the HMI stops responding, bench-side investigation must check
whether another source overwrites the ID, the message needs continuous cyclic
traffic, or counter/checksum/E2E fields must change. No counter or checksum
algorithm is inferred or auto-generated from a field name. Use **Start cyclic**
with the specified cycle time when continuous transmission is required.

The reader polling interval is reduced, stopped receiver exceptions are exposed,
and browser monitor decoding no longer runs on the neoVI receipt thread. These
changes avoid a reader callback waiting on the sender while the sender waits for
its transmission receipt. They do not establish the cause of the user's physical
bench intermittence without a trace.

## Validation and limits

61 automated tests passed, including real Qt child-editor typing/Enter, actual
popup mouse selection, repeated sends after favorite refresh, multiple active
DBCs sharing 0x5B0 with different scaling, source-specific decoding, competing
cyclic prevention, successful/failed FD apply, setting persistence, saved-rate
kwargs, reader failures, receipt-thread delivery, and previous regressions.
The TypeScript/Vite production build passed. Desktop checks used Linux offscreen
Qt. Windows setup/executable packaging and physical ValueCAN/HMI operation still
require validation on your PC.

Official setup references:
- https://python-can.readthedocs.io/en/stable/interfaces/neovi.html
- https://cdn.intrepidcs.net/guides/vcan4-2/vcan4-2_ug.pdf
