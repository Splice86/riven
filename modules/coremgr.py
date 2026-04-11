"""Core manager module for riven - manages running agent cores."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from core import get_core, list_cores

# Storage for running and completed cores
_running_cores: dict = {}
_completed_cores: dict = {}


@dataclass
class CoreRun:
    """Represents a running or completed core."""
    id: str
    core_name: str
    message: str
    status: str  # "running", "completed", "error"
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None


def _run_async(run_id: str, core_name: str, message: str) -> None:
    """Actually run the core asynchronously in background."""
    try:
        core = get_core(core_name)
        result = asyncio.run(core.run(message))
        
        _completed_cores[run_id] = CoreRun(
            id=run_id,
            core_name=core_name,
            message=message,
            status="completed",
            result=str(result.output) if result else None,
            finished_at=datetime.now()
        )
    except Exception as e:
        _completed_cores[run_id] = CoreRun(
            id=run_id,
            core_name=core_name,
            message=message,
            status="error",
            error=str(e),
            finished_at=datetime.now()
        )
    finally:
        if run_id in _running_cores:
            del _running_cores[run_id]


def get_module():
    """Get the coremgr module.
    
    Returns:
        CoreMgr Module instance
    """
    from modules import Module

    async def coremgr_get_context() -> str:
        """Get context about running cores.
        
        Returns a string listing all running cores with their IDs and status.
        """
        lines = []
        
        # Always show available core types
        available = list_cores()
        lines.append(f"Available cores: {', '.join(available)}")
        
        if not _running_cores and not _completed_cores:
            lines.append("No cores currently running or completed")
            return "\n".join(lines)
        
        # Running cores
        if _running_cores:
            lines.append("Running:")
            for run_id, run in _running_cores.items():
                lines.append(f"  {run_id}: {run.core_name} - started {run.started_at.strftime('%H:%M:%S')}")
        else:
            lines.append("No cores currently running")
        
        # Recently completed (last 5)
        if _completed_cores:
            lines.append("Completed:")
            for run_id, run in list(_completed_cores.items())[-5:]:
                finished = run.finished_at.strftime('%H:%M:%S') if run.finished_at else "?"
                lines.append(f"  {run_id}: {run.core_name} - {run.status} at {finished}")
        
        return "\n".join(lines)
    
    async def coremgr_run(core: str, message: str, blocking: bool = False, timeout: int = 300) -> dict:
        """Start a core running with a message.
        
        Args:
            core: Name of the core to run (e.g., 'code_hammer', 'research')
            message: Message to send to the core
            blocking: If True, wait for completion (uses timeout). If False, run async.
            timeout: Seconds to wait for blocking runs (default: 300)
        
        Returns:
            dict with 'id', 'core', 'started', 'ok' fields. If blocking=True, also includes 'result' or 'error'.
        """
        # Validate core exists
        available = list_cores()
        if core not in available:
            return {
                "id": None,
                "core": core,
                "started": False,
                "ok": False,
                "error": f"Core '{core}' not found. Available: {available}"
            }
        
        # Generate unique ID
        run_id = str(uuid.uuid4())[:8]
        
        # Create running entry
        _running_cores[run_id] = CoreRun(
            id=run_id,
            core_name=core,
            message=message,
            status="running"
        )
        
        if blocking:
            # Run synchronously and wait for completion
            import concurrent.futures
            
            result_holder = {"result": None, "error": None}
            
            def run_blocking():
                try:
                    core_instance = get_core(core)
                    result = asyncio.run(core_instance.run(message))
                    result_holder["result"] = str(result.output) if result else None
                except Exception as e:
                    result_holder["error"] = str(e)
            
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(run_blocking)
            
            try:
                future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                result_holder["error"] = f"Timeout after {timeout} seconds"
            except Exception as e:
                result_holder["error"] = str(e)
            
            executor.shutdown(wait=False)
            
            # Move to completed
            finished_at = datetime.now()
            _completed_cores[run_id] = CoreRun(
                id=run_id,
                core_name=core,
                message=message,
                status="error" if result_holder["error"] else "completed",
                result=result_holder.get("result"),
                error=result_holder.get("error"),
                finished_at=finished_at
            )
            del _running_cores[run_id]
            
            return {
                "id": run_id,
                "core": core,
                "started": True,
                "ok": result_holder["error"] is None,
                "result": result_holder.get("result"),
                "error": result_holder.get("error"),
                "finished": finished_at.isoformat()
            }
        
        # Non-blocking: start async execution in background thread
        import threading
        thread = threading.Thread(target=_run_async, args=(run_id, core, message))
        thread.daemon = True
        thread.start()
        
        return {
            "id": run_id,
            "core": core,
            "started": True,
            "ok": True,
            "message": f"Core '{core}' started with ID: {run_id}"
        }
    
    
    async def coremgr_get(id: str) -> dict:
        """Get the output from a completed core.
        
        Args:
            id: The core run ID to retrieve
        
        Returns:
            dict with 'id', 'status', 'result', 'core', 'message', and 'finished' fields
        """
        # Check running first
        if id in _running_cores:
            run = _running_cores[id]
            return {
                "id": run.id,
                "status": "running",
                "result": None,
                "core": run.core_name,
                "message": run.message,
                "finished": None,
                "started": run.started_at.isoformat()
            }
        
        # Check completed
        if id in _completed_cores:
            run = _completed_cores[id]
            return {
                "id": run.id,
                "status": run.status,
                "result": run.result,
                "error": run.error,
                "core": run.core_name,
                "message": run.message,
                "finished": run.finished_at.isoformat() if run.finished_at else None,
                "started": run.started_at.isoformat()
            }
        
        return {
            "id": id,
            "status": "not_found",
            "result": None,
            "error": f"No core found with ID '{id}'"
        }
    
    
    async def coremgr_list() -> dict:
        """List all running and completed core IDs.
        
        Returns:
            dict with 'running' and 'completed' lists of IDs
        """
        return {
            "running": list(_running_cores.keys()),
            "completed": list(_completed_cores.keys())
        }
    
    return Module(
        name="coremgr",
        enrollment=lambda: None,
        functions={
            "coremgr_get_context": coremgr_get_context,
            "coremgr_run": coremgr_run,
            "coremgr_get": coremgr_get,
            "coremgr_list": coremgr_list,
        }
    )
