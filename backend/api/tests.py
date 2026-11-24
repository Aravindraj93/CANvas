"""
backend/api/tests.py — FastAPI router for test execution and AI generation.
"""

from __future__ import annotations

import asyncio
import uuid
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# In-memory test result store (replace with SQLite for persistence later)
_results: dict[str, dict] = {}
_active_cancel: threading.Event | None = None


class RunTestRequest(BaseModel):
    test_yaml: str = Field(max_length=1_000_000)


class GenerateTestRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)


@router.post("/run")
async def run_test(req: RunTestRequest):
    """Execute a YAML test scenario and return results."""
    from backend.runner.test_runner import run_test_from_yaml
    global _active_cancel
    if _active_cancel is not None:
        raise HTTPException(status_code=409, detail='A test is already running. Cancel it or wait for completion.')
    cancel = threading.Event()
    _active_cancel = cancel
    worker = asyncio.create_task(asyncio.to_thread(
        lambda: asyncio.run(run_test_from_yaml(req.test_yaml, cancel_event=cancel))))
    def release(completed):
        global _active_cancel
        if _active_cancel is cancel: _active_cancel = None
        # Retrieve exceptions even when the requesting client disconnected.
        if not completed.cancelled(): completed.exception()
    worker.add_done_callback(release)
    try:
        results = await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Test execution error: {exc}")
    finally:
        cancel.set()

    # Store result
    result_id = str(uuid.uuid4())[:8]
    _results[result_id] = results
    results["id"] = result_id
    while len(_results) > 100:
        del _results[next(iter(_results))]
    return results


@router.post('/cancel')
async def cancel_test():
    if _active_cancel is not None: _active_cancel.set()
    return {'cancellation_requested': _active_cancel is not None,
            'detail': 'An adapter call already in progress may finish.'}


@router.get("/results")
async def list_results():
    """List all past test results."""
    return {
        "results": [
            {"id": k, "name": v.get("name"), "status": v.get("status"), "timestamp": v.get("timestamp")}
            for k, v in _results.items()
        ]
    }


@router.get("/results/{result_id}")
async def get_result(result_id: str):
    """Get a specific test result."""
    if result_id not in _results:
        raise HTTPException(status_code=404, detail="Result not found")
    return _results[result_id]


@router.post("/generate")
async def generate_test(req: GenerateTestRequest):
    """Generate a YAML test scenario from natural language using AI."""
    from backend.ai.test_generator import generate_test_yaml

    dbc_context = ""
    from backend.can.signal_sender import signal_sender
    if signal_sender._db:
        msgs = signal_sender.get_all_messages().get("messages", [])
        lines = []
        for m in msgs:
            sigs = ", ".join(
                f"{s['name']} ({s['min_value']}–{s['max_value']} {s['unit']})"
                for s in m["signals"]
            )
            lines.append(f"  Message: {m['name']} (ID {m['arbitration_id_hex']}) → Signals: {sigs}")
        dbc_context = "\n".join(lines)

    try:
        yaml_str = await generate_test_yaml(req.prompt, dbc_context)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"yaml": yaml_str}
