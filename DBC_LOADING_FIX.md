# CANvas 0.4.2 — DBC lists and startup recovery

## Confirmed failure and scope

An empty search with Favorites only off should show the messages from loaded
DBCs. A selected checkbox previously meant that the file was enabled in the
saved program, even if startup had failed to load it.

The old startup path restored all selected DBCs as one batch. A parse or
validation error in any one file prevented every file from reaching the message
list. The files still appeared active. The only error appeared in the footer,
where connecting the adapter replaced it with Ready. This failure was reproduced
with a valid DBC beside a failing saved DBC. The exact failing file/error from the
reported three-file Windows workspace has not been captured yet.

## Changes

- Startup and program switching load enabled DBCs independently. A failed file
  no longer suppresses messages from the valid files.
- A persistent banner above the list names failed files and their errors. The
  full error is in its tooltip and Save diagnostics. Connecting does not hide it.
- The sidebar distinguishes enabled files from successfully loaded files. A
  failed file stays selected so its saved selection is preserved, and its text
  and tooltip identify the failure.
- Reload DBCs retries enabled files from their saved bytes. It stops cyclic
  sending and resets retained send values/traffic evidence, without reconnecting
  the adapter or transmitting anything. It preserves programs, DBC bytes and
  favorites. Failed definitions are not sent with a relaxed parser.
- Empty states distinguish a loading failure, no enabled DBCs, no favorites and
  no search match. Counts include the number of loaded messages.
- Save diagnostics includes the current program, file names, enabled/loaded
  states, per-file errors, loaded message count and search/favorites filters,
  including when no message can be selected. It does not include raw DBC files.

## Use this update

1. Close CANvas, extract this ZIP into a new folder, and run Setup_CANvas.bat
   once, then Start_CANvas.bat. The package contains source and Windows launcher /
   build scripts, not a prebuilt Windows executable.
2. Select your program. Leave Favorites only off and clear the search initially.
3. The sidebar shows enabled and loaded counts. Valid DBCs should populate the
   message list, even if another file fails.
4. If a banner appears, read the filename/error and try Reload DBCs. Unchecking
   the failed file allows the other selected files to remain enabled.
5. If the list is still blank, click Save diagnostics and share the JSON. Do not
   delete your workspace database or saved DBCs to troubleshoot this.

The prior search-focus, typo matching, Enter / step / text-choice sending and
default CAN FD checkbox fixes remain. YAML verdict limitations described in
UI_SEARCH_AND_RX.md remain pending.

## Validation

Automated coverage includes failed parse and duplicate-ID validation isolation,
preserved saved bytes/program selection/favorites, recovery after a transient
failure, a new Python process loading the saved workspace, searching usable
messages beside a failed file, a persistent error after connecting/retrying,
and diagnostic export with all files failed. All 82 automated tests passed; the frontend production build passed.

The previously uploaded PDT27_E2A_R6_FDCAN8.dbc was tested separately: 323 messages
loaded on a fresh launch and PitchAngle search worked. That customer DBC is not
included in this package. Qt checks use Linux offscreen mode; Windows and the
physical ValueCAN/HMI bench remain unverified here.
