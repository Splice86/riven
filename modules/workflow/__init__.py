"""Workflow module - stage-gated workflow management.

Workflows are built from scratch per-task. The LLM creates the stages based on
the task and best practices baked into the help text.
"""

import uuid

from datetime import datetime, timezone

from modules import Module, CalledFn, ContextFn
from .models import WorkflowState, StepStatus, Step, Stage
from . import storage


# ---------------------------------------------------------------------------
# Help text — best practices injected into every prompt
# ---------------------------------------------------------------------------

def _workflow_help() -> str:
    return """## Workflow Module — Track Structured Task Progress

For any non-trivial coding task, use the workflow module to stay on track.
Structure your work into stages with specific steps. Never just start coding
blindly — build the workflow first.

### Best Practices

**Structure your work into stages.** Every task benefits from at least:
  - Understand → what exists, what the problem/goal is
  - Plan → specific steps, specific files, before you code
  - Implement → execute the plan
  - Verify → tests pass, manually tested
  - Commit → commit and push

**For bug fixes:** Reproduce reliably before touching any code. Don't fix
the symptom — find the root cause.

**For refactors:** Tests define the behavior contract. Every test must pass.
Refactor one focused change at a time, run tests after each.

**For code reviews:** Check logic errors, security, performance, style, and
whether the change actually solves the problem it claims to.

### Workflow Functions

**Starting:**
- `start_workflow(name, description)` — Start a new workflow for the current task.
  Provide a short name and describe what you're building or fixing.

- `add_stage(name, description, steps, gate?)` — Add a stage to the workflow.
  Add stages in order. Steps format: `[{"id": "step_1", "description": "..."}, ...]`.
  Gate format: `"gate condition"` (optional — shown when entering the stage).

**Tracking:**
- `workflow_status()` — Current stage, steps done/total, stage map, next hint.
- `mark_step_done(step_id, notes?)` — Mark a step complete. Always include notes.
- `mark_step_in_progress(step_id)` — Mark a step as being worked on.
- `skip_step(step_id, reason)` — Skip a step with a reason.
- `add_step_note(step_id, note)` — Attach a note to any step.

**Navigation:**
- `advance_stage()` — Move to the next stage. Only succeeds when all steps
  are done or skipped. This is the LLM's call — advance when the stage is done.

**Cleanup:**
- `stop_workflow()` — Abandon the current workflow and clear state.

### Example Flow

    start_workflow("add OAuth login", "Build Google OAuth2 login flow")
      → Workflow started with 0 stages

    add_stage("understand", "Understand the codebase",
      [{"id": "und_1", "description": "Explore auth module and middleware"},
       {"id": "und_2", "description": "Read existing login patterns"},
       {"id": "und_3", "description": "Check User model fields"}])

    add_stage("plan", "Plan the implementation",
      [{"id": "plan_1", "description": "Add google_id to User model"},
       {"id": "plan_2", "description": "Create OAuth client in auth/oauth.py"},
       {"id": "plan_3", "description": "Add /auth/google/login route"},
       {"id": "plan_4", "description": "Add /auth/google/callback route"},
       {"id": "plan_5", "description": "Add session management"}],
      "Plan must list every file to modify")

    # ... more stages as needed ...

    mark_step_done("und_1", "Found auth.py and middleware/. oauthlib is already installed.")
    mark_step_done("und_2", "Using flask-login pattern for sessions.")
    mark_step_done("und_3", "User model has email, will add google_id field.")

    advance_stage()
      → Advanced to: plan

    # BE SPECIFIC in your step descriptions.
    # 'Implement step 1' is not a useful step.
    # 'Add google_id VARCHAR field to User model' is.

    advance_stage()
      → Advanced to: implement

    mark_step_done("plan_1")
    mark_step_done("plan_2")
    ...

    advance_stage()
      → Advanced to: verify

    # ... run tests, manual check ...

    advance_stage()
      → Advanced to: commit

    mark_step_done("com_1", "git commit -m 'add Google OAuth2 login'")
    mark_step_done("com_2", "git push")

    advance_stage()
      → Workflow complete!
"""


def _workflow_context() -> str:
    """Generate workflow context for system prompt injection."""
    state = storage.load_state()

    if not state:
        return ""

    if state.dynamic_stages:
        workflow_name = state.workflow_id.replace("_", " ").title()
    else:
        from .templates import get_workflow
        workflow = get_workflow(state.workflow_id)
        if not workflow:
            return ""
        workflow_name = workflow.name

    current_stage = state.get_current_stage()
    if not current_stage:
        return ""

    progress = state.get_stage_progress()
    total_stages = len(state._get_stages())

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Workflow: {workflow_name}",
        f"Stage: {current_stage.name.upper()} ({state.current_stage_index + 1}/{total_stages})",
        f"Progress: {progress[0]}/{progress[1]} steps",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    lines.append("Stages:")
    for i, stage in enumerate(state._get_stages()):
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

    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])
    if all_steps:
        lines.append("")
        lines.append("Steps:")
        for step in all_steps:
            step_state = state.step_states.get(step.id, StepStatus.PENDING)
            note = state.step_notes.get(step.id, "")
            note_str = f" [{note}]" if note else ""
            lines.append(f"  {step_state.value} {step.description}{note_str}")

    lines.append("")
    if state.can_advance():
        next_stage_name = state._get_stages()[state.current_stage_index + 1].name \
            if state.current_stage_index < total_stages - 1 else None
        if next_stage_name:
            lines.append(f"Ready to advance to: {next_stage_name}")
        else:
            lines.append("Workflow complete!")
    else:
        lines.append(f"Complete remaining steps to advance")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command functions
# ---------------------------------------------------------------------------

def start_workflow_cmd(name: str, description: str) -> str:
    """Start a new workflow.

    Args:
        name: Short name for the workflow (e.g., "OAuth login", "Fix null crash")
        description: Brief description of what you're building or fixing
    """
    state = storage.load_state()
    if state:
        return (
            f"Workflow '{state.workflow_id}' is already active. "
            f"Use stop_workflow() first, or continue with workflow_status()."
        )

    wf_id = f"{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}"

    state = WorkflowState(
        workflow_id=wf_id,
        current_stage_index=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        dynamic_stages=[],
    )

    storage.save_state(state)

    lines = [
        f"Workflow started: {name}",
        f"Description: {description}",
        "",
        "No stages yet. Use add_stage() to add your first stage.",
    ]
    return "\n".join(lines)


def add_stage_cmd(
    name: str,
    description: str,
    steps: list[dict],
    gate_description: str | None = None,
) -> str:
    """Add a stage to the active workflow.

    Args:
        name: Short name for the stage (e.g., "understand", "plan", "implement")
        description: What this stage involves
        steps: List of step dicts: [{"id": "step_1", "description": "..."}, ...]
        gate_description: Optional gate — a condition that must be met before advancing
    """
    state = storage.load_state()
    if not state:
        return "No active workflow. Use start_workflow() first."

    stage_steps = []
    for i, s in enumerate(steps):
        step_id = s.get("id", f"{name}_{i+1}")
        step_desc = s.get("description", f"Step {i+1}")
        stage_steps.append(Step(id=step_id, description=step_desc))
        state.step_states[step_id] = StepStatus.PENDING

    stage = Stage(
        name=name,
        description=description,
        steps=stage_steps,
        gate_description=gate_description,
    )

    state.dynamic_stages.append(stage)
    storage.save_state(state)

    lines = [
        f"Stage added: {name}",
        f"Description: {description}",
    ]
    if gate_description:
        lines.append(f"Gate: {gate_description}")
    lines.append(f"Steps ({len(stage_steps)}):")
    for step in stage_steps:
        lines.append(f"  - {step.description}")

    total = len(state._get_stages())
    lines.append(f"\nWorkflow now has {total} stage(s).")
    return "\n".join(lines)


def workflow_status_cmd() -> str:
    """Get current workflow status."""
    state = storage.load_state()

    if not state:
        return "No active workflow. Use start_workflow(name, description) to begin."

    if not state.dynamic_stages:
        from .templates import get_workflow
        workflow = get_workflow(state.workflow_id)
        if not workflow:
            return "Workflow data corrupted. Use stop_workflow() to reset."
        name = workflow.name
        stages = workflow.stages
    else:
        name = state.workflow_id.replace("_", " ").title()
        stages = state.dynamic_stages

    current_stage = state.get_current_stage()
    progress = state.get_stage_progress()
    total_stages = len(stages)

    lines = [
        f"Workflow: {name}",
        f"Stage: {current_stage.name.upper()} ({state.current_stage_index + 1}/{total_stages})",
        f"Steps: {progress[0]}/{progress[1]} complete",
        "",
        "Stage Progress:",
    ]

    for i, stage in enumerate(stages):
        if i < state.current_stage_index:
            lines.append(f"  ✓ {stage.name}")
        elif i == state.current_stage_index:
            stage_progress = state.get_stage_progress()
            lines.append(f"  → {stage.name} ({stage_progress[0]}/{stage_progress[1]})")
        else:
            lines.append(f"  ○ {stage.name}")

    return "\n".join(lines)


def advance_stage_cmd() -> str:
    """Advance to the next stage if current stage is complete."""
    state = storage.load_state()

    if not state:
        return "No active workflow. Use start_workflow() first."

    if not state.can_advance():
        completed, total = state.get_stage_progress()
        return f"Cannot advance: {total - completed} step(s) remaining in current stage."

    prev_stage = state.get_current_stage()
    stages = state._get_stages()

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

    return "\n".join(lines)


def mark_step_done_cmd(step_id: str, notes: str = "") -> str:
    """Mark a step as complete."""
    state = storage.load_state()

    if not state:
        return "No active workflow."

    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])

    found = any(s.id == step_id for s in all_steps)
    if not found:
        return f"Unknown step: {step_id}. Check workflow_status() for valid step IDs."

    state.step_states[step_id] = StepStatus.COMPLETE
    if notes:
        state.step_notes[step_id] = notes

    storage.save_state(state)

    progress = state.get_stage_progress()

    if state.is_stage_complete():
        return (
            f"Step '{step_id}' marked done. Stage complete! ({progress[0]}/{progress[1]} steps)\n"
            "Ready to advance to next stage."
        )

    return f"Step '{step_id}' marked done. ({progress[0]}/{progress[1]} steps)"


def mark_step_in_progress_cmd(step_id: str) -> str:
    """Mark a step as in progress."""
    state = storage.load_state()

    if not state:
        return "No active workflow."

    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])

    found = any(s.id == step_id for s in all_steps)
    if not found:
        return f"Unknown step: {step_id}"

    state.step_states[step_id] = StepStatus.IN_PROGRESS
    storage.save_state(state)

    return f"Step '{step_id}' marked in progress."


def skip_step_cmd(step_id: str, reason: str) -> str:
    """Skip a step with a reason."""
    state = storage.load_state()

    if not state:
        return "No active workflow."

    current_stage = state.get_current_stage()
    all_steps = current_stage.steps + state.dynamic_steps.get(current_stage.name, [])

    found = any(s.id == step_id for s in all_steps)
    if not found:
        return f"Unknown step: {step_id}"

    state.step_states[step_id] = StepStatus.SKIPPED
    state.step_notes[step_id] = f"SKIPPED: {reason}"

    storage.save_state(state)

    return f"Step '{step_id}' skipped. Reason: {reason}"


def add_step_note_cmd(step_id: str, note: str) -> str:
    """Add a note to a step."""
    state = storage.load_state()

    if not state:
        return "No active workflow."

    state.step_notes[step_id] = note
    storage.save_state(state)

    return f"Note added to step '{step_id}'."


def stop_workflow_cmd() -> str:
    """Stop the current workflow and clear all state."""
    storage.clear_state()
    return "Workflow stopped and state cleared."


# ---------------------------------------------------------------------------
# Module registration
# ---------------------------------------------------------------------------

def get_module() -> Module:
    """Return the workflow module."""
    return Module(
        name="workflow",
        called_fns=[
            CalledFn(
                name="start_workflow",
                description="Start a new workflow for the current task. Provide a short name "
                    "and description. Use this at the start of any non-trivial task before "
                    "adding stages.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short name for the workflow (e.g., 'OAuth login', 'Fix null crash')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what you're building or fixing",
                        },
                    },
                    "required": ["name", "description"],
                },
                fn=start_workflow_cmd,
            ),
            CalledFn(
                name="add_stage",
                description="Add a stage to the active workflow. Add stages in execution order "
                    "(understand → plan → implement → verify → commit, or similar). "
                    "Each stage should have specific, named steps.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short stage name (e.g., 'understand', 'plan', 'implement')",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this stage involves",
                        },
                        "steps": {
                            "type": "array",
                            "description": "List of steps: [{\"id\": \"step_id\", \"description\": \"...\"}]",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                        "gate_description": {
                            "type": "string",
                            "description": "Optional gate: a condition that must be met before advancing to the next stage",
                        },
                    },
                    "required": ["name", "description", "steps"],
                },
                fn=add_stage_cmd,
            ),
            CalledFn(
                name="workflow_status",
                description="Get current workflow status: current stage, steps done/total, "
                    "full stage map, and next action hint.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=workflow_status_cmd,
            ),
            CalledFn(
                name="advance_stage",
                description="Move to the next stage. Only succeeds when all steps in the current "
                    "stage are done or skipped. This is the LLM's decision — advance when ready.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                fn=advance_stage_cmd,
            ),
            CalledFn(
                name="mark_step_done",
                description="Mark a step as complete. Always include notes describing what was done.",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step to mark done",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Description of what was done",
                        },
                    },
                    "required": ["step_id"],
                },
                fn=mark_step_done_cmd,
            ),
            CalledFn(
                name="mark_step_in_progress",
                description="Mark a step as currently being worked on.",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step",
                        },
                    },
                    "required": ["step_id"],
                },
                fn=mark_step_in_progress_cmd,
            ),
            CalledFn(
                name="skip_step",
                description="Skip a step with a reason. Use when a step is not applicable.",
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
                name="add_step_note",
                description="Attach a note to any step — decisions, links, findings.",
                parameters={
                    "type": "object",
                    "properties": {
                        "step_id": {
                            "type": "string",
                            "description": "ID of the step",
                        },
                        "note": {
                            "type": "string",
                            "description": "Note to attach",
                        },
                    },
                    "required": ["step_id", "note"],
                },
                fn=add_step_note_cmd,
            ),
            CalledFn(
                name="stop_workflow",
                description="Stop the current workflow and clear all state.",
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
