#!/usr/bin/env python3
"""
planner_client — async client for plannd

Sends a raw user task to plannd over its Unix socket and returns the list
of numbered step strings.  Designed to be awaited directly from the main
daemon's async event loop.

Failure contract:
  - If plannd's socket does not exist      → raises ConnectionRefusedError immediately
  - If plannd takes longer than timeout    → caller should use asyncio.wait_for
  - Any other error (bad JSON, EOF, etc.)  → returns None so caller can fall back

The caller (core/daemon.py) wraps this in asyncio.wait_for(timeout=45) and
falls back to state.add_task(prompt) on any exception or None return.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, List


async def send_plan_request_async(task: str) -> Optional[List[str]]:
    """
    Send *task* to plannd and return the list of step strings.

    Returns None if plannd is running but the inference produced no usable steps.
    Raises ConnectionRefusedError if plannd's socket is not present (not started).
    Any other exception propagates to the caller.

    Protocol:
      Client writes JSON {"task": "..."} then drains.
      Server reads, runs DeepSeek, writes JSON {"steps": [...]} or {"error": "..."},
      then closes the connection.
      Client reads until EOF, parses response.
    """
    from utils.config import PLANND_SOCKET_PATH

    sock_path = str(PLANND_SOCKET_PATH)

    if not Path(sock_path).exists():
        raise ConnectionRefusedError(f"plannd socket not found: {sock_path}")

    reader, writer = await asyncio.open_unix_connection(sock_path)
    try:
        # Send request
        payload = json.dumps({"task": task}).encode("utf-8")
        writer.write(payload)
        await writer.drain()
        # Close write side so the server's reader.read() returns promptly
        writer.write_eof()
        await writer.drain()

        # Read response until server closes the connection
        chunks: List[bytes] = []
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            chunks.append(chunk)

        raw = b"".join(chunks)
        if not raw:
            return None

        result = json.loads(raw.decode("utf-8"))

        if result.get("error"):
            # plannd ran but reported an internal error — caller falls back
            return None

        steps = result.get("steps")
        if steps and isinstance(steps, list) and len(steps) > 0:
            return [str(s) for s in steps]

        return None

    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
