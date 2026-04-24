"""Process Manager - spawn, monitor, and control long-running agent processes.

Process ID = Session ID, so processes persist via Memory API.

Architecture:
- ProcessManager: singleton managing all processes
- Process: represents a running agent instance
- Each process has its own Core and runs in its own session

Usage:
    from process_manager import process_manager
    
    # Spawn a process
    proc = process_manager.spawn("codehammer", "Fix the bug")
    
    # Poll for output
    while not proc.is_done:
        for event in proc.get_output():
            print(event)
        time.sleep(0.5)
    
    # Send a message
    process_manager.send_message("proc-id", "Also check login.py")
    
    # Stop
    process_manager.stop("proc-id")
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import AsyncIterator

from core import Core
from config import get, get_llm_config


class ProcessStatus(str, Enum):
    """Process lifecycle states."""
    IDLE = "idle"      # Spawned, waiting for message
    RUNNING = "running"  # Actively processing
    DONE = "done"      # Finished (success or error)
    STOPPED = "stopped"  # Killed by user


@dataclass
class ProcessEvent:
    """A single event from a process (token, tool_call, etc)."""
    type: str  # token, thinking, tool_call, tool_result, error, done
    content: str | None = None
    name: str | None = None
    args: dict | None = None
    result: dict | None = None
    error: str | None = None
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        result = {"type": self.type, "timestamp": self.timestamp}
        if self.content is not None:
            result["content"] = self.content
        if self.name is not None:
            result["name"] = self.name
        if self.args is not None:
            result["args"] = self.args
        if self.result is not None:
            result["result"] = self.result
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass
class Process:
    """A running agent process."""
    process_id: str  # Same as session_id
    shard_name: str
    shard: dict
    llm_config: dict
    status: ProcessStatus = ProcessStatus.IDLE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Internal state
    _core: Core | None = None
    _events: list[ProcessEvent] = field(default_factory=list)
    _last_poll: float = field(default_factory=lambda: time.time())
    _task: asyncio.Task | None = None
    _running_stream: AsyncIterator[dict] | None = None
    _cancellation_event: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    @property
    def is_done(self) -> bool:
        return self.status in (ProcessStatus.DONE, ProcessStatus.STOPPED)
    
    @property
    def is_running(self) -> bool:
        return self.status == ProcessStatus.RUNNING
    
    @property
    def elapsed_seconds(self) -> float | None:
        if self.started_at:
            end = self.completed_at or datetime.now(timezone.utc)
            return (end - self.started_at).total_seconds()
        return None
    
    def get_output(
        self,
        messages: bool = True,
        thinking: bool = False,
        tool_calls: bool = False,
        tool_results: bool = False,
        errors: bool = False,
        last_only: bool = False,
        since: float | None = None,
    ) -> list[dict]:
        """Get output events with filtering.
        
        Args:
            messages: Include token output
            thinking: Include reasoning/thinking content
            tool_calls: Include function call events
            tool_results: Include function result events
            errors: Include error events
            last_only: Only return events since last poll
            since: Only return events after this timestamp
        
        Returns:
            List of filtered event dicts
        """
        self._last_poll = time.time()
        
        output = []
        events = self._events
        
        if since is not None:
            events = [e for e in events if e.timestamp > since]
        
        if last_only:
            # Return only events since last poll — filter out older ones
            events = [e for e in events if e.timestamp > self._last_poll]
        
        for event in events:
            if event.type == "token" and messages:
                output.append(event.to_dict())
            elif event.type == "thinking" and thinking:
                output.append(event.to_dict())
            elif event.type == "tool_call" and tool_calls:
                output.append(event.to_dict())
            elif event.type == "tool_result" and tool_results:
                output.append(event.to_dict())
            elif event.type in ("error", "done") and errors:
                output.append(event.to_dict())
        
        return output
    
    def add_event(self, event: ProcessEvent) -> None:
        """Add an event to this process's output buffer."""
        self._events.append(event)
    
    def clear_output(self) -> None:
        """Clear all stored events."""
        self._events.clear()


class ProcessManager:
    """Manages all running agent processes.
    
    Singleton - import and use directly:
        from process_manager import process_manager
        process_manager.spawn("codehammer", "Fix the bug")
    """
    
    def __init__(self):
        self._processes: dict[str, Process] = {}
        self._max_processes = get("process_manager.max_processes", 50)
    
    def spawn(
        self,
        shard_name: str,
        message: str | None = None,
        process_id: str | None = None,
        llm_config: str = "primary",
    ) -> Process:
        """Spawn a new process.
        
        Args:
            shard_name: Which shard/config to use
            message: Initial message to send (optional)
            process_id: Custom process ID (auto-generated if None)
            llm_config: Which LLM config to use
        
        Returns:
            The created Process object
        """
        if len(self._processes) >= self._max_processes:
            raise RuntimeError(f"Max processes reached ({self._max_processes})")
        
        # Generate process ID if not provided
        if process_id is None:
            process_id = f"proc-{uuid.uuid4().hex[:12]}"
        
        # Load shard config (same logic as api.py)
        shard = self._load_shard(shard_name)
        
        # LLM config
        llm_cfg = get_llm_config(llm_config)
        
        # Create process
        proc = Process(
            process_id=process_id,
            shard_name=shard_name,
            shard=shard,
            llm_config=llm_cfg,
            status=ProcessStatus.IDLE,
        )
        
        # Store in registry
        self._processes[process_id] = proc
        
        # If initial message provided, send it immediately
        if message:
            # Schedule async sending (don't block)
            asyncio.create_task(self._send_and_run(proc, message))
        
        return proc
    
    def _load_shard(self, shard_name: str) -> dict:
        """Load shard config by name (same logic as api.py)."""
        import glob
        import yaml
        
        shards_dir = "shards"
        
        # Try to find YAML file
        for filepath in glob.glob(f"{shards_dir}/*.yaml"):
            with open(filepath) as f:
                data = yaml.safe_load(f)
                if data and data.get("name") == shard_name:
                    shard = data
                    break
        else:
            # Build from config defaults
            shard = {
                "name": shard_name,
                "modules": get("modules", ["time", "shell"]),
                "system": get("system", "You are a helpful assistant."),
                "tool_timeout": get("tool_timeout", 60),
                "max_function_calls": get("max_function_calls", 20),
            }
        
        # Ensure memory_api is set
        shard.setdefault("memory_api", {"url": get("memory_api.url")})
        
        return shard
    
    async def _send_and_run(self, proc: Process, message: str) -> None:
        """Send a message to a process and run until done or next context_rebuilt.
        
        This is the main loop for a process. It:
        1. Stores the message to Memory API
        2. Creates a Core instance
        3. Runs the loop until context_rebuilt (waits for more input) or done
        """
        import requests
        from modules import _session_id
        
        proc.status = ProcessStatus.RUNNING
        proc.started_at = datetime.now(timezone.utc)
        
        # Store message to Memory API
        memory_url = proc.shard.get("memory_api", {}).get("url") or get("memory_api.url")
        
        try:
            resp = requests.post(
                f"{memory_url}/context",
                json={"role": "user", "content": message, "session": proc.process_id},
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                proc.add_event(ProcessEvent(
                    type="error",
                    error=f"Failed to store message: HTTP {resp.status_code}"
                ))
                proc.status = ProcessStatus.DONE
                proc.completed_at = datetime.now(timezone.utc)
                return
        except Exception as e:
            proc.add_event(ProcessEvent(type="error", error=f"Memory API error: {e}"))
            proc.status = ProcessStatus.DONE
            proc.completed_at = datetime.now(timezone.utc)
            return
        
        # Create Core instance
        proc._core = Core(
            shard=proc.shard,
            llm=proc.llm_config,
            max_function_calls=proc.shard.get("max_function_calls", 20),
        )
        
        # Set session ID context var
        token = _session_id.set(proc.process_id)
        
        try:
            # Run the loop
            done = False
            while not done and not proc._cancellation_event.is_set():
                async for event in proc._core.run_stream(proc.process_id):
                    # Handle cancellation
                    if proc._cancellation_event.is_set():
                        proc.add_event(ProcessEvent(
                            type="error",
                            error="Process cancelled by user"
                        ))
                        proc.status = ProcessStatus.STOPPED
                        break
                    
                    # Process the event
                    if "token" in event:
                        proc.add_event(ProcessEvent(type="token", content=event["token"]))
                    elif "thinking" in event:
                        proc.add_event(ProcessEvent(type="thinking", content=event["thinking"]))
                    elif "tool_call" in event:
                        tc = event["tool_call"]
                        proc.add_event(ProcessEvent(
                            type="tool_call",
                            name=tc.get("name"),
                            args=tc.get("arguments"),
                        ))
                    elif "tool_result" in event:
                        tr = event["tool_result"]
                        proc.add_event(ProcessEvent(
                            type="tool_result",
                            name=tr.get("name"),
                            result={"content": tr.get("content"), "error": tr.get("error")},
                        ))
                    elif "error" in event:
                        proc.add_event(ProcessEvent(type="error", error=event["error"]))
                        done = True
                    elif "done" in event:
                        proc.add_event(ProcessEvent(type="done"))
                        done = True
                    elif "context_rebuilt" in event:
                        # LLM is waiting for more input - stop here, let caller send next message
                        done = True
                        proc.status = ProcessStatus.IDLE
        except Exception as e:
            proc.add_event(ProcessEvent(type="error", error=str(e)))
        finally:
            _session_id.reset(token)
            
            if proc.status == ProcessStatus.RUNNING:
                proc.status = ProcessStatus.DONE
            proc.completed_at = datetime.now(timezone.utc)
    
    def send_message(self, process_id: str, message: str) -> bool:
        """Send a message to a running process.
        
        Args:
            process_id: Process to send to
            message: Message content
        
        Returns:
            True if message was queued, False if process not found or not in idle state
        """
        proc = self._processes.get(process_id)
        if not proc:
            return False
        
        if proc.status != ProcessStatus.IDLE:
            return False
        
        # Queue the message for async processing
        asyncio.create_task(self._send_and_run(proc, message))
        return True
    
    def stop(self, process_id: str) -> bool:
        """Stop a running process.
        
        Args:
            process_id: Process to stop
        
        Returns:
            True if stopped, False if not found
        """
        proc = self._processes.get(process_id)
        if not proc:
            return False
        
        proc._cancellation_event.set()
        proc.status = ProcessStatus.STOPPED
        proc.completed_at = datetime.now(timezone.utc)
        return True
    
    def get(self, process_id: str) -> Process | None:
        """Get a process by ID."""
        return self._processes.get(process_id)
    
    def list(
        self,
        shard_name: str | None = None,
        status: ProcessStatus | None = None,
    ) -> list[Process]:
        """List processes with optional filtering.
        
        Args:
            shard_name: Filter by shard name
            status: Filter by status
        
        Returns:
            List of matching processes
        """
        procs = list(self._processes.values())
        
        if shard_name:
            procs = [p for p in procs if p.shard_name == shard_name]
        
        if status:
            procs = [p for p in procs if p.status == status]
        
        return procs
    
    def remove(self, process_id: str) -> bool:
        """Remove a process (cleanup after done).
        
        Args:
            process_id: Process to remove
        
        Returns:
            True if removed, False if not found
        """
        if process_id in self._processes:
            del self._processes[process_id]
            return True
        return False
    
    def cleanup_done(self) -> int:
        """Remove all done/stopped processes.
        
        Returns:
            Number of processes cleaned up
        """
        to_remove = [
            pid for pid, proc in self._processes.items()
            if proc.status in (ProcessStatus.DONE, ProcessStatus.STOPPED)
        ]
        for pid in to_remove:
            del self._processes[pid]
        return len(to_remove)


# Singleton instance
process_manager = ProcessManager()
