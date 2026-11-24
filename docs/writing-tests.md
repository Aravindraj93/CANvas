# YAML scenarios

```yaml
name: Signal demonstration
bus: virtual
steps:
  - action: log
    message: No hardware is used by this scenario.
  - action: wait
    ms: 100
```

Run `canvas test scenario.yaml --report report.html` or use the desktop/browser
YAML tab. This example returns **INCOMPLETE**, not PASS: it performs no assertion.
The CLI exits zero only for PASS. Load/enable the appropriate DBC in the saved
workspace before running signal scenarios. Physical buses must be explicitly
configured; no adapter is required for virtual use.

## Supported steps

| Action | Required fields | Optional fields |
|---|---|---|
| send_signal | message, signal, value | dbc_id |
| send_message | message, signals (nonempty mapping) | dbc_id |
| wait | ms (integer, 0–3600000) | |
| assert_signal | message, signal, expected | dbc_id, max_age_ms (1–3600000), tolerance (>= 0) |
| assert_visual | baseline (name, not path) | threshold (0–1) |
| log | message | |

Every step may have description. Top-level fields are name, description, bus and
steps. Names must be nonempty strings; numerical values must be finite. Defined
DBC text choices are accepted for value/expected and send_message values.
Unknown actions/fields, empty scenarios, invalid ranges, missing DBC fields and
invalid choice names are rejected before execution. Use dbc_id to disambiguate
messages present in multiple enabled DBCs. Encoding/adapter errors can still
occur at runtime; preflight is not a guarantee of successful transmission.

## Verdicts

- **PASS**: steps succeeded and at least one verification assertion passed.
- **FAIL**: transmission failure or unsuccessful signal/visual comparison.
- **ERROR**: verification infrastructure (for example screen capture/baseline)
  could not execute correctly.
- **INCOMPLETE**: no successful verification, or skipped checks.
- **CANCELLED**: cancellation was requested; later steps were not executed.

RX assertions inspect fresh received frames, not TX acceptance or TX echo.
A virtual send does not simulate an ECU response; a responder is needed to
produce RX evidence. Visual comparisons require a prepared local baseline.

Explicit CLI --bus overrides YAML bus. With neither, an existing connection is
used, otherwise virtual is chosen. An explicitly requested bus type that differs
from the existing connection is rejected. CLI execution disconnects on exit.

Cancel test cooperatively interrupts waits and prevents later steps. Stop TX in
the desktop additionally latches transmission off and stops cyclic workers.
An in-progress adapter/screenshot call cannot be forcibly interrupted. Resume TX
allows new work only; it does not replay cancelled sends, tests or cycles.

