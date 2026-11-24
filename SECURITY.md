# Security, privacy and bench use

## Supported scope

CANvas is alpha bench-testing software, not a safety-certified control system.
Use only on authorized, isolated development benches. A software stop is not a
physical emergency stop. An adapter call already in progress may complete.

The web launcher supports loopback addresses only. HTTP and WebSocket requests
reject untrusted Host/Origin headers, including cross-origin multipart uploads.
Originless local scripts are allowed. This is browser-origin protection, **not
authentication**. Do not expose the server through a proxy, tunnel or a custom
Uvicorn bind to an untrusted network. Other local software can access the API.
The Vite development origin on localhost/127.0.0.1 port 3000 is trusted.

## Data handling

- Saved programs and DBC bytes are stored locally under `~/.canvas` by default.
  Back up this directory while the application is closed; deleting it removes
  local saved workspaces. Check custom storage settings before deleting data.
- Session history is in memory. Diagnostics contain filenames, program names,
  adapter details, signal values and encoded payloads. Review and redact exports
  manually before sharing. There is not yet automatic diagnostic redaction.
- Visual verification captures screen contents. Use a dedicated test desktop;
  screenshots may contain confidential information.
- With a Gemini API key configured, AI generation sends the prompt and DBC-derived
  metadata to Google's service. Do not submit confidential DBC data without
  authorization. Without a key, generation uses local templates. The current UI
  does not provide a separate consent dialog; treat the Generate action as an
  external disclosure when a key is configured.
- Never commit keys, private DBCs, real vehicle traces or local evidence. A
  .gitignore does not remove previously committed files or sanitize history.

## Reporting a vulnerability

Before publishing the repository, maintainers must enable GitHub private
vulnerability reporting. Then use the repository's **Security → Report a
vulnerability** page. Do not post secrets, private data or weaponized examples
in public issues. Only the latest maintained release receives security fixes.

