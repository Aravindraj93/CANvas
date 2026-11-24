# CANvas 0.4.1 — search, favorites and CAN FD

Close CANvas, extract this ZIP into a new folder, run Setup_CANvas.bat once and
then Start_CANvas.bat. Saved DBCs, programs and favorites remain available from
the existing data directory. This package includes source and Windows launcher /
executable-build scripts, not a prebuilt Windows executable.

## What changed

**Search retains keyboard focus.** The original issue was reproduced: after the
first letter and result refresh, focus moved from the search input to a new result
button. The fix restores search focus, caret and text selection after the entire
message/signal refresh. Tests type through the actual focused widget with pauses
longer than the debounce interval; they do not simply address key events directly
to the search field regardless of where focus has moved.

**Search tolerates different spelling formats.** Case, spaces, underscores and
hyphens do not need to match. `pitch angle` matches `PitchAngle`; `engine fd 8`
matches `ENGINE_FD_8`. Partial text also works. Direct normalized matches take
priority. If none exist, queries of at least four alphanumeric characters try a
small edit distance (including adjacent swapped letters) and show **approximate
matches**, closest first. For example `mpa4bar` can find `MAP_4_BAR`. This is typo
matching, not semantic/synonym search. Favorites filtering and source DBCs still
apply; fuzzy matching never changes a signal's actual identity or encoding.

**Favorites-only is an obvious button.** Click the bordered **☆ Favorites only**
button next to search to turn the filter on. It becomes green with **★ Favorites
only** while active; click again to return to all messages. This filter does not
add favorites. Use the message/signal **☆ Add / ★ Saved** buttons to add or remove
favorites for the current program.

**CAN FD is a checkbox at the top beside Connect/Disconnect.** It is checked by
default on a fresh launch and when migrating settings from the old FD-button UI.
Once you explicitly uncheck it and successfully apply that configuration in this
version, the saved choice is respected on later launches. The checkbox stays
available when advanced settings are collapsed. Clicking it opens those settings.

Check nominal/data bitrates and BRS against your bench, then click **Apply &
connect/reconnect**. Changing the checkbox alone does not reconnect the adapter.
The connection summary describes the active connection, while the checkbox is
the setting to apply. This patch does not enable BRS automatically or infer rates
from a DBC. It does not automatically connect or resume sending at startup.

## What are TX, TX echo and RX?

| Term | Meaning in CANvas |
| --- | --- |
| TX — transmit | CANvas sends an encoded CAN frame through the selected backend. TX accepted means the backend returned successfully. |
| TX echo | The adapter reports a copy/receipt of its transmitted frame. It is tracked separately from incoming traffic. |
| RX — receive | A CAN frame arrives from the bus and is marked as received by the backend. CANvas can decode it using the selected DBC definition. |

A TX result or TX echo alone does not establish that the HMI displayed or consumed
the value correctly. RX counts are by CAN ID and standard/extended format, so
shared DBC definitions share raw traffic evidence.

## What does Verify latest RX do?

It compares the values currently visible in the selected signal editors with the
latest received frame for that message ID, decoded using the selected DBC.

- The adapter must be connected and an RX frame must exist.
- Its age must be within **Max age**, normally 1000 ms by default.
- Its CAN/FD format and payload length must match the definition.
- Compared signal values must match, allowing the configured numeric resolution.

The result fails if RX is missing, stale, malformed or different. It checks the
latest snapshot; it does not wait for a future matching frame. It is a CAN-bus
value check, not a screenshot/UI check or proof that a particular ECU consumed
our transmission. TX echoes are deliberately excluded.

For example, if your HMI receives BCM_FD_4 but does not retransmit that CAN ID,
its display may change while Verify latest RX still reports **No RX frame**.
That is different from a failed TX. Use the TX/echo evidence or an independent
trace for transmission, and inspect/capture the actual HMI for display behavior.

## What are YAML Tests?

YAML is a readable text format. The **YAML Tests** tab lets you open or write a
sequence of automation instructions and run it: set ignition RUN, send a pitch
value, wait, check a received value, or make a visual comparison. The runner's
current actions are send_signal, send_message, wait, assert_signal, assert_visual
and log. Ambiguous message names require the correct dbc_id.

`assert_signal` checks fresh received CAN values. `assert_visual` invokes the
current image-capture/comparison implementation. The existing capturer targets
the computer screen; Android ADB capture has not yet been implemented.

The prior review identified unresolved verdict/mode gaps in YAML execution:
required visual checks can be skipped after capture errors while the suite still
reports PASS, and requested hardware mode is not fully enforced. This UI patch
does not fix those separate runner issues. Treat YAML outcomes as experimental;
a PASS alone is not physical HMI validation.

## Validation

75 automated tests passed, including focus across slow typing and refreshes,
caret/selection, no-result recovery, partial/normalized/fuzzy search and ranking,
favorites scope, visible controls, default-FD migration, saved explicit FD-off
choice, and the previous UI/CAN/persistence regressions. The frontend build also
passed. Qt tests and visual inspection used Linux offscreen mode. Windows and
physical ValueCAN/bench behavior still need validation on your PC.
