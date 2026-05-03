"""Riven API Server - simple HTTP API for riven_core.

Session ID is passed directly to Context DB - no session state stored here.
All conversation history lives in the Context DB (~/.riven/core.db).
"""

import asyncio
import glob
import importlib
import logging
import json
import os
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import Core
from config import get_llm_config, get

logger = logging.getLogger(__name__)

DEBUG_HANG = False

# ─── Active streams tracker ───────────────────────────────────────────────────
# Maps session_id → Core instance (so we can call .cancel() on abort)
_active_cores: dict[str, Core] = {}

def _debug(step: str, session_id: str = None) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = __import__("time").time()
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


def _load_shard(shard_name: str) -> dict:
    """Load shard config by name."""
    shard = None

    for filepath in _shard_files():
        with open(filepath) as f:
            data = yaml.safe_load(f)
            if data and data.get("name") == shard_name:
                shard = data
                break

    if shard is None:
        shard = {
            "name": shard_name,
            "modules": get("modules", ["time", "shell"]),
            "system": get("system", "You are a helpful assistant."),
            "tool_timeout": get("tool_timeout", 60),
            "max_function_calls": get("max_function_calls", 20),
        }


    if "llm_config" in shard:
        config_name = shard.pop("llm_config")
        shard["llm"] = get_llm_config(config_name)

    return shard


# =============================================================================
# API Models
# =============================================================================

class MessageRequest(BaseModel):
    message: str
    stream: bool = False
    session_id: str  # Client provides this
    shard_name: str = "default"


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(title="Riven API", version="1.0.0")


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "riven": "riven_core"}


@app.get("/api/v1/chat/abort")
def abort_stream(session_id: str):
    """Abort the active inference for a session.
    
    Sets the _cancelled flag on the running Core, which causes run_stream()
    to exit with an error event on the next yield point.
    """
    core = _active_cores.get(session_id)
    if core is None:
        raise HTTPException(409, "No active inference for this session")
    core.cancel()
    return {"ok": True, "session_id": session_id}


@app.get("/api/v1/chat/status")
def stream_status(session_id: str):
    """Check if a session has an active inference running."""
    active = session_id in _active_cores
    return {"session_id": session_id, "active": active}


# =============================================================================
# Messages API
# =============================================================================

@app.post("/api/v1/messages")
async def send_message(req: MessageRequest):
    """Send a message and get a response.
    
    - stream=true: SSE with tokens as they arrive
    - stream=false: JSON with full output when done
    
    Session ID is passed directly to Context DB for context retrieval.
    """
    from db import add

    shard = _load_shard(req.shard_name)
    llm = get_llm_config("primary")

    # Store user message to context DB first
    try:
        add(role="user", content=req.message, session=req.session_id)
    except Exception as e:
        raise HTTPException(500, f"Context database error: {e}")

    core = Core(shard=shard, llm=llm)
    _active_cores[req.session_id] = core

    if req.stream:
        async def generate():
            try:
                while True:
                    generator = core.run_stream(req.session_id)
                    try:
                        async for event in generator:
                            if "error" in event:
                                yield f"data: {json.dumps({'error': event['error']})}\n\n"
                                await generator.aclose()
                                return

                            if "tool_call" in event:
                                yield f"data: {json.dumps(event)}\n\n"

                            elif "thinking" in event:
                                content = event["thinking"]
                                if content and content.strip():
                                    yield f"data: {json.dumps({'thinking': content})}\n\n"

                            elif "tool_result" in event:
                                yield f"data: {json.dumps(event)}\n\n"

                            elif "token" in event:
                                yield f"data: {json.dumps({'token': event['token']})}\n\n"

                            if event.get("context_rebuilt"):
                                await generator.aclose()
                                break

                            if event.get("done"):
                                yield f"data: {json.dumps({'done': True})}\n\n"
                                await generator.aclose()
                                return
                    except GeneratorExit:
                        # Client disconnected — cancel and clean up
                        core.cancel()
                        return
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                _active_cores.pop(req.session_id, None)

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming
    try:
        output = ""
        while True:
            async for event in core.run_stream(req.session_id):
                if "error" in event:
                    raise Exception(event["error"])
                if "token" in event:
                    output += event["token"]
                if event.get("done"):
                    return {"output": output}
                if event.get("context_rebuilt"):
                    break
        return {"output": output}
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        _active_cores.pop(req.session_id, None)


# =============================================================================
# History API
# =============================================================================

@app.get("/api/v1/history")
def get_history(session_id: str, response: Response):
    """Get conversation history for a session from Context DB."""
    from db import get_history as _get_history

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    try:
        history = _get_history(session=session_id)
        return {"messages": history, "count": len(history)}
    except Exception as e:
        raise HTTPException(500, f"Context database error: {e}")


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


# Register module routes at startup
_registered_modules = _discover_modules()
for name in _registered_modules:
    _register_module_routes(app, name)


# Register web modules (live in web/, not modules/)
for web_mod in ["editor", "chat"]:
    try:
        mod = importlib.import_module(f"web.{web_mod}")
        if hasattr(mod, "register_routes"):
            mod.register_routes(app)
            logger.info(f"[API] Registered web.{web_mod} routes")
    except Exception as e:
        logger.warning(f"[API] Failed to register web.{web_mod}: {e}")


@app.get("/module/")
def list_modules():
    """List all modules that have registered API routes."""
    return {
        "modules": [{"name": name, "path": f"/module/{name}"} for name in _registered_modules],
        "count": len(_registered_modules),
    }


# =============================================================================
# Web UI (Chat)
# =============================================================================

CHAT_PATH = os.path.join(os.path.dirname(__file__), "web", "chat")
if os.path.isdir(CHAT_PATH):
    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
    
    app.mount("/ui", NoCacheStaticFiles(directory=CHAT_PATH, html=True), name="webui")

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
