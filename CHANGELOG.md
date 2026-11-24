# Changelog

## Unreleased

- Full-text DBC choices and a program-scoped Session Signals tab with shared
  editors, accepted TX history, multiplexing status and cyclic controls.
- Strict YAML validation and DBC field/range preflight before test execution.
- Explicit ERROR, CANCELLED and INCOMPLETE verdicts. Send/log-only scenarios no
  longer imply that ECU or HMI verification passed.
- Desktop Cancel test and latched Stop TX / Resume TX; cancellation of queued
  manual requests, cancellation-aware waits and workspace-specific YAML sending.
- Browser test cancellation, single-run execution and latest-100 result history.
- Local-only web launcher, HTTP/WebSocket Host/Origin checks and bounded live
  frame buffering with slow-client timeouts.
- Frontend asset packaging, release checks, CI, license and contribution/security
  documentation.

## 0.4.6

- Side-by-side messages/signals and highlighted program-specific signal notes.

