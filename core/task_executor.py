#!/usr/bin/env python3
"""
Task executor for Codey v2 daemon.

Executes queued tasks using the existing agent infrastructure.
Runs in the background as part of the daemon event loop.
"""

import asyncio
import time
from typing import Optional, Dict, Any, List
from pathlib import Path

from utils.logger import info, warning, error, success, debug
from utils.config import AGENT_CONFIG
from core.state import StateStore
from core.daemon_config import DaemonConfig

# Import agent components for task execution
# We'll use a simplified execution path that doesn't require full REPL
from core.inference import infer
from core.context import build_file_context_block, auto_load_from_prompt
from core.project import get_project_summary
from core.codeymd import read_codeymd, find_codeymd
from core.summarizer import summarize_history
from prompts.system_prompt import SYSTEM_PROMPT


class TaskExecutor:
    """
    Executes tasks from the daemon's task queue.
    
    Runs asynchronously in the background, processing pending tasks
    one at a time using the agent inference engine.
    """
    
    def __init__(self, state: StateStore, config: DaemonConfig):
        self.state = state
        self.config = config
        self.running = False
        self.current_task: Optional[Dict] = None
        self._task_history: List[Dict] = []
    
    async def start(self):
        """Start the task executor loop."""
        self.running = True
        info("Task executor started")
        
        while self.running:
            try:
                await self._process_next_task()
                await asyncio.sleep(0.5)  # Avoid busy loop
            except asyncio.CancelledError:
                break
            except Exception as e:
                error(f"Task executor error: {e}")
                await asyncio.sleep(1)
        
        info("Task executor stopped")
    
    def stop(self):
        """Stop the task executor."""
        self.running = False
    
    async def _process_next_task(self):
        """Get and process the next pending task."""
        task = self.state.get_next_pending()
        if not task:
            return
        
        task_id = task["id"]
        description = task["description"]
        
        # Check if task was cancelled while pending
        if self.state.get(f"task_cancelled_{task_id}"):
            info(f"Task {task_id} was cancelled, skipping")
            self.state.delete(f"task_cancelled_{task_id}")
            self.state.fail_task(task_id, "Task cancelled by user")
            return
        
        info(f"Executing task {task_id}: {description[:60]}...")
        self.state.start_task(task_id)
        self.current_task = task
        
        try:
            # Get timeout from config
            timeout = self.config.get("tasks", "task_timeout", default=1800)
            
            # Execute with timeout
            result = await asyncio.wait_for(
                self._execute_task(description),
                timeout=timeout
            )
            
            self.state.complete_task(task_id, result)
            success(f"Task {task_id} completed successfully")
            
        except asyncio.TimeoutError:
            error_msg = f"Task timed out after {timeout} seconds"
            error(error_msg)
            self.state.fail_task(task_id, error_msg)
            
        except Exception as e:
            error_msg = f"Task failed: {str(e)}"
            error(error_msg)
            self.state.fail_task(task_id, error_msg)
        
        finally:
            self.current_task = None
    
    async def _execute_task(self, prompt: str) -> str:
        """
        Execute a single task using the agent inference engine.
        
        This is a simplified execution that:
        1. Builds context from project files
        2. Runs inference with the agent prompt
        3. Executes any tool calls in the response
        4. Returns the final result
        """
        try:
            # Build system prompt
            system_prompt = SYSTEM_PROMPT
            
            # Add project context if available
            from core.project import detect_project
            project_info = detect_project()
            if project_info.get("type", "unknown") != "unknown":
                system_prompt += f"\n\nCurrent Project: {project_info['type']} in {project_info['cwd']}"
            
            # Add CODEY.md context if available
            codeymd_path = find_codeymd()
            if codeymd_path:
                try:
                    codeymd_content = read_codeymd()
                    system_prompt += f"\n\nProject Memory (CODEY.md):\n{codeymd_content[:2000]}"
                except Exception as e:
                    warning(f"Could not read CODEY.md: {e}")
            
            # Build user message with context
            try:
                context_block = build_file_context_block()
            except Exception as e:
                warning(f"Could not build context block: {e}")
                context_block = ""
            
            if context_block:
                user_message = f"{context_block}\n\nTask: {prompt}"
            else:
                user_message = f"Task: {prompt}"
            
            # Create messages for inference
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            debug(f"Starting task execution with {len(messages)} messages")
            
            # Run inference (this may include tool calls)
            # For daemon mode, we run with auto-execute for simple tasks
            result = await self._run_with_tool_execution(messages)
            
            return result
            
        except Exception as e:
            import traceback
            error(f"Task execution error: {e}")
            error(traceback.format_exc())
            raise RuntimeError(f"Execution failed: {e}")
    
    async def _run_with_tool_execution(self, messages: List[Dict], max_steps: int = 6) -> str:
        """
        Run inference with automatic tool execution.

        Similar to the agent loop but simplified for background execution.
        """
        from tools.file_tools import tool_read_file, tool_write_file, tool_append_file, tool_list_dir
        from tools.patch_tools import tool_patch_file
        from tools.shell_tools import shell, search_files

        TOOLS = {
            "read_file": lambda args: tool_read_file(args["path"]),
            "write_file": lambda args: self._confirm_write(args["path"], args["content"]),
            "patch_file": lambda args: tool_patch_file(args["path"], args["old_str"], args["new_str"]),
            "append_file": lambda args: tool_append_file(args["path"], args["content"]),
            "list_dir": lambda args: tool_list_dir(args.get("path", ".")),
            "shell": lambda args: self._confirm_shell(args["command"]),
            "search_files": lambda args: search_files(args["pattern"], args.get("path", ".")),
        }
        
        step = 0
        while step < max_steps:
            step += 1
            
            debug(f"Step {step}: Running inference")

            # Run inference
            response = infer(messages, stream=False)
            
            debug(f"Step {step}: Got response ({len(response)} chars)")

            # Check for tool calls
            tool_match = self._extract_tool_call(response)
            if not tool_match:
                debug(f"Step {step}: No tool call found, returning response")
                # No tool call, return the response
                return self._clean_response(response)

            tool_name, tool_args = tool_match
            debug(f"Step {step}: Found tool '{tool_name}' with args type {type(tool_args)}")
            
            # Ensure tool_args is a dict
            if tool_args is None:
                tool_args = {}
            elif isinstance(tool_args, str):
                # Try to parse as JSON
                try:
                    import json
                    tool_args = json.loads(tool_args)
                    debug(f"Step {step}: Parsed string args to dict")
                except:
                    tool_args = {"raw": tool_args}
                    debug(f"Step {step}: Could not parse args, using raw")

            # Log tool call
            info(f"Tool: {tool_name}({tool_args})")

            # Execute tool
            if tool_name in TOOLS:
                try:
                    result = TOOLS[tool_name](tool_args)
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": f"Tool result: {result}"})
                    debug(f"Step {step}: Tool executed successfully")
                except Exception as e:
                    error(f"Tool {tool_name} error: {e}")
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": f"Tool error: {e}"})
            else:
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"Unknown tool: {tool_name}"})

        # Max steps reached, return last response
        debug("Max steps reached")
        return self._clean_response(response)
    
    def _extract_tool_call(self, response: str) -> Optional[tuple]:
        """Extract tool call from response."""
        import re
        import json
        
        # Look for <tool>...</tool> pattern
        tool_pattern = r'<tool>\s*(\{.*?\})\s*</tool>'
        match = re.search(tool_pattern, response, re.DOTALL)
        
        if match:
            try:
                tool_data = json.loads(match.group(1))
                return tool_data.get("name"), tool_data.get("args", {})
            except json.JSONDecodeError:
                pass
        
        # Also check for bare JSON at start
        stripped = response.strip()
        if stripped.startswith('{'):
            try:
                # Find the end of the JSON object
                depth = 0
                in_string = False
                for i, ch in enumerate(stripped):
                    if ch == '"' and (i == 0 or stripped[i-1] != '\\'):
                        in_string = not in_string
                    elif not in_string:
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                tool_data = json.loads(stripped[:i+1])
                                if "name" in tool_data and "args" in tool_data:
                                    return tool_data["name"], tool_data["args"]
                                break
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _clean_response(self, text: str) -> str:
        """Clean up response text."""
        import re
        # Remove tool tags
        text = re.sub(r'<tool>.*?</tool>', '', text, flags=re.DOTALL)
        # Remove leading/trailing whitespace
        return text.strip()
    
    def _confirm_write(self, path: str, content: str) -> str:
        """Confirm and execute file write (daemon mode - auto-confirm)."""
        from tools.file_tools import tool_write_file
        # In daemon mode, we auto-confirm writes
        return tool_write_file(path, content)
    
    def _confirm_shell(self, command: str) -> str:
        """Confirm and execute shell command (daemon mode - auto-confirm)."""
        # In daemon mode, we auto-confirm shell commands
        return shell(command)
    
    def get_current_task(self) -> Optional[Dict]:
        """Get the currently executing task."""
        return self.current_task
    
    def get_task_history(self, limit: int = 10) -> List[Dict]:
        """Get recent task history."""
        return self._task_history[-limit:]


# Global executor instance
_executor: Optional[TaskExecutor] = None


def get_executor() -> TaskExecutor:
    """Get the global task executor instance."""
    global _executor
    if _executor is None:
        from core.state import get_state_store
        from core.daemon_config import get_config
        _executor = TaskExecutor(get_state_store(), get_config())
    return _executor


def reset_executor():
    """Reset the global executor (for testing)."""
    global _executor
    if _executor:
        _executor = None
