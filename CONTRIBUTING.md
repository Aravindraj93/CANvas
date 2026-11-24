# Contributing to CANvas

Use Python 3.10+ and Node.js 22 LTS. On Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,desktop]"
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m pytest tests -q
```

Tests use virtual CAN and offscreen Qt, not physical hardware. Desktop tests
require the desktop extra; skipping them is not desktop qualification. For a
manual UI check, run `python desktop_entry.py` outside offscreen mode.

## Pull requests

- Describe the problem, user-visible behavior and validation performed.
- Include regression tests; preserve RX vs TX-echo evidence distinctions.
- Keep hardware calls off the GUI thread. Do not automatically replay saved TX.
- Include sanitized reproductions only. Never upload customer DBCs, real traces,
  secrets, adapter serials or screenshots without authorization.
- Record significant user-facing changes in CHANGELOG.md.
- State adapter, driver, network, bitrate and CAN FD/BRS settings when reporting
  hardware issues. Distinguish virtual results from physical bench results.

Report security concerns using SECURITY.md rather than a public exploit report.
See RELEASE_CHECKLIST.md for packaging and release verification.

