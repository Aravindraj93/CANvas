"""
backend/runner/test_runner.py
Orchestrates test execution: parse YAML → send signals → wait → assert → report.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from backend.runner.validation import parse_scenario, validate_scenario, validate_definitions


async def run_test_from_yaml(yaml_str: str, *, sender=None, cancel_event=None, bus_type=None) -> dict:
    """Parse and execute a YAML test scenario."""
    return await _execute(parse_scenario(yaml_str), sender=sender, cancel_event=cancel_event, bus_type=bus_type)


async def run_test_suite(config_path: str, bus_type=None, *, sender=None, cancel_event=None) -> dict:
    """Load a YAML file and run the test suite."""
    with open(config_path, encoding="utf-8") as f:
        content = f.read(1_000_001)
    return await run_test_from_yaml(content, sender=sender, cancel_event=cancel_event, bus_type=bus_type)


async def _execute(config: dict, *, sender=None, cancel_event=None, bus_type=None) -> dict:
    from backend.can.signal_sender import signal_sender
    from backend.can.bus_manager import bus_manager

    signal_sender = sender if sender is not None else signal_sender
    validate_scenario(config)
    validate_definitions(config, signal_sender)
    name = config['name']
    steps: list[dict] = config.get("steps", [])
    requested_bus = bus_type or config.get('bus')

    # Auto-connect if not already connected
    status = bus_manager.get_status()
    if requested_bus and status['connected'] and status['bus_type'] != requested_bus:
        raise ValueError('Connected bus differs from the requested test bus. Disconnect or select the correct bus explicitly.')
    needs_bus = any(s['action'] in ('send_signal', 'send_message', 'assert_signal') for s in steps)
    if needs_bus and not status['connected'] and not (cancel_event and cancel_event.is_set()):
        status = bus_manager.connect(bus_type=requested_bus or 'virtual')
        if not status.connected: raise ValueError(status.error or 'Cannot connect to test bus')

    step_results: list[dict] = []
    overall_start = time.monotonic()

    for i, step in enumerate(steps):
        step_start = time.monotonic()
        if cancel_event and cancel_event.is_set():
            result = dict(step_index=i, action=step['action'], description=step.get('description', ''),
                          status='CANCELLED', message='Test cancelled before this step')
        else:
            result = await _run_step(i, step, signal_sender, cancel_event)
        result["duration_ms"] = round((time.monotonic() - step_start) * 1000, 2)
        step_results.append(result)
        if result['status'] == 'CANCELLED': break

    total_ms = round((time.monotonic() - overall_start) * 1000, 2)
    passed = sum(1 for r in step_results if r["status"] == "PASS")
    failed = sum(1 for r in step_results if r["status"] == "FAIL")
    errors = sum(r['status'] == 'ERROR' for r in step_results)
    skipped = sum(r['status'] == 'SKIP' for r in step_results)
    cancelled = bool(cancel_event and cancel_event.is_set()) or any(r['status'] == 'CANCELLED' for r in step_results)
    verified = any(r['action'] in ('assert_signal', 'assert_visual') and r['status'] == 'PASS' for r in step_results)
    verdict = ('CANCELLED' if cancelled else 'ERROR' if errors else 'FAIL' if failed
               else 'INCOMPLETE' if skipped or not verified else 'PASS')

    return {
        "name": name,
        "status": verdict,
        "errors": errors,
        "skipped": skipped,
        "completed_steps": len(step_results),
        "reason": 'No successful verification assertion was performed.' if verdict == 'INCOMPLETE' and not verified else '',
        "total_steps": len(steps),
        "passed": passed,
        "failed": failed,
        "duration_ms": total_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": step_results,
    }


async def _run_step(index: int, step: dict, signal_sender: Any, cancel_event=None) -> dict:
    action = step.get("action", "unknown")
    description = step.get("description", "")

    base = {"step_index": index, "action": action, "description": description, "status": "PASS", "message": ""}

    try:
        if cancel_event and cancel_event.is_set():
            return {**base, 'status': 'CANCELLED', 'message': 'Test cancelled'}
        if action == "send_signal":
            msg_name = step["message"]
            sig_name = step["signal"]
            value = step["value"] if isinstance(step["value"], str) else float(step["value"])
            if not signal_sender.send_signal(msg_name, sig_name, value, step.get('dbc_id')):
                from backend.can.bus_manager import bus_manager
                raise RuntimeError(bus_manager.get_status().get("last_tx_error") or "CAN send failed")
            base["message"] = f"Sent {msg_name}.{sig_name} = {value}"

        elif action == "send_message":
            msg_name = step["message"]
            signals = step.get("signals", {})
            if not signal_sender.send_message_signals(msg_name, signals, step.get('dbc_id')):
                from backend.can.bus_manager import bus_manager
                raise RuntimeError(bus_manager.get_status().get("last_tx_error") or "CAN send failed")
            base["message"] = f"Sent {msg_name} with {len(signals)} signals"

        elif action == "wait":
            ms = int(step.get("ms", 100))
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                if cancel_event and cancel_event.is_set():
                    return {**base, 'status': 'CANCELLED', 'message': 'Test cancelled during wait'}
                await asyncio.sleep(min(.05, max(0.0, deadline - time.monotonic())))
            base["message"] = f"Waited {ms}ms"

        elif action == "assert_signal":
            from backend.can.traffic import traffic
            from backend.can.bus_manager import bus_manager
            _, msg = signal_sender.resolve_message(step['message'], step.get('dbc_id'))
            from backend.can.signal_sender import _signal_value
            expected = {step['signal']: _signal_value(msg.get_signal_by_name(step['signal']), step['expected'])}
            verification = traffic.verify(
                msg, expected, bus_manager.get_status()['connected'],
                int(step.get('max_age_ms', 1000)), step.get('tolerance'),
            )
            base['status'] = verification['status']
            base['message'] = verification['reason']
            base['verification'] = verification

        elif action == "log":
            base["message"] = step.get("message", "")

        elif action == "assert_visual":
            # Visual assertion — requires HMI capturer
            try:
                from backend.hmi.capturer import capture_screen
                from backend.hmi.verifier import compare_images_by_name
                baseline = step.get("baseline", "")
                threshold = float(step.get("threshold", 0.95))
                img = capture_screen()
                result_cmp = compare_images_by_name(img, baseline, threshold)
                if result_cmp.get('error'):
                    raise RuntimeError(result_cmp['error'])
                if result_cmp["match"]:
                    base["message"] = f"Visual assertion passed (score={result_cmp['score']:.3f})"
                else:
                    base["status"] = "FAIL"
                    base["message"] = f"Visual assertion FAILED (score={result_cmp['score']:.3f}, threshold={threshold})"
            except Exception as exc:
                base["status"] = "ERROR"
                base["message"] = f"Visual verification unavailable: {exc}"

        else:
            base["status"] = "ERROR"
            base["message"] = f"Unknown action: {action}"

    except KeyError as exc:
        base["status"] = "FAIL"
        base["message"] = f"Missing required field: {exc}"
    except Exception as exc:
        base["status"] = "FAIL"
        base["message"] = f"Error: {exc}"

    return base
