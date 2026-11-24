"""
backend/main.py — CANvas FastAPI application entry point + Click CLI.
"""

from __future__ import annotations

import os
import threading
import webbrowser

import click
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.api.dbc import router as dbc_router
from backend.api.signals import router as signals_router
from backend.api.tests import router as tests_router
from backend.api.ws import router as ws_router
from backend.security import LocalBrowserMiddleware, DEV_ORIGINS, LOCAL_HOSTS

# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="CANvas",
    description="Open-source CAN/CAN FD bench signal and HMI testing tools",
    version="0.4.6",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(DEV_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LocalBrowserMiddleware)

app.include_router(signals_router, prefix="/api/signals", tags=["signals"])
app.include_router(dbc_router, prefix="/api/dbc", tags=["dbc"])
app.include_router(tests_router, prefix="/api/tests", tags=["tests"])
app.include_router(ws_router, prefix="/ws", tags=["websocket"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.4.6", "tool": "CANvas"}


# Serve built frontend if it exists
_frontend_dist = os.path.join(os.path.dirname(__file__), 'static')
if not os.path.isdir(_frontend_dist):
    _frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def root():
        return """
        <html><body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;padding:48px;text-align:center">
        <h1 style="color:#00ff88;font-size:48px">CAN<span style="color:white">vas</span></h1>
        <p style="font-size:18px;color:#8b949e">Backend is running! 🚗</p>
        <p style="margin-top:16px"><a href="/docs" style="color:#00ff88">API Docs →</a></p>
        <p style="margin-top:32px;color:#8b949e;font-size:14px">
          To start the full UI, run:<br>
          <code style="background:#161b22;padding:8px 16px;border-radius:4px;display:inline-block;margin-top:8px">
            cd frontend && npm install && npm run dev
          </code>
        </p>
        </body></html>
        """


# ── CLI ──────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """CANvas — Free, open-source automotive HMI test platform."""
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind")
@click.option("--port", default=8765, show_default=True, help="Port")
@click.option("--bus", default="virtual", show_default=True,
              help="CAN bus type: virtual, neovi (ValueCAN), socketcan, pcan, kvaser")
@click.option("--channel", default=None, help="CAN channel (e.g. PCAN_USBBUS1, /dev/can0)")
@click.option("--bitrate", default=500_000, show_default=True, help="CAN bus bitrate")
@click.option("--fd", is_flag=True, help="Enable CAN FD on the adapter")
@click.option("--data-bitrate", type=click.IntRange(min=1), default=None, help="CAN FD data bitrate")
@click.option("--bitrate-switch", is_flag=True, help="Enable BRS on transmitted CAN FD frames")
@click.option("--serial", default=None, help="Intrepid device serial (optional)")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def serve(host, port, bus, channel, bitrate, fd, data_bitrate, bitrate_switch, serial, no_browser):
    """Start the CANvas server and open the browser UI."""
    if host not in LOCAL_HOSTS:
        raise click.UsageError('Remote serving is not supported. Use 127.0.0.1, localhost or ::1.')
    from rich.console import Console
    console = Console()

    console.print(r"""
[bold green]
  ____    _    _   _               
 / ___|  / \  | \ | |__   ____ _ ___
| |     / _ \ |  \| \ \ / / _` / __|
| |___ / ___ \| |\  |\ V / (_| \__ \\
 \____/_/   \_\_| \_| \_/ \__,_|___/
[/bold green]
[dim]Open-source CAN/CAN FD bench signal testing[/dim]
""")

    console.print(f"  🌐  UI:      [link=http://{host}:{port}]http://{host}:{port}[/link]")
    console.print(f"  📡  Bus:     [cyan]{bus}[/cyan]{f' ({channel})' if channel else ''} @ {bitrate} bps")
    console.print(f"  📖  API:     [link=http://{host}:{port}/docs]http://{host}:{port}/docs[/link]")
    console.print()

    # Auto-connect to bus
    os.environ["CANVAS_BUS_TYPE"] = bus
    if channel:
        os.environ["CANVAS_BUS_CHANNEL"] = channel

    from backend.can.bus_manager import bus_manager
    status = bus_manager.connect(
        bus_type=bus, channel=channel, bitrate=bitrate, fd=fd,
        data_bitrate=data_bitrate, bitrate_switch=bitrate_switch, serial=serial,
    )
    if status.connected:
        console.print(f"  ✅  Bus connected: [green]{bus}[/green]")
        if bus == "virtual":
            console.print("  [yellow]Simulation only: no frames are sent to the physical bench.[/yellow]")
    else:
        console.print(f"  ⚠️  Bus not connected: [yellow]{status.error}[/yellow]")
        console.print("     You can connect from the UI later.")
    console.print()

    if not no_browser:
        def _open():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.argument("config", type=click.Path(exists=True))
@click.option("--bus", default=None, help="Override the YAML bus; otherwise use the current bus or virtual")
@click.option("--report", default="canvas-report.html", show_default=True, help="Report output path")
def test(config, bus, report):
    """Run a YAML test suite and generate an HTML report."""
    import asyncio
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    console = Console()

    console.print(f"\n[bold]CANvas[/bold] — Running: [cyan]{config}[/cyan]\n")

    async def _run():
        from backend.runner.test_runner import run_test_suite
        return await run_test_suite(config, bus_type=bus)

    try:
        results = asyncio.run(_run())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        from backend.can.signal_sender import signal_sender
        from backend.can.bus_manager import bus_manager
        signal_sender.stop_all_cyclic()
        bus_manager.disconnect()

    # Print step results
    for step in results["steps"]:
        icon = "✅" if step["status"] == "PASS" else ("⚠️" if step["status"] == "SKIP" else "❌")
        console.print(f"  {icon} Step {step['step_index']+1}: [dim]{step['action']}[/dim] — {step['message']}")

    # Summary
    passed = results["passed"]
    total = results["total_steps"]
    color = "green" if passed == total else "red"
    console.print(f"\n  [bold {color}]{passed}/{total} steps passed[/bold {color}] in {results['duration_ms']}ms")
    console.print(f"  Verdict: {results['status']} {results.get('reason', '')}")

    # Generate report
    from backend.runner.reporter import generate_html_report
    generate_html_report(results, output_path=report)
    console.print(f"  📋 Report saved: [cyan]{report}[/cyan]\n")

    raise SystemExit(0 if results["status"] == "PASS" else 1)


if __name__ == "__main__":
    cli()
