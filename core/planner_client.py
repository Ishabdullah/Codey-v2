#!/usr/bin/env python3
"""
planner_client — async planning interface for Codey-v2

Sends a raw user task to the Qwen 7B model on port 8080 for high-level
planning, then returns the numbered step list.  Designed to be awaited
directly from the main daemon's async event loop.

Failure contract:
  - If the 7B server is unreachable or returns no steps → returns None
  - Any other error → returns None so caller falls back to direct execution

The caller (core/daemon.py) wraps this in asyncio.wait_for(timeout=180) and
falls back to state.add_task(prompt) on any exception or None return.
"""

import asyncio
from typing import Optional, List


async def send_plan_request_async(task: str) -> Optional[List[str]]:
    """
    Ask the 7B model to plan *task* and return the list of step strings.

    Delegates to core.plannd.get_plan_from_7b (blocking HTTP call) via
    run_in_executor so the daemon event loop is not stalled.

    Returns None if planning fails or produces fewer than 1 step, so the
    caller falls through to the direct-execution path unchanged.
    """
    from core.plannd import get_plan_from_7b

    loop = asyncio.get_running_loop()
    steps = await loop.run_in_executor(None, get_plan_from_7b, task)
    if steps and isinstance(steps, list) and len(steps) > 0:
        return [str(s) for s in steps]
    return None
