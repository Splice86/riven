"""Riven API Server - simple HTTP API for riven_core.

Session ID is passed directly to Memory API - no session state stored here.
The API is stateless; all conversation history lives in the Memory API.
"""

import asyncio
import glob
import importlib
import logging
import json
import os
import pkgutil
import time
from typing import Optional

import requests
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

from core import Core
from config import get_llm_config, get

logger = logging.getLogger(__name__)

# High-level debug flag
DEBUG_HANG = False

def _debug(step: str, session_id: str = None) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = time.time()
    sid = f"[{session_id[:8]}]" if session_id else "[--------]"
    print(f"[DEBUG {ts:.3f}] {sid} {step}", flush=True)


# =============================================================================
# Shard helpers
# =============================================================================


def _shard_files() -> list[str]:
    """Get absolute paths of all shard YAML files."""
    shards_dir = os.path.join(os.path.dirname(__file__), "shards")
    if not os.path.exists(shards_dir):
        return []
    return glob.glob(os.path.join(shards_dir, "*.yaml"))


# =============================================================================
# API Models
# =============================================================================

class MessageRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: str  # Client provides this - passed directly to Memory API
    shard_name: str = "default"


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(title="Riven API", version="1.0.0")


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "riven": "riven_core"}


@app.get("/api/v1/shards")
def list_shards():
    """List available shards."""
    shards = []

    for filepath in _shard_files():
        with open(filepath) as f:
            data = yaml.safe_load(f)
            if data and "name" in data:
                shards.append({
                    "name": data.get("name"),
                    "display_name": data.get("display_name", data["name"]),
                })

    return {"shards": shards, "note": "Shards without a YAML file fall back to config defaults."}


def _load_shard(shard_name: str) -> dict:
    """Load shard config by name."""
    shard = None
    found = False

    for filepath in _shard_files():
        with open(filepath) as f:
            data = yaml.safe_load(f)
            if data and data.get("name") == shard_name:
                shard = data
                found = True
                break

    if shard is None:
        # Build from config defaults (fallback)
        shard = {
            "name": shard_name,
            "modules": get("modules", ["time", "shell"]),
            "system": get("system", "You are a helpful assistant."),
            "tool_timeout": get("tool_timeout", 60),
            "max_function_calls": get("max_function_calls", 20),
        }
        available = sorted(os.path.basename(f)[:-5] for f in _shard_files())
        pass  # Shard fallback handled silently
    else:
        pass  # Shard loaded silently

    # Ensure memory_api is always set from config (even if shard file doesn't have it)
    shard.setdefault("memory_api", {
        "url": get("memory_api.url"),
    })

    # Resolve llm_config reference if present
    if "llm_config" in shard:
        config_name = shard.pop("llm_config")
        shard["llm"] = get_llm_config(config_name)

    return shard


@app.post("/api/v1/messages")
async def send_message(req: MessageRequest):
    """Send a message and get a response.

    - stream=true: SSE with tokens as they arrive
    - stream=false: JSON with full output when done

    Session ID is passed directly to Memory API for context retrieval.
    No session state is stored in this API.

    The harness controls the agent loop: after each LLM turn, if tools were
    executed and context was rebuilt, it calls run_stream() again for the next turn.
    """
    shard = _load_shard(req.shard_name)
    llm = get_llm_config("primary")
    _debug(f"API: received message, shard={req.shard_name}", req.session_id)

    core = Core(shard=shard, llm=llm)

    # Store user message to Memory API first
    memory_url = get("memory_api.url")
    _debug("API: storing user message to memory API", req.session_id)

    try:
        r = requests.post(
            f"{memory_url}/context",
            json={"role": "user", "content": req.message, "session": req.session_id},
            timeout=30,
        )
        _debug("API: user message stored to memory API", req.session_id)
    except requests.RequestException as e:
        _debug(f"API: memory API error: {e}", req.session_id)
        raise HTTPException(500, f"Memory API error: {e}")

    if req.stream:
        async def generate():
            _debug("API: starting streaming response", req.session_id)
            try:
                # Harness controls the loop - calls run_stream() for each LLM turn
                turn_count = 0
                while True:
                    turn_count += 1
                    _debug(f"API: starting turn {turn_count}", req.session_id)

                    # Use a generator variable to ensure proper cleanup
                    generator = core.run_stream(req.session_id)
                    async for event in generator:
                        # Handle errors
                        if "error" in event:
                            _debug(f"API: received error event: {event['error'][:100]}", req.session_id)
                            yield f"data: {json.dumps({'error': event['error']})}\n\n"
                            # Ensure generator is cleaned up
                            await generator.aclose()
                            return  # Stop streaming on error - don't loop forever!

                        # Handle tool_call events - forward as-is
                        if "tool_call" in event:
                            _debug(f"API: tool_call: {event['tool_call']['name']}", req.session_id)
                            yield f"data: {json.dumps(event)}\n\n"

                        # Handle thinking events
                        elif "thinking" in event:
                            content = event["thinking"]
                            if content and content.strip():
                                yield f"data: {json.dumps({'thinking': content})}\n\n"

                        # Handle tool results - forward as-is
                        elif "tool_result" in event:
                            _debug(f"API: tool_result: {event['tool_result']['name']}", req.session_id)
                            yield f"data: {json.dumps(event)}\n\n"

                        # Regular token
                        elif "token" in event:
                            yield f"data: {json.dumps({'token': event['token']})}\n\n"

                        # Context rebuilt - properly cleanup and loop for next turn
                        if event.get("context_rebuilt"):
                            _debug(f"API: context_rebuilt, turn {turn_count} complete", req.session_id)
                            # Ensure generator cleanup before next turn
                            await generator.aclose()
                            break

                        # Done
                        if event.get("done"):
                            _debug("API: done, streaming complete", req.session_id)
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            await generator.aclose()
                            return

            except Exception as e:
                _debug(f"API: streaming exception: {e}", req.session_id)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming mode - harness controls the loop
    _debug("API: non-streaming mode", req.session_id)
    try:
        output = ""
        turn_count = 0
        while True:
            turn_count += 1
            _debug(f"API: non-streaming turn {turn_count}", req.session_id)
            async for event in core.run_stream(req.session_id):
                if "error" in event:
                    raise Exception(event["error"])
                if "token" in event:
                    output += event["token"]
                if event.get("done"):
                    return {"output": output}
                if event.get("context_rebuilt"):
                    _debug(f"API: context_rebuilt, turn {turn_count} done", req.session_id)
                    break  # exit inner loop, continue outer while True

        _debug("API: non-streaming complete", req.session_id)
        return {"output": output}

    except Exception as e:
        _debug(f"API: non-streaming exception: {e}", req.session_id)
        raise HTTPException(500, str(e))


# =============================================================================
# Process Management API
# =============================================================================

from process_manager import process_manager, ProcessStatus


class ProcessOutputParams:
    """Query params for /processes/{id}/output endpoint."""
    messages: bool = True
    thinking: bool = False
    tool_calls: bool = False
    tool_results: bool = False
    errors: bool = False
    last_only: bool = False


@app.get("/processes")
def list_processes(
    shard_name: str = None,
    status: str = None,
    action: str = None,
):
    """List processes, or perform an action.
    
    Actions:
        action=discover   Return shard list (same info as old /api/v1/shards)
    """
    # Shard discovery via the new process API
    if action == "discover":
        shards = []
        for filepath in _shard_files():
            with open(filepath) as f:
                data = yaml.safe_load(f)
                if data and "name" in data:
                    name = data.get("name")
                    llm_cfg = data.get("llm_config", "primary")
                    llm_info = {}
                    if llm_cfg in get("llm", {}):
                        llm_info = {
                            "config_name": llm_cfg,
                            "model": get(f"llm.{llm_cfg}.model"),
                            "url": get(f"llm.{llm_cfg}.url"),
                        }
                    shards.append({
                        "name": name,
                        "display_name": data.get("display_name", name),
                        "description": data.get("description", ""),
                        "modules": data.get("modules", []),
                        "llm_config": llm_info,
                        "system": (data.get("system", "") or "")[:200] + "..."
                            if len((data.get("system") or "")) > 200
                            else (data.get("system") or ""),
                    })
        return {
            "shards": shards,
            "default_shard": get("default_shard", "codehammer"),
        }

    status_enum = ProcessStatus(status) if status else None
    procs = process_manager.list(shard_name=shard_name, status=status_enum)

    return {
        "processes": [
            {
                "process_id": p.process_id,
                "shard_name": p.shard_name,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
                "started_at": p.started_at.isoformat() if p.started_at else None,
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                "elapsed_seconds": p.elapsed_seconds,
            }
            for p in procs
        ],
        "count": len(procs),
    }


@app.post("/processes")
async def spawn_process(req: Request):
    """Spawn a new process."""
    body = await req.json()
    
    shard_name = body.get("shard_name")
    if not shard_name:
        raise HTTPException(400, "shard_name is required")
    
    message = body.get("message")
    process_id = body.get("process_id")
    llm_config = body.get("llm_config", "primary")
    
    proc = process_manager.spawn(
        shard_name=shard_name,
        message=message,
        process_id=process_id,
        llm_config=llm_config,
    )
    
    return {
        "process_id": proc.process_id,
        "shard_name": proc.shard_name,
        "status": proc.status.value,
        "created_at": proc.created_at.isoformat(),
    }


@app.get("/processes/{process_id}")
def get_process(process_id: str):
    """Get process status and info."""
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    return {
        "process_id": proc.process_id,
        "shard_name": proc.shard_name,
        "status": proc.status.value,
        "created_at": proc.created_at.isoformat(),
        "started_at": proc.started_at.isoformat() if proc.started_at else None,
        "completed_at": proc.completed_at.isoformat() if proc.completed_at else None,
        "elapsed_seconds": proc.elapsed_seconds,
        "is_done": proc.is_done,
        "is_running": proc.is_running,
    }


@app.get("/processes/{process_id}/output")
def get_process_output(
    process_id: str,
    messages: bool = True,
    thinking: bool = False,
    tool_calls: bool = False,
    tool_results: bool = False,
    errors: bool = False,
    last_only: bool = False,
    since: float = None,
):
    """Get process output with filtering.
    
    Query params:
        messages: Include token output (default: true)
        thinking: Include reasoning content (default: false)
        tool_calls: Include function call events (default: false)
        tool_results: Include function result events (default: false)
        errors: Include error events (default: false)
        last_only: Only return events since last poll (default: false)
        since: Only return events after this timestamp
    """
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    output = proc.get_output(
        messages=messages,
        thinking=thinking,
        tool_calls=tool_calls,
        tool_results=tool_results,
        errors=errors,
        last_only=last_only,
        since=since,
    )
    
    return {
        "process_id": proc.process_id,
        "status": proc.status.value,
        "output": output,
        "last_poll": proc._last_poll,
    }


@app.get("/processes/{process_id}/output/stream")
async def stream_process_output(
    process_id: str,
    messages: bool = True,
    thinking: bool = False,
    tool_calls: bool = False,
    tool_results: bool = False,
    errors: bool = False,
):
    """Stream process output as SSE.
    
    Query params same as /output but no last_only/since (continuous stream).
    """
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    async def generate():
        seen_count = 0
        _debug(f"API: process_output/stream: starting for {process_id}")
        while not proc.is_done:
            events = proc.get_output(
                messages=messages,
                thinking=thinking,
                tool_calls=tool_calls,
                tool_results=tool_results,
                errors=errors,
            )
            
            # Yield only new events
            for i, event in enumerate(events):
                if i >= seen_count:
                    _debug(f"API: stream yielding event {i}: {event.get('type', '?')}")
                    yield f"event: output\ndata: {json.dumps(event)}\n\n"
                    seen_count = i + 1
            
            # Also yield status updates
            yield f"event: status\ndata: {json.dumps({'status': proc.status.value})}\n\n"
            
            await asyncio.sleep(0.25)
        
        # Final done event
        _debug(f"API: process_output/stream: done for {process_id}")
        yield f"event: done\ndata: {json.dumps({'status': proc.status.value})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/processes/{process_id}/input")
async def send_process_message(process_id: str, req: Request):
    """Send a message to a process.
    
    Only works if process is in idle state (waiting for input after context_rebuilt).
    """
    body = await req.json()
    message = body.get("message")
    if not message:
        raise HTTPException(400, "message is required")
    
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    if proc.status != ProcessStatus.IDLE:
        raise HTTPException(409, f"Process is {proc.status.value}, not idle")
    if not message:
        raise HTTPException(400, "message is required")
    
    success = process_manager.send_message(process_id, message)
    if not success:
        raise HTTPException(500, "Failed to queue message")
    
    return {"status": "ok", "message": "Message queued"}


@app.delete("/processes/{process_id}")
def stop_process(process_id: str):
    """Stop a running process."""
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    process_manager.stop(process_id)
    return {"ok": True, "process_id": process_id, "stopped_status": ProcessStatus.STOPPED.value}


@app.delete("/processes/{process_id}/cleanup")
def cleanup_process(process_id: str):
    """Remove a done/stopped process."""
    proc = process_manager.get(process_id)
    if not proc:
        raise HTTPException(404, f"Process '{process_id}' not found")
    
    if not proc.is_done:
        raise HTTPException(409, f"Process is {proc.status.value}, not done")
    
    process_manager.remove(process_id)
    return {"status": "ok", "process_id": process_id}


# =============================================================================
# Module Routes
# =============================================================================

def _discover_modules():
    """Scan modules/ directory and discover all subpackages with register_routes."""
    modules_dir = os.path.join(os.path.dirname(__file__), "modules")
    if not os.path.isdir(modules_dir):
        return []

    discovered = []
    for name in sorted(os.listdir(modules_dir)):
        mod_path = os.path.join(modules_dir, name)
        if not os.path.isdir(mod_path):
            continue
        if name.startswith("_"):
            continue
        if not os.path.exists(os.path.join(mod_path, "__init__.py")):
            continue

        try:
            mod = importlib.import_module(f"modules.{name}")
            if hasattr(mod, "register_routes"):
                discovered.append(name)
                logger.debug(f"Discovered module with routes: {name}")
        except Exception as e:
            logger.warning(f"[API] Failed to discover module '{name}': {e}")

    logger.info(f"[API] Discovered {len(discovered)} module(s) with routes: {discovered}")
    return discovered


def _register_module_routes(app, module_name: str):
    """Import and register routes from a single module."""
    try:
        mod = importlib.import_module(f"modules.{module_name}")
        mod.register_routes(app)
        logger.info(f"[API] Registered routes for module: {module_name}")
        return True
    except Exception as e:
        logger.warning(f"[API] Failed to register routes for module '{module_name}': {e}")
        return False


# Discover and register all module routes at startup
# (modules.file auto-includes screen WebSocket routes via its register_routes)
_registered_modules = _discover_modules()
for name in _registered_modules:
    _register_module_routes(app, name)


@app.get("/module/")
def list_modules():
    """List all modules that have registered API routes."""
    return {
        "modules": [
            {
                "name": name,
                "path": f"/module/{name}",
            }
            for name in _registered_modules
        ],
        "count": len(_registered_modules),
    }

# =============================================================================
# Screens
# =============================================================================

from modules.file.screens._registry import registry as screen_registry


@app.get("/api/v1/screens")
async def list_screens():
    """List all connected screens."""
    screens = await screen_registry.list_all()
    return {
        "screens": [
            {
                "uid": s.uid,
                "bound_path": s.bound_path,
                "bound_version": s.bound_version,
                "client_name": s.client_name,
                "status": "bound" if s.bound_path else "idle",
            }
            for s in screens
        ]
    }


@app.post("/api/v1/screens/{screen_uid}/bind")
async def bind_screen(screen_uid: str, path: str):
    """Bind a screen to a file path."""
    ok = await screen_registry.bind(screen_uid, path)
    if not ok:
        raise HTTPException(404, f"Screen '{screen_uid}' not found or not connected")
    return {"ok": True, "uid": screen_uid, "path": path}


@app.post("/api/v1/screens/{screen_uid}/release")
async def release_screen(screen_uid: str):
    """Release a screen from its current binding."""
    ok = await screen_registry.release(screen_uid)
    if not ok:
        raise HTTPException(404, f"Screen '{screen_uid}' not found or not connected")
    return {"ok": True, "uid": screen_uid}


# =============================================================================
# History API (for webui)
# =============================================================================

@app.get("/api/v1/history")
def get_history(session_id: str, response: Response):
    """Get conversation history for a session from Memory API."""
    # No caching - always fetch fresh data
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    memory_url = get("memory_api.url")
    try:
        resp = requests.get(
            f"{memory_url}/context",
            params={"session": session_id, "max_summaries": 0},
            timeout=30,
        )
        resp.raise_for_status()
        history = resp.json().get("context", [])
        # Debug: log the structure of each message type
        for i, msg in enumerate(history):
            role = msg.get('role', '?')
            content = msg.get('content', '<MISSING>')
            name_field = msg.get('name', msg.get('function', '<MISSING>'))
            tc_id = msg.get('tool_call_id', '<MISSING>')
            _debug(f"history[{i}] role={role} name={name_field} content_len={len(str(content)) if content else 0} tc_id={tc_id[:16] if tc_id and tc_id != '<MISSING>' else tc_id}", session_id)
        return {"messages": history, "count": len(history)}
    except requests.RequestException as e:
        _debug(f"API: history fetch error: {e}", session_id)
        raise HTTPException(500, f"Memory API error: {e}")


# =============================================================================
# Web UI
# =============================================================================

# Mount webui/ as /ui so the browser can reach index.html, style.css, etc.
WEBUI_PATH = os.path.join(os.path.dirname(__file__), "webui")
if os.path.isdir(WEBUI_PATH):
    # Custom StaticFiles with no-cache headers for webui
    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
    
    app.mount("/ui", NoCacheStaticFiles(directory=WEBUI_PATH, html=True), name="webui")

    @app.get("/", response_class=HTMLResponse)
    def root():
        """Redirect / → /ui/."""
        from starlette.responses import RedirectResponse
        return RedirectResponse("/ui/", status_code=302)


# =============================================================================
# Run
# =============================================================================


def run(host: str = None, port: int = None):
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host=host or get("server.host", "0.0.0.0"), port=port or get("server.port", 8080))


if __name__ == "__main__":
    run(host="0.0.0.0", port=8080)
