"""Web file editor module.

A lightweight, filesystem-driven live editor that watches files on disk
and pushes updates to connected browsers in real-time. No binding, no UIDs,
no session state — just file watching.

Components:
    config.py     — Editor settings (root dir, port, watch patterns)
    editor.py     — FileWatcher + EditorServer (WebSocket + file serving)
    api.py        — HTTP endpoints the file module calls (update/highlight/speak)
    static/
        editor.html — Browser UI (file tree + code editor)
"""

from __future__ import annotations

import logging

logger = logging.getLogger("web.editor")


def register_routes(app) -> None:
    """Register web editor routes with the FastAPI app."""
    from fastapi.staticfiles import StaticFiles
    import os

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static/editor", StaticFiles(directory=static_dir), name="web_editor_static")

    from . import editor, api
    app.include_router(editor.router, prefix="/web/editor")
    app.include_router(api.router, prefix="/web/editor/api")
    logger.info("[WebEditor] Routes registered under /web/editor")


__all__ = ["register_routes"]
