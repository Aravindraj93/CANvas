"""Never read or change the developer's saved CANvas workspace during tests."""
import os
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix='canvas-tests-')
os.environ['CANVAS_DATA_DIR'] = _test_data.name
