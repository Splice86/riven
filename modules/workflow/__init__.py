"""Workflow module - stage-gated workflow management.

Provides workflow templates and tracking for structured task completion.
"""

from datetime import datetime, timezone
from typing import Optional

from modules import Module, CalledFn, ContextFn, _session_id
from .models import WorkflowState, StepStatus, Step
from .templates import WORKFLOWS, get_workflow, list_workflows
from . import storage


def _workflow_help() -> str:
    """Static help text describing the workflow module."""
    return """## Workflow Module

Workflows provide stage-gated task management with structured progress tracking.
Useful for complex, multi-step tasks that need clear checkpoints.

Available Workflows: `coding`, `quick`, `review`, `exploratory`

Tools:
- **list_workflows()** — List all available workflow templates
- **show_workflow(workflow_id)** — Show the structure/stages of a specific workflow
- **start_workflow(workflow_id)** — Begin a workflow (coding, quick, review, exploratory)
- **workflow_status()** — Get current stage, step progress, and next actions
- **advance_stage()** — Move to the next stage (only when all steps complete)
- **mark_step_done(step_id, ?notes)** — Mark a step complete
- **mark_step_in_progress(step_id)** — Mark a step as in-progress
- **skip_step(step_id, reason)** — Skip a step with a reason
- **expand_implement_steps(steps)** — Add custom steps to the implement stage
- **add_step_note(step_id, note)** — Add a note to any step
- **stop_workflow()** — Stop and reset the active workflow
"""


def _workflow_context() -> str:
    """Generate workflow context for system prompt injection."""
    state = storage.load_state()
    
    if not state:
        return ""
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return ""
    
    current_stage = state.get_current_stage()
    if not current_stage:
        return ""
    
    progress = state.get_stage_progress()
    total_stages = len(workflow.stages)
    
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Workflow: {workflow.name}",
        f"Stage: {current_stage.name.upper()} ({state.current_stage_index + 1}/{total_stages})",
        f"Progress: {progress[0]}/{progress[1]} steps",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    
    # Stage overview
    lines.append("Stages:")
    for i, stage in enumerate(workflow.stages):
        if i < state.current_stage_index:
            icon = "✓"
        elif i == state.current_stage_index:
            icon = "→"
        else:
            icon = "○"
        lines.append(f"  {icon} {stage.name}")
    
    lines.append("")
    lines.append(f"Current: {current_stage.description}")
    
    if current_stage.gate_description:
        lines.append(f"Gate: {current_stage.gate_description}")
    
    # Steps for current stage
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])
    if all_steps:
        lines.append("")
        lines.append("Steps:")
        for step in all_steps:
            step_state = state.step_states.get(step.id, StepStatus.PENDING)
            note = state.step_notes.get(step.id, "")
            note_str = f" [{note}]" if note else ""
            lines.append(f"  {step_state.value} {step.description}{note_str}")
    
    # Next hint
    lines.append("")
    if state.can_advance():
        next_stage = workflow.stages[state.current_stage_index + 1] if state.current_stage_index < total_stages - 1 else None
        if next_stage:
            lines.append(f"Ready to advance to: {next_stage.name}")
        else:
            lines.append("Workflow complete!")
    else:
        lines.append(f"Complete remaining steps to advance")
    
    return "\n".join(lines)


def list_workflows_cmd() -> str:
    """List all available workflows.
    
    Returns a formatted list of workflow names and descriptions.
    """
    workflows = list_workflows()
    if not workflows:
        return "No workflows available."
    
    lines = ["Available Workflows:", ""]
    for wf in workflows:
        lines.append(f"  {wf.id}: {wf.name}")
        lines.append(f"    {wf.description}")
        lines.append(f"    Stages: {', '.join(s.name for s in wf.stages)}")
        lines.append("")
    
    return "\n".join(lines)


def show_workflow_cmd(workflow_id: str) -> str:
    """Show details of a specific workflow.
    
    Args:
        workflow_id: ID of the workflow to display
    """
    workflow = get_workflow(workflow_id)
    if not workflow:
        return f"Unknown workflow: {workflow_id}"
    
    lines = [
        f"## {workflow.name}",
        f"{workflow.description}",
        "",
        f"Category: {workflow.category}",
        f"Tags: {', '.join(workflow.tags)}",
        "",
        "Stages:",
    ]
    
    for i, stage in enumerate(workflow.stages):
        lines.append(f"  {i + 1}. {stage.name}")
        lines.append(f"     {stage.description}")
        if stage.gate_description:
            lines.append(f"     Gate: {stage.gate_description}")
        if stage.steps:
            lines.append(f"     Steps:")
            for step in stage.steps:
                lines.append(f"       - {step.description}")
    
    return "\n".join(lines)


def start_workflow_cmd(workflow_id: str) -> str:
    """Start a workflow by ID.
    
    Args:
        workflow_id: ID of the workflow to start (e.g., 'coding', 'quick')
    """
    workflow = get_workflow(workflow_id)
    if not workflow:
        return f"Unknown workflow: {workflow_id}. Use list_workflows() to see available options."
    
    state = storage.load_state()
    if state and state.workflow_id == workflow_id:
        return f"Workflow '{workflow_id}' is already active. Use workflow_status() to see progress."
    
    state = WorkflowState(
        workflow_id=workflow_id,
        current_stage_index=0,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    
    # Initialize all step states to PENDING
    for stage in workflow.stages:
        for step in stage.steps:
            state.step_states[step.id] = StepStatus.PENDING
    
    storage.save_state(state)
    
    first_stage = workflow.stages[0]
    lines = [
        f"Started workflow: {workflow.name}",
        f"Stage 1: {first_stage.name}",
        "",
        first_stage.description,
    ]
    
    if first_stage.gate_description:
        lines.append("")
        lines.append(f"Gate: {first_stage.gate_description}")
    
    return "\n".join(lines)


def workflow_status_cmd() -> str:
    """Get current workflow status.
    
    Returns the current stage, progress, and next steps.
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow. Use list_workflows() to see available options."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted. Use stop_workflow() to reset."
    
    current_stage = state.get_current_stage()
    progress = state.get_stage_progress()
    total_stages = len(workflow.stages)
    
    lines = [
        f"Workflow: {workflow.name}",
        f"Stage: {current_stage.name.upper()} ({state.current_stage_index + 1}/{total_stages})",
        f"Steps: {progress[0]}/{progress[1]} complete",
        "",
    ]
    
    # Stage progress
    lines.append("Stage Progress:")
    for i, stage in enumerate(workflow.stages):
        if i < state.current_stage_index:
            lines.append(f"  ✓ {stage.name}")
        elif i == state.current_stage_index:
            stage_progress = state.get_stage_progress()
            lines.append(f"  → {stage.name} ({stage_progress[0]}/{stage_progress[1]})")
        else:
            lines.append(f"  ○ {stage.name}")
    
    return "\n".join(lines)


def advance_stage_cmd() -> str:
    """Advance to the next stage if current stage is complete.
    
    Returns success message or error if gate not satisfied.
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    if not state.can_advance():
        completed, total = state.get_stage_progress()
        return f"Cannot advance: {total - completed} step(s) remaining in current stage."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted."
    
    prev_stage = workflow.stages[state.current_stage_index]
    
    if not state.advance():
        storage.clear_state()
        return f"Workflow complete! Finished: {prev_stage.name}"
    
    storage.save_state(state)
    
    new_stage = state.get_current_stage()
    lines = [
        f"Advanced to: {new_stage.name}",
        "",
        new_stage.description,
    ]
    
    if new_stage.gate_description:
        lines.append("")
        lines.append(f"Gate: {new_stage.gate_description}")
    
    # Show first step as IN_PROGRESS
    all_steps = new_stage.steps + state.dynamic_steps.get(new_stage.name, [])
    if all_steps:
        lines.append("")
        lines.append("First step:")
        lines.append(f"  → {all_steps[0].description}")
    
    return "\n".join(lines)


def mark_step_done_cmd(step_id: str, notes: str = "") -> str:
    """Mark a step as complete.
    
    Args:
        step_id: ID of the step to mark done
        notes: Optional notes about the step
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted."
    
    # Find the step
    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])
    
    found = False
    for step in all_steps:
        if step.id == step_id:
            found = True
            break
    
    if not found:
        return f"Unknown step: {step_id}. Check workflow_status() for valid step IDs."
    
    state.step_states[step_id] = StepStatus.COMPLETE
    if notes:
        state.step_notes[step_id] = notes
    
    storage.save_state(state)
    
    progress = state.get_stage_progress()
    
    if state.is_stage_complete():
        return f"Step '{step_id}' marked done. Stage complete! ({progress[0]}/{progress[1]} steps)\nReady to advance to next stage."
    
    return f"Step '{step_id}' marked done. ({progress[0]}/{progress[1]} steps)"


def mark_step_in_progress_cmd(step_id: str) -> str:
    """Mark a step as in progress.
    
    Args:
        step_id: ID of the step to mark in progress
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted."
    
    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])
    
    found = False
    for step in all_steps:
        if step.id == step_id:
            found = True
            break
    
    if not found:
        return f"Unknown step: {step_id}"
    
    state.step_states[step_id] = StepStatus.IN_PROGRESS
    storage.save_state(state)
    
    return f"Step '{step_id}' marked in progress."


def skip_step_cmd(step_id: str, reason: str) -> str:
    """Skip a step with a reason.
    
    Args:
        step_id: ID of the step to skip
        reason: Why the step is being skipped
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted."
    
    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])
    
    found = False
    for step in all_steps:
        if step.id == step_id:
            found = True
            break
    
    if not found:
        return f"Unknown step: {step_id}"
    
    state.step_states[step_id] = StepStatus.SKIPPED
    state.step_notes[step_id] = f"SKIPPED: {reason}"
    
    storage.save_state(state)
    
    return f"Step '{step_id}' skipped. Reason: {reason}"


def expand_implement_steps_cmd(steps: list[dict]) -> str:
    """Expand the implement stage with custom steps based on a plan.
    
    Args:
        steps: List of step dicts with 'id' and 'description' keys
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    workflow = get_workflow(state.workflow_id)
    if not workflow:
        return "Workflow data corrupted."
    
    current_stage = state.get_current_stage()
    if current_stage.name != "implement":
        return "Can only expand steps in the implement stage."
    
    if not steps:
        return "No steps provided."
    
    # Create Step objects from dict
    new_steps = []
    for i, s in enumerate(steps):
        step_id = s.get('id', f"impl_custom_{i+1}")
        desc = s.get('description', f"Step {i+1}")
        new_steps.append(Step(id=step_id, description=desc))
    
    # Replace or append to dynamic steps
    state.dynamic_steps["implement"] = new_steps
    
    # Initialize their states
    for step in new_steps:
        state.step_states[step.id] = StepStatus.PENDING
    
    storage.save_state(state)
    
    lines = [f"Added {len(new_steps)} steps to implement stage:", ""]
    for i, step in enumerate(new_steps, 1):
        lines.append(f"  {i}. {step.description}")
    
    return "\n".join(lines)


def add_step_note_cmd(step_id: str, note: str) -> str:
    """Add a note to a step.
    
    Args:
        step_id: ID of the step
        note: Note to add
    """
    state = storage.load_state()
    
    if not state:
        return "No active workflow."
    
    state.step_notes[step_id] = note
    storage.save_state(state)
    
    return f"Note added to step '{step_id}'."


def stop_workflow_cmd() -> str:
    """Stop the current workflow."""
    storage.clear_state()
    return "Workflow stopped and state cleared."


def get_module() -> Module:
    """Return the workflow module."""
    return Module(
        name="workflow",
        called_fns=[
            CalledFn(
                name="list_workflows",
                description="List all available workflows with their descriptions",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=list_workflows_cmd,
            ),
            CalledFn(
                name="show_workflow",
                description="Show detailed structure of a specific workflow",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to show (e.g., 'coding', 'quick', 'review')",
                        },
                    },
                    "required": ["workflow_id"],
                },
                fn=show_workflow_cmd,
            ),
            CalledFn(
                name="start_workflow",
                description="Start a workflow by ID. This begins tracking progress through stages.",
                parameters={
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "ID of the workflow to start (e.g., 'coding', 'quick', 'review')",
                        },
                    },
                    "required": ["workflow_id"],
                },
                fn=start_workflow_cmd,
            ),
            CalledFn(
                name="workflow_status",
                description="Get current workflow status including stage and step progress",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=workflow_status_cmd,
            ),
            CalledFn(
                name="advance_stage",
                description="Move to the next stage. Only works if all steps in current stage are complete.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=advance_stage_cmd,
            ),
            CalledFn(
                name="mark_step_done",
                description="Mark a step as complete",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step to mark done",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Optional notes about what was done",
                        },
                    },
                    "required": ["step_id"],
                },
                fn=mark_step_done_cmd,
            ),
            CalledFn(
                name="mark_step_in_progress",
                description="Mark a step as currently in progress",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step to mark in progress",
                        },
                    },
                    "required": ["step_id"],
                },
                fn=mark_step_in_progress_cmd,
            ),
            CalledFn(
                name="skip_step",
                description="Skip a step with a reason",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step to skip",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why this step is being skipped",
                        },
                    },
                    "required": ["step_id", "reason"],
                },
                fn=skip_step_cmd,
            ),
            CalledFn(
                name="expand_implement_steps",
                description="Expand the implement stage with steps from a plan",
                parameters={
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "description": "List of step objects with 'id' and 'description'",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["steps"],
                },
                fn=expand_implement_steps_cmd,
            ),
            CalledFn(
                name="add_step_note",
                description="Add a note to any step",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step",
                        },
                        "note": {
                            "type": "string",
                            "description": "Note to add",
                        },
                    },
                    "required": ["step_id", "note"],
                },
                fn=add_step_note_cmd,
            ),
            CalledFn(
                name="stop_workflow",
                description="Stop the current workflow and clear state",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=stop_workflow_cmd,
            ),
        ],
        context_fns=[
            ContextFn(tag="workflow_help", fn=_workflow_help, static=True),
            ContextFn(tag="workflow", fn=_workflow_context, static=False),
        ],
    )
