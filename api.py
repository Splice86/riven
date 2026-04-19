"""Riven API Server - simple HTTP API for temp_riven.

Session ID is passed directly to Memory API - no session state stored here.
The API is stateless; all conversation history lives in the Memory API.
"""

import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import Core
from config import get_llm_config, get


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

app = FastAPI(title="Riven API (temp_riven)", version="1.0.0")


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "riven": "temp_riven"}


@app.get("/api/v1/shards")
def list_shards():
    """List available shards."""
    shards_dir = os.path.join(os.path.dirname(__file__), "shards")
    shards = []

    if os.path.exists(shards_dir):
        import glob
        import yaml

        for filepath in glob.glob(os.path.join(shards_dir, "*.yaml")):
            with open(filepath) as f:
                data = yaml.safe_load(f)
                if data and "name" in data:
                    shards.append({
                        "name": data.get("name"),
                        "display_name": data.get("display_name", data["name"]),
                    })

    # Always include default shard
    if not any(s["name"] == "default" for s in shards):
        shards.append({"name": "default", "display_name": "Default"})

    return {"shards": shards}


def _load_shard(shard_name: str) -> dict:
    """Load shard config by name."""
    shards_dir = os.path.join(os.path.dirname(__file__), "shards")
    shard = None

    if os.path.exists(shards_dir):
        import glob
        import yaml

        for filepath in glob.glob(os.path.join(shards_dir, "*.yaml")):
            with open(filepath) as f:
                data = yaml.safe_load(f)
                if data and data.get("name") == shard_name:
                    shard = data
                    break

    if shard is None:
        # Build from config defaults
        shard = {
            "name": shard_name,
            "modules": get("modules", ["time", "shell"]),
            "system": get("system", "You are a helpful assistant."),
            "tool_timeout": get("tool_timeout", 60),
            "max_function_calls": get("max_function_calls", 20),
        }

    # Ensure memory_api is always set from config (even if shard file doesn't have it)
    shard.setdefault("memory_api", {
        "url": get("memory_api.url", "http://127.0.0.1:8030"),
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
    """
    import requests

    shard = _load_shard(req.shard_name)
    llm = get_llm_config("primary")

    core = Core(shard=shard, llm=llm)

    # Store user message to Memory API first
    memory_url = get("memory_api.url", "http://127.0.0.1:8030")

    try:
        requests.post(
            f"{memory_url}/context",
            json={"role": "user", "content": req.message, "session": req.session_id},
        )
    except requests.RequestException as e:
        raise HTTPException(500, f"Memory API error: {e}")

    if req.stream:
        async def generate():
            thinking_active = False
            thinking_content_emitted = False
            
            try:
                async for event in core.run_stream(req.session_id):
                    # Handle errors
                    if "error" in event:
                        if thinking_active and thinking_content_emitted:
                            yield f"data: {json.dumps({'token': '</think>'})}\n\n"
                        yield f"data: {json.dumps({'error': event['error']})}\n\n"
                        break
                    
                    # Handle thinking - only emit if there's actual content
                    if "thinking" in event:
                        content = event["thinking"]
                        if content and content.strip():
                            if not thinking_active:
                                yield f"data: {json.dumps({'token': '<think>'})}\n\n"
                                thinking_active = True
                                thinking_content_emitted = False
                            thinking_content_emitted = True
                            yield f"data: {json.dumps({'token': content})}\n\n"
                        # If content is empty/whitespace, don't emit anything
                        # and don't set thinking_active True yet
                    
                    # Handle tool calls - close thinking if we emitted content
                    elif "tool_call" in event:
                        if thinking_active and thinking_content_emitted:
                            yield f"data: {json.dumps({'token': '</think>'})}\n\n"
                        thinking_active = False
                        thinking_content_emitted = False
                        tc = event["tool_call"]
                        args_str = json.dumps(tc["arguments"]) if tc["arguments"] else "{}"
                        token_val = f"<tool>{tc['name']}{args_str}</tool>"
                        yield f"data: {json.dumps({'token': token_val})}\n\n"
                    
                    # Handle tool results
                    elif "tool_result" in event:
                        tr = event["tool_result"]
                        content = tr["content"] if not tr["error"] else f"ERROR: {tr['error']}"
                        token_val = f"<result>{content}</result>"
                        yield f"data: {json.dumps({'token': token_val})}\n\n"
                    
                    # Regular token - close thinking if active
                    elif "token" in event:
                        if thinking_active and thinking_content_emitted:
                            yield f"data: {json.dumps({'token': '</think>'})}\n\n"
                        thinking_active = False
                        thinking_content_emitted = False
                        yield f"data: {json.dumps({'token': event['token']})}\n\n"
                    
                    # Done
                    if event.get("done"):
                        if thinking_active and thinking_content_emitted:
                            yield f"data: {json.dumps({'token': '</think>'})}\n\n"
                        yield f"data: {json.dumps({'done': True})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming mode
    try:
        output = ""
        async for event in core.run_stream(req.session_id):
            if "error" in event:
                raise Exception(event["error"])
            if "token" in event:
                output += event["token"]

        return {"output": output}

    except Exception as e:
        raise HTTPException(500, str(e))


# =============================================================================
# Run
# =============================================================================

def run(host: str = "0.0.0.0", port: int = 8080):
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run(host="0.0.0.0", port=8080)
