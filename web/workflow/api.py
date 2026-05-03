"""Workflow panel API — returns JSON snapshot of the active workflow."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from modules.workflow.db import load as load_row
from modules.workflow.models import StepStatus
from modules.workflow.templates import get_workflow

logger = logging.getLogger("web.workflow.api")

router = APIRouter(prefix="/api/v1/workflow", tags=["web.workflow.api"])


# ─── Response models ──────────────────────────────────────────────────────────

class StepInfo(BaseModel):
    id: str
    description: str
    status: str  # "PENDING" | "COMPLETE" | "IN_PROGRESS" | "SKIPPED"
    note: Optional[str] = None


class StageInfo(BaseModel):
    name: str
    description: str
    gate_description: Optional[str] = None
    status: str  # "past" | "current" | "future"
    steps: list[StepInfo]


class WorkflowStatusResponse(BaseModel):
    active: bool
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    current_stage_index: Optional[int] = None
    total_stages: Optional[int] = None
    current_stage: Optional[StageInfo] = None
    stages: Optional[list[StageInfo]] = None
    stage_progress: Optional[tuple[int, int]] = None  # (done, total) for current stage


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_stage_info(name: str, description: str, gate_description: Optional[str],
                      steps: list[dict], step_states: dict, step_notes: dict,
                      status: str) -> StageInfo:
    """Build a StageInfo from raw dict data."""
    step_infos = []
    for s in steps:
        sid = s["id"]
        step_infos.append(StepInfo(
            id=sid,
            description=s["description"],
            status=step_states.get(sid, StepStatus.PENDING.value),
            note=step_notes.get(sid),
        ))
    return StageInfo(
        name=name,
        description=description,
        gate_description=gate_description,
        status=status,
        steps=step_infos,
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status", response_model=WorkflowStatusResponse)
def workflow_status(session_id: str) -> WorkflowStatusResponse:
    """Return a JSON snapshot of the active workflow for the given session."""
    if not session_id:
        raise HTTPException(400, "session_id is required")

    row = load_row(session_id)
    if not row:
        return WorkflowStatusResponse(active=False)

    workflow_id: str = row["workflow_id"]
    current_stage_index: int = row.get("current_stage_index", 0)
    step_states: dict = row.get("step_states") or {}
    step_notes: dict = row.get("step_notes") or {}
    dynamic_stages: list = row.get("dynamic_stages") or []

    # Resolve stages: dynamic_stages take priority, otherwise use template
    if dynamic_stages:
        stages_raw = dynamic_stages
        workflow_name = workflow_id.replace("_", " ").title()
    else:
        wf = get_workflow(workflow_id)
        if not wf:
            return WorkflowStatusResponse(active=False)
        workflow_name = wf.name
        stages_raw = [
            {
                "name": s.name,
                "description": s.description,
                "gate_description": s.gate_description,
                "steps": [{"id": st.id, "description": st.description} for st in s.steps],
            }
            for s in wf.stages
        ]

    total_stages = len(stages_raw)

    # Build stage list with status markers
    stages_info = []
    for i, stage in enumerate(stages_raw):
        if i < current_stage_index:
            status = "past"
        elif i == current_stage_index:
            status = "current"
        else:
            status = "future"

        # Merge dynamic steps for current stage
        steps = stage.get("steps", [])
        if status == "current":
            dynamic_steps = row.get("dynamic_steps", {}).get(stage["name"], [])
            steps = steps + dynamic_steps

        stages_info.append(_build_stage_info(
            name=stage["name"],
            description=stage["description"],
            gate_description=stage.get("gate_description"),
            steps=steps,
            step_states=step_states,
            step_notes=step_notes,
            status=status,
        ))

    # Current stage progress
    current_stage_info = stages_info[current_stage_index] if current_stage_index < len(stages_info) else None
    if current_stage_info:
        done = sum(1 for s in current_stage_info.steps if s.status in ("COMPLETE", "SKIPPED"))
        stage_progress = (done, len(current_stage_info.steps))
    else:
        stage_progress = None

    return WorkflowStatusResponse(
        active=True,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        current_stage_index=current_stage_index,
        total_stages=total_stages,
        current_stage=current_stage_info,
        stages=stages_info,
        stage_progress=stage_progress,
    )


# ─── Route registration ───────────────────────────────────────────────────────

def register_routes(app):
    """Register workflow API routes with the main FastAPI app."""
    app.include_router(router)
    logger.info("[Workflow API] Registered routes under /api/v1/workflow")
