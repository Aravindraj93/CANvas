"""Run with the installed wheel's Python, outside the source checkout."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

import backend
from fastapi.testclient import TestClient
from backend.main import app

package = Path(backend.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve()), f'Not an installed package: {package}'
static = package / 'static'
assert (static / 'index.html').is_file(), 'Packaged browser UI missing'
with TestClient(app, base_url='http://localhost') as client:
    assert client.get('/api/health').status_code == 200
    assert client.get('/').status_code == 200
    assets = list((static / 'assets').iterdir())
    assert assets and all(client.get('/assets/' + asset.name).status_code == 200 for asset in assets)
subprocess.run([sys.executable, '-m', 'backend.main', '--help'], check=True, capture_output=True)
if '--desktop' in sys.argv:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from backend.can.signal_sender import SignalSender
    from backend.dbc_workspace import DbcWorkspace
    from backend.storage import WorkspaceStore
    from backend.desktop.app import CanvasWindow
    app_qt = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        workspace = DbcWorkspace(WorkspaceStore(Path(directory)), SignalSender())
        window = CanvasWindow(workspace); window.show(); app_qt.processEvents()
        assert window.tabs.count() >= 4
        window.close(); app_qt.processEvents()
print('Installed package smoke checks passed:', package)

