"""Scenario trust, cancellation, local-browser boundaries and result correctness."""
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import can
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from backend.runner.test_runner import run_test_from_yaml, run_test_suite, _run_step
from backend.runner.validation import parse_scenario
from backend.runner.reporter import generate_html_report


@pytest.fixture
def bench(tmp_path):
    from test_programs_choices import engine_dbc
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    workspace.upload([('engine.dbc', engine_dbc())])
    yield workspace
    workspace.sender.stop_all_cyclic(); bus_manager.disconnect()


@pytest.mark.parametrize('content', [
    '[]', 'name: Empty\nsteps: []',
    'name: Bad\nsteps: [{action: waait, ms: 1}]',
    'name: Bad\nsteps: [{action: wait, ms: -1}]',
    'name: Bad\nsteps: [{action: wait, ms: true}]',
    'name: Bad\nsteps: [{action: wait, ms: 0.1}]',
    'name: Bad\nsteps: [{action: wait, ms: 1, typo: 2}]',
    'name: Bad\nsteps: [{action: send_signal, message: A, signal: B, value: .nan}]',
    'name: Bad\nsteps: [{action: assert_visual, baseline: ../secret}]',
    'name: Bad\nsteps: [{action: assert_visual, baseline: ok, threshold: 1.1}]',
    'name: Bad\nsteps: [{action: send_message, message: A, signals: {}}]',
])
def test_invalid_scenarios_rejected(content):
    with pytest.raises(ValueError): parse_scenario(content)


def test_invalid_later_step_sends_nothing(bench):
    bus_manager.connect('virtual', 'preflight')
    yaml = '''name: Reject before side effects
steps:
  - action: send_signal
    message: ENGINE_FD_8
    signal: MAP_4_BAR
    value: 5
  - action: send_signal
    message: ENGINE_FD_8
    signal: CmdIgnSts
    value: UnknownChoice
'''
    with can.Bus(interface='virtual', channel='preflight') as receiver:
        with pytest.raises(ValueError, match='Step 2'):
            asyncio.run(run_test_from_yaml(yaml, sender=bench.sender))
        assert receiver.recv(.05) is None
    assert bench.sender.get_session_signals('default') == []


def test_log_only_is_incomplete_and_visual_infrastructure_error_is_not_skip(bench, monkeypatch):
    result = asyncio.run(run_test_from_yaml('name: Demo\nsteps: [{action: log, message: hello}]', sender=bench.sender))
    assert result['status'] == 'INCOMPLETE' and result['passed'] == 1
    assert not bus_manager.get_status()['connected']
    import backend.hmi.capturer as capturer
    def unavailable(): raise RuntimeError('No display')
    monkeypatch.setattr(capturer, 'capture_screen', unavailable)
    result = asyncio.run(run_test_from_yaml('name: Visual\nsteps: [{action: assert_visual, baseline: sample}]', sender=bench.sender))
    assert result['status'] == 'ERROR' and result['errors'] == 1
    assert result['steps'][0]['status'] == 'ERROR'


def test_cancellation_interrupts_wait_and_prevents_later_send(bench):
    cancel = threading.Event()
    yaml = '''name: Cancel
steps:
  - action: wait
    ms: 10000
  - action: send_signal
    message: ENGINE_FD_8
    signal: MAP_4_BAR
    value: 5
'''
    timer = threading.Timer(.1, cancel.set); timer.start()
    started = time.monotonic()
    try: result = asyncio.run(run_test_from_yaml(yaml, sender=bench.sender, cancel_event=cancel))
    finally: timer.join()
    assert time.monotonic() - started < 2
    assert result['status'] == 'CANCELLED' and result['completed_steps'] == 1
    assert bench.sender.get_session_signals('default') == []


def test_explicit_bus_override_is_not_ignored(bench, tmp_path):
    bus_manager.connect('virtual', 'bus-override')
    path = tmp_path / 'scenario.yaml'
    path.write_text('name: Bus\nbus: pcan\nsteps: [{action: log, message: hello}]')
    with pytest.raises(ValueError, match='Connected bus differs'):
        asyncio.run(run_test_suite(str(path), sender=bench.sender))
    result = asyncio.run(run_test_suite(str(path), bus_type='virtual', sender=bench.sender))
    assert result['status'] == 'INCOMPLETE'


def test_real_rx_assertion_can_pass_a_suite(bench):
    from backend.can.traffic import traffic
    msg = bench.sender._db.get_message_by_name('ENGINE_FD_8')
    bus_manager.connect('virtual', 'assert-pass')
    traffic.on_frame(can.Message(arbitration_id=1040, is_extended_id=False,
                                data=msg.encode({'MAP_4_BAR': 5, 'CmdIgnSts': 4}), is_rx=True))
    result = asyncio.run(run_test_from_yaml('''name: RX
steps:
  - action: assert_signal
    message: ENGINE_FD_8
    signal: CmdIgnSts
    expected: RUN
''', sender=bench.sender))
    assert result['status'] == 'PASS'


def test_pause_latches_and_resume_does_not_restart_cycles(bench):
    bus_manager.connect('virtual', 'pause-sender')
    dbc_id = bench.state()['messages'][0]['dbc_id']
    bench.sender.start_cyclic('ENGINE_FD_8', {'MAP_4_BAR': 5}, 25, dbc_id)
    bench.sender.pause_transmissions()
    with pytest.raises(RuntimeError, match='paused'):
        bench.sender.send_signal('ENGINE_FD_8', 'MAP_4_BAR', 6, dbc_id)
    bench.sender.stop_all_cyclic(); bench.sender.resume_transmissions()
    assert not bench.sender.get_cyclic_messages()
    assert bench.sender.send_signal('ENGINE_FD_8', 'MAP_4_BAR', 6, dbc_id)


def test_report_contains_error_message_and_incomplete_verdict(tmp_path):
    path = tmp_path / 'report.html'
    generate_html_report({'name': '<script>bad</script>', 'status': 'INCOMPLETE', 'reason': 'No assertions',
                          'steps': [{'step_index': 0, 'action': 'log', 'status': 'ERROR',
                                     'description': 'Readable description', 'message': 'Failure details', 'duration_ms': 1}]}, str(path))
    html = path.read_text(encoding='utf-8')
    assert '<script>bad</script>' not in html
    assert 'Failure details' in html and 'No assertions' in html and 'INCOMPLETE' in html


def test_full_app_rejects_foreign_origins_and_hosts():
    from backend.main import app
    with TestClient(app, base_url='http://localhost:8765') as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/health', headers={'Origin': 'http://localhost:8765'}).status_code == 200
        assert client.get('/api/health', headers={'Origin': 'http://localhost:3000'}).status_code == 200
        for origin in ('https://evil.example', 'null', 'http://localhost.evil.example:3000'):
            assert client.get('/api/health', headers={'Origin': origin}).status_code == 403
            assert client.post('/api/dbc/upload', headers={'Origin': origin},
                               files={'file': ('bad.dbc', b'not a dbc')}).status_code == 403
        assert client.get('/api/health', headers={'Host': 'evil.example'}).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('ws://localhost:8765/ws/bus', headers={'Origin': 'https://evil.example'}): pass
        with client.websocket_connect('ws://localhost:8765/ws/bus', headers={'Origin': 'http://localhost:8765'}) as ws:
            assert ws.receive_json()['type'] == 'status'
            ws.send_text('ping'); assert ws.receive_json()['type'] == 'pong'


def test_browser_run_can_be_cancelled_and_overlapping_run_is_rejected(monkeypatch):
    from backend.api import tests as api_tests
    import backend.runner.test_runner as runner
    started = threading.Event()
    original = runner.run_test_from_yaml
    async def marked(*args, **kwargs):
        started.set()
        return await original(*args, **kwargs)
    monkeypatch.setattr(runner, 'run_test_from_yaml', marked)
    app = FastAPI(); app.include_router(api_tests.router, prefix='/tests')
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, '/tests/run', json={'test_yaml': 'name: Slow\nsteps: [{action: wait, ms: 10000}]'})
        assert started.wait(2)
        assert client.post('/tests/run', json={'test_yaml': 'name: Other\nsteps: [{action: log, message: hi}]'}).status_code == 409
        assert client.post('/tests/cancel').json()['cancellation_requested']
        response = future.result(3)
        assert response.status_code == 200 and response.json()['status'] == 'CANCELLED'
        assert not client.post('/tests/cancel').json()['cancellation_requested']


def test_stop_resume_invalidates_inflight_encoding(bench, monkeypatch):
    bus_manager.connect('virtual', 'encoding-stop')
    entered = threading.Event(); release = threading.Event()
    original = SignalSender._encode_physical
    def blocked(msg, values):
        entered.set(); assert release.wait(3)
        return original(msg, values)
    monkeypatch.setattr(SignalSender, '_encode_physical', staticmethod(blocked))
    dbc_id = bench.state()['messages'][0]['dbc_id']
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(bench.sender.send_signal, 'ENGINE_FD_8', 'MAP_4_BAR', 5, dbc_id)
        assert entered.wait(1)
        bench.sender.pause_transmissions(); bench.sender.resume_transmissions(); release.set()
        assert not future.result(3)
    assert bus_manager.get_status()['tx_count'] == 0


def test_disconnected_request_keeps_run_ownership_until_worker_finishes(monkeypatch):
    from backend.api import tests as api_tests
    import backend.runner.test_runner as runner
    from fastapi import HTTPException
    entered = threading.Event(); release = threading.Event()
    async def blocked(*args, **kwargs):
        entered.set(); release.wait(3)
        return {'status': 'CANCELLED'}
    monkeypatch.setattr(runner, 'run_test_from_yaml', blocked)
    async def exercise():
        request = api_tests.RunTestRequest(test_yaml='unused')
        task = asyncio.create_task(api_tests.run_test(request))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert api_tests._active_cancel is not None
            with pytest.raises(HTTPException) as error: await api_tests.run_test(request)
            assert error.value.status_code == 409
        finally:
            release.set()
        for _ in range(100):
            if api_tests._active_cancel is None: break
            await asyncio.sleep(.01)
        assert api_tests._active_cancel is None
    asyncio.run(exercise())


def test_failed_initial_websocket_send_releases_capacity():
    from backend.api import ws as ws_api
    class BrokenSocket:
        async def accept(self): pass
        async def send_text(self, payload): raise RuntimeError('Client disconnected')
    async def exercise():
        socket = BrokenSocket()
        await ws_api.ws_bus(socket)
        assert socket not in ws_api._connections and socket not in ws_api._admitted
    asyncio.run(exercise())


def test_invalid_multiplexor_is_rejected_before_first_send(bench):
    content = b'''VERSION ""
NS_ :
BS_:
BU_: Bench
BO_ 1050 MuxMessage: 3 Bench
 SG_ Selector M : 0|8@1+ (1,0) [0|2] "" Bench
 SG_ BranchA m0 : 8|8@1+ (1,0) [0|255] "" Bench
 SG_ BranchB m1 : 8|8@1+ (1,0) [0|255] "" Bench
'''
    bench.upload([('mux.dbc', content)])
    bus_manager.connect('virtual', 'mux-preflight')
    yaml = '''name: Invalid branch
steps:
  - action: send_signal
    message: ENGINE_FD_8
    signal: MAP_4_BAR
    value: 5
  - action: send_signal
    message: MuxMessage
    signal: Selector
    value: 2
'''
    with pytest.raises(ValueError, match='Step 2'):
        asyncio.run(run_test_from_yaml(yaml, sender=bench.sender))
    assert bus_manager.get_status()['tx_count'] == 0


