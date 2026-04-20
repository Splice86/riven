"""Riven API Server - simple HTTP API for riven_core.

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

app = FastAPI(title="Riven API", version="1.0.0")


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "riven": "riven_core"}


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
    
    The harness controls the agent loop: after each LLM turn, if tools were
    executed and context was rebuilt, it calls run_stream() again for the next turn.
    """
    import requests

    print(f"\n{'='*60}")
    print(f"[API] Received message: session={req.session_id}, shard={req.shard_name}, stream={req.stream}")
    print(f"[API] Message preview: {req.message[:100]}...")
    print(f"{'='*60}")

    shard = _load_shard(req.shard_name)
    llm = get_llm_config("primary")

    core = Core(shard=shard, llm=llm)
    print(f"[API] Core created: LLM={core._llm_url}, Memory={core._ctx._memory_url}")

    # Store user message to Memory API first
    memory_url = get("memory_api.url", "http://127.0.0.1:8030")
    print(f"[API] Storing user message to memory at {memory_url}")

    try:
        r = requests.post(
            f"{memory_url}/context",
            json={"role": "user", "content": req.message, "session": req.session_id},
        )
        print(f"[API] User message stored: status={r.status_code}")
    except requests.RequestException as e:
        print(f"[API] ERROR storing user message: {e}")
        raise HTTPException(500, f"Memory API error: {e}")

    if req.stream:
        async def generate():
            try:
                # Harness controls the loop - calls run_stream() for each LLM turn
                while True:
                    async for event in core.run_stream(req.session_id):
                        print(f"[API] Stream event: {list(event.keys())}")
                        
                        # Handle errors
                        if "error" in event:
                            print(f"[API] YIELD error: {event['error']}")
                            yield f"data: {json.dumps({'error': event['error']})}\n\n"
                            break

                        # Handle tool_call events
                        if "tool_call" in event:
                            tc = event["tool_call"]
                            args_str = json.dumps(tc["arguments"]) if tc["arguments"] else "{}"
                            token_val = f"<tool>{tc['name']}{args_str}</tool>"
                            print(f"[API] YIELD tool_call: {token_val}")
                            yield f"data: {json.dumps({'token': token_val})}\n\n"

                        # Handle thinking events
                        elif "thinking" in event:
                            content = event["thinking"]
                            if content and content.strip():
                                print(f"[API] YIELD thinking: {content[:50]}...")
                                yield f"data: {json.dumps({'thinking': content})}\n\n"

                        # Handle tool results
                        elif "tool_result" in event:
                            tr = event["tool_result"]
                            content = tr["content"] if not tr["error"] else f"ERROR: {tr['error']}"
                            token_val = f"<result>{content}</result>"
                            print(f"[API] YIELD tool_result: {token_val[:80]}...")
                            yield f"data: {json.dumps({'token': token_val})}\n\n"

                        # Regular token
                        elif "token" in event:
                            print(f"[API] YIELD token: {event['token'][:50]}...")
                            yield f"data: {json.dumps({'token': event['token']})}\n\n"

                        # Context rebuilt - loop back for next LLM turn
                        if event.get("context_rebuilt"):
                            print("[API] context_rebuilt - looping for next turn")
                            break

                        # Done
                        if event.get("done"):
                            print("[API] YIELD done")
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            return

            except Exception as e:
                print(f"[API] Exception in generate: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    # Non-streaming mode - harness controls the loop
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
                    break  # exit inner loop, continue outer while True

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
