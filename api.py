"""Riven API Server - HTTP API for core management and messaging."""

import os
import json
import uuid
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core_manager import get_manager, CoreManager


# ============== MODELS ==============

class SessionCreate(BaseModel):
    core_name: Optional[str] = None


class MessageSend(BaseModel):
    message: str
    stream: bool = False


# ============== API ==============

app = FastAPI(title="Riven API", version="1.0.0")
manager: CoreManager = get_manager()


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "riven": "codehammer"}


@app.get("/api/v1/cores")
def list_cores():
    """List available cores."""
    return {"cores": manager.list()}


@app.post("/api/v1/sessions")
def create_session(req: SessionCreate):
    """Create a new session."""
    result = manager.start(core_name=req.core_name)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message"))
    return result


@app.get("/api/v1/sessions")
def list_sessions():
    """List running sessions."""
    return {"sessions": manager.list_sessions()}


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    """Get session info."""
    if not manager.exists(session_id):
        raise HTTPException(404, "Session not found")
    return {
        "session_id": session_id,
        "core_name": manager.get_current(),
    }


@app.delete("/api/v1/sessions/{session_id}")
def delete_session(session_id: str):
    """Stop a session."""
    result = manager.stop(session_id)
    return result


@app.post("/api/v1/sessions/{session_id}/messages")
def send_message(session_id: str, req: MessageSend):
    """Send a message to a session.
    
    If stream=true, returns SSE stream.
    Otherwise returns direct response.
    """
    # Send message
    result = manager.send(session_id, req.message)
    
    if not result.get("ok"):
        raise HTTPException(400, result.get("error"))
    
    # If queued (threaded mode), wait for response
    if result.get("queued"):
        import time
        for _ in range(60):  # max 60 seconds
            time.sleep(0.5)
            messages = manager.receive(session_id)
            if messages:
                output = messages[0]
                break
        else:
            output = "Timeout waiting for response"
    else:
        # Simple mode - already have output
        output = result.get("output", "")
    
    if req.stream:
        # Stream response via SSE
        async def generate():
            words = output.split()
            for i, word in enumerate(words):
                yield f"data: {json.dumps({'token': word, 'done': i == len(words)-1})}\n\n"
                await asyncio.sleep(0.02)
        
        return StreamingResponse(generate(), media_type="text/event-stream")
    
    # Direct response
    return {"output": output}


@app.get("/api/v1/sessions/{session_id}/messages")
def poll_messages(session_id: str):
    """Poll for messages from a session."""
    messages = manager.receive(session_id)
    return {"messages": messages}


# ============== RUN ==============

def run(host: str = "0.0.0.0", port: int = 8080):
    """Run the API server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()