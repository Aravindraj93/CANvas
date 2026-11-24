"""Desktop entry point with a readable startup error on Windows."""
import sys
import traceback
from pathlib import Path


def main():
    try:
        from backend.desktop.app import main as run
        return run()
    except Exception:
        message = traceback.format_exc()
        directory = Path.home() / '.canvas'
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / 'desktop-startup.log'
        log.write_text(message, encoding='utf-8')
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'CANvas could not start.\n\nDetails: {log}\n\nRun Setup_CANvas.bat if desktop dependencies are missing.', 'CANvas startup error', 0x10)
        else:
            print(message, file=sys.stderr)
        return 1
