#!/usr/bin/env python3
"""
Daemon core for Codey-v2.

Main daemon process with:
- Unix socket server for CLI communication
- Signal handlers (SIGTERM for graceful shutdown, SIGUSR1 for reload)
- PID file management for single-instance enforcement
- Main event loop for background tasks

The daemon runs continuously in the background, accepting commands
from the CLI client via a Unix domain socket.
"""

import os
import sys
import json
import socket
import signal
import asyncio
import time
from pathlib import Path
from typing import Optional, Callable, Dict, Any

from utils.config import CODEY_DIR
from utils.logger import info, warning, error, success, set_log_level, setup_file_logging
from core.state import get_state_store, StateStore
from core.daemon_config import get_config, DaemonConfig
from core.task_executor import TaskExecutor

# ==================== Configuration ====================

# Daemon directory — defined at module level so check_pid_file / is_daemon_running
# can use it without triggering a full Daemon init.
DAEMON_DIR = Path.home() / ".codey-v2"

# Stable path constants with hardcoded defaults.
# These may be overridden when Daemon.__init__ reads the config file.
PID_FILE    = DAEMON_DIR / "codey-v2.pid"
SOCKET_FILE = DAEMON_DIR / "codey-v2.sock"
LOG_FILE    = DAEMON_DIR / "codey-v2.log"


# ==================== PID File Management ====================

def check_pid_file() -> bool:
    """
    Check if daemon is already running.
    
    Returns True if another daemon is running.
    Removes stale PID file if process is dead.
    """
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Signal 0 checks if process exists
            return True  # Daemon is running
        except PermissionError:
            return True  # Process exists but owned by another user — treat as running
        except (ProcessLookupError, ValueError):
            # Process is dead or PID file is corrupt — remove stale file
            warning("Removing stale PID file")
            PID_FILE.unlink(missing_ok=True)
            return False
    return False


def write_pid_file():
    """Write current PID to PID file."""
    PID_FILE.write_text(str(os.getpid()))


def remove_pid_file():
    """Remove PID file on shutdown."""
    PID_FILE.unlink(missing_ok=True)


# ==================== Unix Socket Server ====================

class DaemonServer:
    """
    Unix socket server for CLI communication.
    
    Handles incoming commands from CLI clients and routes them
    to appropriate handlers.
    """
    
    def __init__(self, state: StateStore, shutdown_callback=None):
        self.state = state
        self.server: Optional[asyncio.Server] = None
        self.running = False
        self._handlers: Dict[str, Callable] = {}
        self._shutdown_callback = shutdown_callback
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default command handlers."""
        self.register_handler("ping", self._handle_ping)
        self.register_handler("command", self._handle_command)
        self.register_handler("status", self._handle_status)
        self.register_handler("health", self._handle_health)
        self.register_handler("task", self._handle_task)
        self.register_handler("cancel", self._handle_cancel)
        self.register_handler("shutdown", self._handle_shutdown)
    
    def register_handler(self, cmd: str, handler: Callable):
        """Register a command handler."""
        self._handlers[cmd] = handler
    
    async def _handle_ping(self, data: Dict) -> Dict:
        """Handle ping command."""
        return {"status": "ok", "message": "pong"}
    
    async def _handle_command(self, data: Dict) -> Dict:
        """Handle a user command (prompt).

        If plannd is available and no_plan is not set, the raw prompt is sent to
        plannd (DeepSeek 1.5B) which returns a numbered step list.  Each step is
        added as a dependent task via Planner.add_tasks() so the 7B model works
        through them one at a time.

        If plannd is unavailable, times out (>45 s), or returns fewer than 2 steps,
        the prompt is queued as a single direct task — identical to prior behaviour.
        Plannd failure is always silent (logged only) and never surfaces as an error.
        """
        prompt = data.get("prompt", "")
        if not prompt:
            return {"status": "error", "message": "No prompt provided"}

        # Log to episodic log
        self.state.log_action("command_received", prompt[:200])

        # ── plannd integration (Change 1) ────────────────────────────────────
        no_plan = data.get("no_plan", False)
        if not no_plan:
            try:
                from core.planner_client import send_plan_request_async
                steps = await asyncio.wait_for(
                    send_plan_request_async(prompt),
                    timeout=180.0,
                )
                if steps and len(steps) > 1:
                    if data.get("plan_only", False):
                        task_ids = []
                        info(f"plannd: returned {len(steps)}-step plan (plan_only)")
                    else:
                        # Inject original prompt into step 1 (the create step)
                        # so the executor has full requirements context.
                        # Later steps (run/verify) are usually self-contained
                        # and don't need the full prompt — just the step.
                        total = len(steps)
                        enriched = []
                        for i, step in enumerate(steps):
                            if i == 0:
                                # Step 1: full context — the executor needs
                                # all requirements to write the code
                                enriched.append(
                                    f"User's full request: {prompt}\n\n"
                                    f"Your task (step {i+1}/{total}): {step}\n\n"
                                    "Write the COMPLETE file with ALL features "
                                    "described above. Do not skip any requirement."
                                )
                            else:
                                enriched.append(
                                    f"Previous context: {prompt[:200]}\n\n"
                                    f"Your task (step {i+1}/{total}): {step}\n\n"
                                    "Complete only this step."
                                )
                        task_ids = self.planner.add_tasks(enriched)
                        info(f"plannd: queued {len(steps)}-step plan")
                    return {
                        "status": "ok",
                        "message": f"Plan created: {len(steps)} steps",
                        "task_ids": task_ids,
                        "plan": steps,
                    }
                # plannd returned ≤1 step — fall through to single-task path
                if steps:
                    info("plannd returned only 1 step — using single-task path")
            except asyncio.TimeoutError:
                warning("plannd request timed out after 45 s — falling back to direct task")
            except ConnectionRefusedError:
                # plannd not running — silent fallback
                pass
            except Exception as _e:
                warning(f"plannd unavailable ({_e}) — falling back to direct task")

        # ── Fallback: single direct task (existing behaviour) ────────────────
        task_id = self.state.add_task(prompt)
        return {
            "status": "ok",
            "message": f"Task queued with ID {task_id}",
            "task_id": task_id,
        }
    
    async def _handle_status(self, data: Dict) -> Dict:
        """Handle status query."""
        pending = len(self.state.get_tasks_by_status("pending"))
        running = len(self.state.get_tasks_by_status("running"))
        done = len(self.state.get_tasks_by_status("done"))

        return {
            "status": "ok",
            "daemon": "running",
            "pid": os.getpid(),
            "tasks": {
                "pending": pending,
                "running": running,
                "done": done
            },
            "state": self.state.get_all()
        }

    async def _handle_health(self, data: Dict) -> Dict:
        """Handle health check query."""
        import resource
        
        # Get process memory usage
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = usage.ru_maxrss / 1024  # Convert to MB (on Linux)
        except:
            memory_mb = 0
        
        # Get task stats
        all_tasks = self.state.get_all_tasks()
        pending_count = len([t for t in all_tasks if t["status"] == "pending"])
        stuck_tasks = []
        now = int(time.time())
        for t in all_tasks:
            if t["status"] == "running" and t.get("started_at"):
                running_time = now - t["started_at"]
                if running_time > 1800:  # 30 minutes
                    stuck_tasks.append(t["id"])
        
        # Get recent actions count
        recent_actions = len(self.state.get_recent_actions(100))
        
        # Get uptime
        started_at = self.state.get("daemon_started_at", 0)
        uptime_seconds = int(time.time()) - int(started_at) if started_at else 0
        
        return {
            "status": "ok",
            "healthy": True,
            "pid": os.getpid(),
            "uptime_seconds": uptime_seconds,
            "memory_mb": round(memory_mb, 1),
            "tasks": {
                "pending": pending_count,
                "stuck": stuck_tasks
            },
            "recent_actions": recent_actions
        }

    async def _handle_task(self, data: Dict) -> Dict:
        """Handle task query (get task by ID or list all)."""
        task_id = data.get("id")
        
        if task_id is not None:
            # Get specific task
            task = self.state.get_task(task_id)
            if not task:
                return {"status": "error", "message": f"Task {task_id} not found"}
            return {"status": "ok", "task": task}
        else:
            # List all tasks
            limit = data.get("limit", 20)
            tasks = self.state.get_all_tasks()[:limit]
            return {"status": "ok", "tasks": tasks}

    async def _handle_cancel(self, data: Dict) -> Dict:
        """Handle task cancellation."""
        task_id = data.get("id")
        if not task_id:
            return {"status": "error", "message": "Task ID required"}
        
        cancelled = self.state.cancel_task(task_id)
        if cancelled:
            self.state.log_action("task_cancelled", f"Task {task_id}")
            return {"status": "ok", "message": f"Task {task_id} cancelled"}
        else:
            task = self.state.get_task(task_id)
            if task:
                return {"status": "error", "message": f"Task {task_id} already {task['status']}"}
            return {"status": "error", "message": f"Task {task_id} not found"}

    async def _handle_shutdown(self, data: Dict) -> Dict:
        """Handle shutdown request — triggers the daemon's main loop to exit."""
        info("Shutdown requested via socket")
        if self._shutdown_callback:
            self._shutdown_callback()
        return {"status": "ok", "message": "Shutting down"}
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle incoming client connection."""
        try:
            # Read request (JSON message)
            data = await reader.read(65536)
            if not data:
                return
            
            request = json.loads(data.decode('utf-8'))
            cmd = request.get("cmd", "unknown")
            
            info(f"Received command: {cmd}")
            
            # Route to handler
            handler = self._handlers.get(cmd)
            if handler:
                response = await handler(request.get("data", {}))
            else:
                response = {"status": "error", "message": f"Unknown command: {cmd}"}
            
            # Send response
            writer.write(json.dumps(response).encode('utf-8'))
            await writer.drain()
            
        except json.JSONDecodeError as e:
            error(f"Invalid JSON from client: {e}")
            writer.write(json.dumps({"status": "error", "message": "Invalid JSON"}).encode('utf-8'))
            await writer.drain()
        except Exception as e:
            error(f"Error handling client: {e}")
            try:
                writer.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
                await writer.drain()
            except:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
    
    async def start(self):
        """Start the socket server."""
        # Remove old socket file if exists
        SOCKET_FILE.unlink(missing_ok=True)
        
        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(SOCKET_FILE)
        )
        
        # Set socket permissions (user only)
        os.chmod(SOCKET_FILE, 0o600)
        
        self.running = True
        info(f"Daemon listening on {SOCKET_FILE}")
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self):
        """Stop the socket server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        SOCKET_FILE.unlink(missing_ok=True)
        info("Daemon socket stopped")


# ==================== Daemon Core ====================

class Daemon:
    """
    Main daemon class.

    Manages the event loop, signal handlers, and socket server.
    """

    def __init__(self):
        global PID_FILE, SOCKET_FILE, LOG_FILE

        # Load config and apply logging — done here, not at module level,
        # so importing core.daemon for CLI helpers doesn't trigger side effects.
        self._config = get_config()
        DAEMON_DIR.mkdir(parents=True, exist_ok=True)

        log_level = self._config.get("daemon", "log_level", default="INFO")
        set_log_level(log_level)

        log_file_path = self._config.get("daemon", "log_file", default=str(LOG_FILE))
        setup_file_logging(log_file_path)

        # Override path constants from config so all other functions see them.
        PID_FILE    = Path(self._config.get("daemon", "pid_file",    default=str(DAEMON_DIR / "codey-v2.pid")))
        SOCKET_FILE = Path(self._config.get("daemon", "socket_file", default=str(DAEMON_DIR / "codey-v2.sock")))
        LOG_FILE    = Path(log_file_path)

        self.state = get_state_store()
        self.server = DaemonServer(self.state, shutdown_callback=self._trigger_shutdown)
        self.executor = TaskExecutor(self.state, self._config)
        from core.planner_v2 import get_planner
        self.planner = get_planner()
        # Give DaemonServer access to the planner so _handle_command can queue steps.
        self.server.planner = self.planner
        from core.background import get_background_manager, get_file_watch_manager
        self.background = get_background_manager()
        self.file_watch = get_file_watch_manager()
        self.running = True
        self._reload_requested = False

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)

        # Wire ProjectMemory: load CODEY.md and config.json at boot (never evicted)
        try:
            from core.memory import memory as _mem
            from core.codeymd import find_codeymd, read_codeymd
            from pathlib import Path as _Path

            # Load CODEY.md if it exists
            _codeymd_path = find_codeymd()
            if _codeymd_path:
                _codeymd_content = read_codeymd()
                if _codeymd_content and not _codeymd_content.startswith("[ERROR]"):
                    _mem.add_to_project(_codeymd_path, _codeymd_content, is_protected=True)
                    info(f"ProjectMemory: loaded {_codeymd_path}")

            # Load config.json if it exists
            _config_path = _Path.home() / ".codey-v2" / "config.json"
            if _config_path.exists():
                _config_content = _config_path.read_text(encoding="utf-8", errors="replace")
                _mem.add_to_project(str(_config_path), _config_content, is_protected=True)
                info(f"ProjectMemory: loaded {_config_path}")
        except Exception as _e:
            warning(f"ProjectMemory initialization skipped: {_e}")

    def _trigger_shutdown(self):
        """Called by DaemonServer when a socket shutdown command is received."""
        info("Daemon shutdown triggered via socket command")
        self.running = False
        if self.server.server:
            self.server.server.close()
    
    def _handle_sigterm(self, signum, frame):
        """Handle SIGTERM (graceful shutdown)."""
        info("SIGTERM received, shutting down...")
        self.running = False
    
    def _handle_sigusr1(self, signum, frame):
        """Handle SIGUSR1 (reload configuration)."""
        info("SIGUSR1 received, reload requested")
        self._reload_requested = True
    
    async def _main_loop(self):
        """Main daemon event loop."""
        info("Daemon started")
        self.state.set("daemon_started_at", int(time.time()))
        self.state.log_action("daemon_started", f"PID {os.getpid()}")

        # Start socket server
        server_task = asyncio.create_task(self.server.start())

        # NOTE: We do NOT start executor.start() as a background task.
        # The executor's auto-poll loop and _process_planner_tasks both poll the
        # same SQLite task_queue, creating a race where the same task could be
        # claimed and executed twice.  All task dispatch goes through
        # _process_planner_tasks, which uses try_claim_task() for atomic claiming.

        # Pre-load 7B model (llama-server on port 8080) so it's ready for CLI
        try:
            from core.loader_v2 import get_loader
            loader = get_loader()
            if loader.ensure_model():
                info("7B model pre-loaded (port 8080)")
            else:
                warning("7B model pre-load failed — will load on first request")
        except Exception as _e:
            warning(f"7B model pre-load skipped: {_e}")

        # Start dedicated embedding server (nomic-embed on port 8082)
        try:
            from core.embed_server import start_embed_server
            if start_embed_server():
                info("Embed server started (port 8082)")
            else:
                warning("Embed server unavailable — BM25-only KB search active")
        except Exception as _e:
            warning(f"Embed server startup skipped: {_e}")

        # Start file watch manager
        self.file_watch.start()

        _watchdog_ticks = 0
        try:
            while self.running:
                # Check for reload request
                if self._reload_requested:
                    info("Processing reload...")
                    self._reload_requested = False

                # Dispatch next ready task (planner queue + direct commands)
                await self._process_planner_tasks()

                # Cleanup completed background tasks periodically
                self.background.cleanup_completed(max_age=3600)

                # Watchdog — check servers every 30s (60 × 0.5s)
                _watchdog_ticks += 1
                if _watchdog_ticks >= 60:
                    _watchdog_ticks = 0
                    # 7B model server watchdog
                    try:
                        from core.loader_v2 import get_loader
                        _loader = get_loader()
                        if not _loader.get_loaded_model():
                            warning("7B model server died — restarting...")
                            _loader.load_primary()
                    except Exception:
                        pass
                    # Embed server watchdog
                    try:
                        from core.embed_server import get_embed_server
                        if not get_embed_server().is_running():
                            warning("Embed server died — restarting...")
                            from core.embed_server import start_embed_server
                            start_embed_server()
                    except Exception:
                        pass

                # Small sleep to avoid busy loop
                await asyncio.sleep(0.5)

        finally:
            # Stop file watch
            self.file_watch.stop()

            # Stop embed server
            try:
                from core.embed_server import stop_embed_server
                stop_embed_server()
            except Exception:
                pass

            # Cleanup
            await self.server.stop()
            remove_pid_file()
            self.state.set("daemon_stopped_at", int(time.time()))
            self.state.log_action("daemon_stopped", f"PID {os.getpid()}")
            info("Daemon stopped")

    async def _process_planner_tasks(self):
        """Dispatch one ready task per main-loop tick.

        Two task sources are unified here:

        1. Planner tasks  — added via Planner.add_task(); tracked in the planner's
           in-memory dict AND persisted to SQLite.
        2. Direct command tasks — added via the socket `command` handler directly
           into SQLite (not in the planner dict).

        All claiming is done with state.try_claim_task() which atomically flips
        status pending→running only once, preventing double-execution.
        """
        timeout = self._config.get("tasks", "task_timeout", default=1800)

        # ── 1. Try a planner task first (respects dependency ordering) ──────────
        planner_task = self.planner.get_next_task()
        if planner_task:
            # Atomically claim in SQLite before any yield point.
            if not self.state.try_claim_task(planner_task.id):
                # Already claimed by a previous tick that somehow didn't clean up.
                # Sync in-memory state from SQLite.
                db = self.state.get_task(planner_task.id)
                if db:
                    if db["status"] == "done":
                        self.planner.complete_task(planner_task.id, db.get("result", ""))
                    elif db["status"] == "failed":
                        self.planner.fail_task(planner_task.id, db.get("result", "already failed"))
                return

            # Sync in-memory planner state. planner.start_task() re-runs the SQLite
            # UPDATE (harmless — overwrites 'running' with 'running') and sets the
            # in-memory task status and _current_task pointer.
            self.planner.start_task(planner_task.id)

            info(f"Planner: dispatching task {planner_task.id}: {planner_task.description[:50]}...")
            try:
                result = await asyncio.wait_for(
                    self.executor._execute_task(planner_task.description),
                    timeout=timeout,
                )
                self.planner.complete_task(planner_task.id, result)
            except asyncio.TimeoutError:
                err = f"Task timed out after {timeout}s"
                error(err)
                self.planner.fail_task(planner_task.id, err)
            except Exception as e:
                error(f"Planner: task {planner_task.id} error: {e}")
                self.planner.fail_task(planner_task.id, str(e))
            return

        # ── 2. Fall back to direct-command tasks (not in planner dict) ──────────
        db_task = self.state.get_next_pending()
        if not db_task:
            return
        # Only handle tasks that aren't tracked by the planner in memory.
        if db_task["id"] in self.planner._tasks:
            return  # planner will handle it next tick

        if not self.state.try_claim_task(db_task["id"]):
            return  # lost the race — another path claimed it

        info(f"Daemon: executing direct task {db_task['id']}: {db_task['description'][:50]}...")
        try:
            result = await asyncio.wait_for(
                self.executor._execute_task(db_task["description"]),
                timeout=timeout,
            )
            self.state.complete_task(db_task["id"], result)
        except asyncio.TimeoutError:
            self.state.fail_task(db_task["id"], f"Task timed out after {timeout}s")
        except Exception as e:
            self.state.fail_task(db_task["id"], str(e))

    def run(self):
        """Run the daemon."""
        write_pid_file()
        info(f"Daemon PID: {os.getpid()}")

        try:
            asyncio.run(self._main_loop())
        except KeyboardInterrupt:
            info("Interrupted")
        finally:
            remove_pid_file()


# ==================== CLI Functions ====================

def is_daemon_running() -> bool:
    """Check if daemon is running by testing socket."""
    if not SOCKET_FILE.exists():
        return False
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(SOCKET_FILE))
        sock.close()
        return True
    except (socket.error, OSError):
        return False


def send_command(cmd: str, data: Dict = None) -> Dict:
    """Send a command to the daemon via socket."""
    if not SOCKET_FILE.exists():
        raise ConnectionError("Daemon socket not found. Is the daemon running?")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(60.0)

    try:
        sock.connect(str(SOCKET_FILE))

        # Send request
        request = {"cmd": cmd, "data": data or {}}
        sock.sendall(json.dumps(request).encode('utf-8'))

        # Receive response
        response_data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        
        if not response_data:
            raise ConnectionError("No response from daemon. Connection closed.")

        response = json.loads(response_data.decode('utf-8'))
        
        # Check for error response
        if response.get("status") == "error":
            raise RuntimeError(response.get("message", "Unknown error"))
        
        return response

    except socket.timeout:
        raise ConnectionError("Connection timed out. Daemon may be busy.")
    except socket.error as e:
        raise ConnectionError(f"Socket error: {e}. Is the daemon running?")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid response from daemon: {e}")
    finally:
        try:
            sock.close()
        except:
            pass


def daemon_status() -> Dict:
    """Get daemon status."""
    return send_command("status")


def daemon_health() -> Dict:
    """Get daemon health check."""
    return send_command("health")


def daemon_ping() -> Dict:
    """Ping the daemon."""
    return send_command("ping")


def daemon_shutdown():
    """Request daemon shutdown."""
    return send_command("shutdown")


# ==================== Entry Point ====================

def main():
    """Main entry point for daemon."""
    if check_pid_file():
        error("Daemon is already running")
        sys.exit(1)
    
    daemon = Daemon()
    daemon.run()


if __name__ == "__main__":
    main()
