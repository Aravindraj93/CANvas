# Release checklist

## Before publishing source

- Confirm ownership/permission for all contributed code and examples. The root
  LICENSE implements the project's existing MIT declaration, not a provenance audit.
- Inspect staged files and Git history for secrets and private DBCs/traces.
- Enable GitHub private vulnerability reporting and branch protection; require CI.
- Resolve applicable Python/npm vulnerability audit findings and document any
  justified exceptions. Do not equate passing tests with a security audit.
- Update version numbers, CHANGELOG.md and tested hardware/platform results.

## Build and validate

```powershell
python -m pip install -e ".[dev,desktop]" build
Set-Location frontend
npm ci
npm audit
npm run build
Set-Location ..
python -m pytest tests -q
python -m build
```

The build hook requires frontend/dist/index.html and bundles those assets inside
backend/static. Build the UI first. CI checks the installed wheel outside the
checkout and rebuilds a wheel from the source distribution.

Install the wheel into a fresh environment and verify `canvas --help`,
`canvas serve --no-browser`, `/api/health`, `/`, referenced assets and API docs.
Verify desktop startup, explicit connect, Stop TX, cancellation and clean exit.

For Windows EXEs, use Build_Windows_EXE.bat on Windows. Test on a clean Windows
machine without a development Python installation. Review Qt/PySide6 LGPL and
other dependency obligations, include required notices/license texts, and check
any vendor driver redistribution permissions. Do not bundle proprietary drivers
merely because a packaging tool discovers them. Consider signing release EXEs
and publish SHA-256 checksums. These legal/artifact checks remain manual.

## Hardware qualification

Publish actual results per adapter/driver version: classical CAN, FD, BRS,
bitrates, RX, TX echo, cyclic timing under load, disconnect/reconnect and stop.
Virtual-bus tests do not establish physical support or hard-real-time timing.

Publish as an alpha/pre-release until hardware and clean-machine checks pass.

