"""Workflow module - stage-gated workflow management.

Provides workflow templates and tracking for structured task completion.
"""

from datetime import datetime, timezone
from typing import Optional

from modules import Module, CalledFn, ContextFn, _session_id
from .models import WorkflowState, StepStatus, Step, Stage
from .templates import WORKFLOWS, get_workflow, list_workflows
from . import storage


def _workflow_help() -> str:
    """Static help text describing the workflow module."""
    return """## Workflow Module — Use This for Every Task

**IMPORTANT: You should use the workflow module for almost every coding task.**

Structured workflows prevent you from losing track of what you're doing mid-task,
forgetting steps, skipping verification, or forgetting to commit. They turn a messy
multi-step task into a clean, tracked, accountable process.

### Quick Decision Tree

1. Does the user have a specific workflow in mind?
   → `start_workflow(coding)` or `start_workflow(quick)` or another named workflow

2. Is it a one-off task (new feature, bug fix, refactor, investigation)?
   → `guide_workflow(\"<task description\")` → `build_workflow(guide)`

3. Is it a code review or PR review?
   → `start_workflow(review)` or `guide_workflow(\"review\")`

4. Just exploring/understanding something?
   → `guide_workflow(\"explore/investigate\")`

### The Core Principle

**Never just start coding blindly.** Run `guide_workflow` on any non-trivial task,
read the guide, then `build_workflow` and use `workflow_status` + `mark_step_done`
as you go. It's not overhead — it's the difference between \"I think I'm done\" and \"I
know every step is complete.\"

### Complete Function Reference

**Discovery:**
- `list_workflows()` — See all available named workflows with their stage structures
- `show_workflow(workflow_id)` — Drill into one workflow to see its stages, steps, and gates

**Starting:**
- `start_workflow(workflow_id)` — Start a named template workflow directly (coding, quick, review, exploratory)
- `guide_workflow(task)` — For any task, analyze it and generate a tailored workflow guide. Returns a human-readable guide — print it for the user, then pass the same guide to build_workflow(). Task types:
  - Feature/feature request → feature guide (understand → plan → implement → verify → commit)
  - Bug/bug fix/error/crash → bugfix guide (reproduce → fix → verify → commit)
  - Refactor/clean up/optimize → refactor guide (assess → plan → refactor → verify → commit)
  - Review/audit/check → review guide (identify → analyze → fix → verify)
  - Explore/investigate/understand → exploratory guide (explore → iterate → conclude)
- `build_workflow(guide)` — Take a guide dict (from guide_workflow) and start tracking it.
  The guide must have: id, name, description, and stages [{name, description, gate_description?, steps: [{id, description}]}].

**Tracking:**
- `workflow_status()` — Full status snapshot: current stage, steps done/total, stage map, next hint
- `mark_step_done(step_id, notes?)` — Mark a step complete. If it finishes the stage, says "Stage complete! Ready to advance."
- `mark_step_in_progress(step_id)` — Mark a step as actively being worked on (→). Signals intent without claiming done.
- `skip_step(step_id, reason)` — Skip a step with a reason. Useful when a step is N/A for the task.
- `expand_implement_steps(steps)` — Template workflows only: replace the implement stage's steps with a custom list from your plan. Steps format: [{id, description}, ...]
- `add_step_note(step_id, note)` — Attach a note to any step. Great for decisions, links, or findings.

**Navigation:**
- `advance_stage()` — Move to the next stage. Only succeeds when ALL steps (done or skipped) are complete. Tells you how many remain if blocked.

**Cleanup:**
- `stop_workflow()` — Abandon the current workflow. Clears all state.

### Gates

Some stages have a \"gate\" — a condition that must be met before advancing.
Gates are described via `gate_description` and are shown when you enter the stage.
Common gates:
- \"Must be able to reliably reproduce\" (bugfix: reproduce stage)
- \"Tests pass and no regressions\" (verify stage)
- \"Plan must identify files and steps\" (plan stage)

Gates are enforced by `advance_stage()` — you cannot skip them.

### Example: Feature Request

User: \"add OAuth login to the backend\"

You respond:
```
guide_workflow("add OAuth login to the backend")
  → prints a structured guide

build_workflow(guide)
  → workflow is now active and tracking

workflow_status()
  → Stage: UNDERSTAND (0/3 steps)

mark_step_done("und_1", "Found auth.py and middleware/")
mark_step_done("und_2", "Need to use oauthlib + flask-oauthlib")
mark_step_done("und_3", "Will add /auth/oauth/ route")

advance_stage()
  → Advanced to: plan

expand_implement_steps([
  {"id": "plan_1", "description": "Add flask-oauthlib dependency"},
  {"id": "plan_2", "description": "Create OAuth client in auth.py"},
  {"id": "plan_3", "description": "Add /auth/oauth/ route"},
  {"id": "plan_4", "description": "Add session management"},
])

# ...implement each step...

advance_stage()
  → Advanced to: implement

mark_step_done("impl_1")
mark_step_done("impl_2")
mark_step_done("impl_3")
mark_step_done("impl_4")

advance_stage()
  → Advanced to: verify

# ...run tests, verify manually...

advance_stage()
  → Advanced to: commit

mark_step_done("com_1")
mark_step_done("com_2")

advance_stage()
  → Workflow complete!
```
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


def guide_workflow_cmd(task: str) -> str:
    """Analyze a task and produce a structured guide/checklist for completing it.

    The guide is tailored to the specific task type (feature, bug fix, refactor,
    investigation, etc.) and includes appropriate stages and steps.

    Args:
        task: Description of the task or goal to accomplish

    Returns:
        A structured guide with stages and steps, ready to pass to build_workflow()
    """
    import uuid

    # Infer workflow characteristics from task
    task_lower = task.lower()
    is_exploratory = any(k in task_lower for k in [
        "explore", "understand", "investigate", "analyze", "find out", "figure out"
    ])
    is_bug = any(k in task_lower for k in [
        "bug", "fix", "error", "crash", "broken", "fail", "issue", "wrong"
    ])
    is_refactor = any(k in task_lower for k in [
        "refactor", "clean up", "restructure", "improve", "optimize"
    ])
    is_review = any(k in task_lower for k in [
        "review", "audit", "check", "assess"
    ])

    if is_exploratory:
        guide = _exploratory_guide(task)
    elif is_bug:
        guide = _bugfix_guide(task)
    elif is_refactor:
        guide = _refactor_guide(task)
    elif is_review:
        guide = _review_guide(task)
    else:
        guide = _feature_guide(task)

    return guide


def _feature_guide(task: str) -> dict:
    """Build a feature/implementation guide."""
    import uuid
    wf_id = f"feature_{uuid.uuid4().hex[:6]}"
    return {
        "id": wf_id,
        "name": "Feature Implementation",
        "description": f"Build: {task}",
        "stages": [
            {
                "name": "understand",
                "description": "Understand the existing codebase and constraints",
                "steps": [
                    {"id": f"{wf_id}_und_1", "description": "Explore relevant directories and existing patterns"},
                    {"id": f"{wf_id}_und_2", "description": "Identify dependencies and interfaces"},
                    {"id": f"{wf_id}_und_3", "description": "Define boundaries of the change"},
                ],
            },
            {
                "name": "plan",
                "description": "Plan the implementation approach",
                "gate_description": "Plan must identify files and steps",
                "steps": [
                    {"id": f"{wf_id}_plan_1", "description": "Break into logical implementation steps"},
                    {"id": f"{wf_id}_plan_2", "description": "List files to modify/create"},
                ],
            },
            {
                "name": "implement",
                "description": "Implement each step of the plan",
                "steps": [
                    {"id": f"{wf_id}_impl_1", "description": "Implementation step 1"},
                ],
            },
            {
                "name": "verify",
                "description": "Verify the implementation works correctly",
                "gate_description": "Tests pass and no regressions",
                "steps": [
                    {"id": f"{wf_id}_ver_1", "description": "Run tests"},
                    {"id": f"{wf_id}_ver_2", "description": "Manual verification"},
                ],
            },
            {
                "name": "commit",
                "description": "Commit and push changes",
                "steps": [
                    {"id": f"{wf_id}_com_1", "description": "Stage and commit changes"},
                    {"id": f"{wf_id}_com_2", "description": "Push to remote"},
                ],
            },
        ],
    }


def _bugfix_guide(task: str) -> dict:
    """Build a bugfix guide."""
    import uuid
    wf_id = f"bugfix_{uuid.uuid4().hex[:6]}"
    return {
        "id": wf_id,
        "name": "Bug Fix",
        "description": f"Fix: {task}",
        "stages": [
            {
                "name": "reproduce",
                "description": "Reproduce the bug and understand its scope",
                "gate_description": "Must be able to reliably reproduce",
                "steps": [
                    {"id": f"{wf_id}_rep_1", "description": "Find the failing case or error"},
                    {"id": f"{wf_id}_rep_2", "description": "Isolate minimal reproduction"},
                    {"id": f"{wf_id}_rep_3", "description": "Identify root cause"},
                ],
            },
            {
                "name": "fix",
                "description": "Apply the fix",
                "steps": [
                    {"id": f"{wf_id}_fix_1", "description": "Implement the fix"},
                ],
            },
            {
                "name": "verify",
                "description": "Verify the fix",
                "gate_description": "Bug is resolved and no regressions",
                "steps": [
                    {"id": f"{wf_id}_ver_1", "description": "Confirm bug is fixed"},
                    {"id": f"{wf_id}_ver_2", "description": "Run full test suite"},
                ],
            },
            {
                "name": "commit",
                "description": "Commit and push",
                "steps": [
                    {"id": f"{wf_id}_com_1", "description": "Commit fix"},
                    {"id": f"{wf_id}_com_2", "description": "Push"},
                ],
            },
        ],
    }


def _refactor_guide(task: str) -> dict:
    """Build a refactor guide."""
    import uuid
    wf_id = f"refactor_{uuid.uuid4().hex[:6]}"
    return {
        "id": wf_id,
        "name": "Refactor",
        "description": f"Refactor: {task}",
        "stages": [
            {
                "name": "assess",
                "description": "Assess the code to be refactored",
                "steps": [
                    {"id": f"{wf_id}_ass_1", "description": "List files and understand structure"},
                    {"id": f"{wf_id}_ass_2", "description": "Identify what needs changing and why"},
                ],
            },
            {
                "name": "plan",
                "description": "Plan the refactor",
                "gate_description": "Must not change external behavior",
                "steps": [
                    {"id": f"{wf_id}_plan_1", "description": "Outline refactor steps"},
                    {"id": f"{wf_id}_plan_2", "description": "Identify tests to verify no behavior change"},
                ],
            },
            {
                "name": "refactor",
                "description": "Execute the refactor",
                "steps": [
                    {"id": f"{wf_id}_ref_1", "description": "Apply refactor changes"},
                ],
            },
            {
                "name": "verify",
                "description": "Verify refactor is safe",
                "gate_description": "All tests pass",
                "steps": [
                    {"id": f"{wf_id}_ver_1", "description": "Run full test suite"},
                ],
            },
            {
                "name": "commit",
                "description": "Commit",
                "steps": [
                    {"id": f"{wf_id}_com_1", "description": "Commit and push"},
                ],
            },
        ],
    }


def _review_guide(task: str) -> dict:
    """Build a code review guide."""
    import uuid
    wf_id = f"review_{uuid.uuid4().hex[:6]}"
    return {
        "id": wf_id,
        "name": "Code Review",
        "description": f"Review: {task}",
        "stages": [
            {
                "name": "identify",
                "description": "Identify what to review",
                "steps": [
                    {"id": f"{wf_id}_id_1", "description": "List files/changes to review"},
                ],
            },
            {
                "name": "analyze",
                "description": "Analyze for issues",
                "steps": [
                    {"id": f"{wf_id}_an_1", "description": "Check for bugs/logic errors"},
                    {"id": f"{wf_id}_an_2", "description": "Check for style/convention issues"},
                    {"id": f"{wf_id}_an_3", "description": "Check for performance concerns"},
                ],
            },
            {
                "name": "fix",
                "description": "Fix identified issues",
                "steps": [
                    {"id": f"{wf_id}_fix_1", "description": "Apply fixes"},
                ],
            },
            {
                "name": "verify",
                "description": "Verify fixes",
                "gate_description": "Tests pass",
                "steps": [
                    {"id": f"{wf_id}_ver_1", "description": "Run tests"},
                ],
            },
        ],
    }


def _exploratory_guide(task: str) -> dict:
    """Build an exploratory guide."""
    import uuid
    wf_id = f"explore_{uuid.uuid4().hex[:6]}"
    return {
        "id": wf_id,
        "name": "Exploratory Investigation",
        "description": f"Explore: {task}",
        "stages": [
            {
                "name": "explore",
                "description": "Explore and understand",
                "steps": [
                    {"id": f"{wf_id}_exp_1", "description": "Investigate the codebase"},
                    {"id": f"{wf_id}_exp_2", "description": "Document findings"},
                ],
            },
            {
                "name": "iterate",
                "description": "Iterate and experiment",
                "steps": [
                    {"id": f"{wf_id}_it_1", "description": "Make experimental changes"},
                    {"id": f"{wf_id}_it_2", "description": "Test hypotheses"},
                ],
            },
            {
                "name": "conclude",
                "description": "Draw conclusions",
                "steps": [
                    {"id": f"{wf_id}_con_1", "description": "Summarize findings"},
                    {"id": f"{wf_id}_con_2", "description": "Note follow-up items"},
                ],
            },
        ],
    }


def _format_guide(guide: dict) -> str:
    """Format a guide dict as a human-readable string."""
    lines = [
        f"## Workflow Guide: {guide['name']}",
        f"{guide['description']}",
        "",
        "### Stages",
        "",
    ]
    for i, stage in enumerate(guide.get("stages", []), 1):
        lines.append(f"{i}. **{stage['name']}** — {stage['description']}")
        if stage.get("gate_description"):
            lines.append(f"   Gate: {stage['gate_description']}")
        for j, step in enumerate(stage.get("steps", []), 1):
            lines.append(f"   {j}. {step['description']}")
        lines.append("")
    lines.append("---")
    lines.append(f"Guide ID: {guide['id']}")
    lines.append("Pass this guide to build_workflow() to begin tracking progress.")
    return "\n".join(lines)


def build_workflow_cmd(guide: dict) -> str:
    """Build and start a custom workflow from a guide produced by guide_workflow().

    The guide dict should contain:
    - id: unique workflow identifier
    - name: workflow name
    - description: what this workflow does
    - stages: list of stages, each with name, description, optional gate_description,
      and steps (list of {id, description} dicts)

    Args:
        guide: Workflow guide dict from guide_workflow()

    Returns:
        Confirmation message with workflow structure and first stage
    """
    import json

    # Validate guide structure
    if not isinstance(guide, dict):
        return f"Error: guide must be a dict, got {type(guide).__name__}"
    if 'stages' not in guide:
        return "Error: guide must have a 'stages' key"
    if not isinstance(guide['stages'], list):
        return "Error: guide['stages'] must be a list"

    workflow_id = guide.get('id', 'custom')
    stages = []

    for i, stage_data in enumerate(guide['stages']):
        if not isinstance(stage_data, dict):
            return f"Error: stage {i+1} must be a dict"
        if 'name' not in stage_data:
            return f"Error: stage {i+1} is missing a 'name'"

        steps = []
        for j, step_data in enumerate(stage_data.get('steps', [])):
            if not isinstance(step_data, dict):
                return f"Error: stage {i+1}, step {j+1} must be a dict"
            step_id = step_data.get('id', f"{stage_data['name']}_step_{j+1}")
            step_desc = step_data.get('description', f"Step {j+1}")
            steps.append(Step(id=step_id, description=step_desc))

        stages.append(Stage(
            name=stage_data['name'],
            description=stage_data.get('description', ''),
            gate_description=stage_data.get('gate_description'),
            steps=steps,
        ))

    # Check no active workflow
    state = storage.load_state()
    if state:
        return (
            f"Workflow '{state.workflow_id}' is already active. "
            f"Use stop_workflow() first, or continue with workflow_status()."
        )

    # Build state with dynamic stages
    state = WorkflowState(
        workflow_id=workflow_id,
        current_stage_index=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        dynamic_stages=stages,
    )

    # Initialize all step states
    for stage in stages:
        for step in stage.steps:
            state.step_states[step.id] = StepStatus.PENDING

    # Register custom workflow in template registry
    from .templates import WORKFLOWS
    from .models import Workflow
    WORKFLOWS[workflow_id] = Workflow(
        id=workflow_id,
        name=guide.get('name', workflow_id.replace('_', ' ').title()),
        description=guide.get('description', ''),
        category="custom",
        stages=stages,
        tags=["custom"],
    )

    storage.save_state(state)

    # Format response
    lines = [
        f"Workflow built: {guide.get('name', workflow_id)}",
        f"Description: {guide.get('description', '')}",
        "",
        f"Stages ({len(stages)}):",
    ]
    for i, stage in enumerate(stages, 1):
        lines.append(f"  {i}. {stage.name}")
        if stage.gate_description:
            lines.append(f"     Gate: {stage.gate_description}")
        for step in stage.steps:
            lines.append(f"     - {step.description}")

    lines.append("")
    lines.append("Use workflow_status() to track progress, mark_step_done() to complete steps, "
                 "and advance_stage() to move forward.")

    return "\n".join(lines)


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
                name="guide_workflow",
                description="Analyze a task and generate a structured workflow guide. "
                    "Returns a human-readable guide with stages and steps tailored to the task type "
                    "(feature, bug fix, refactor, review, exploratory). "
                    "Pass the result to build_workflow() to start tracking.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Description of the task or goal to accomplish",
                        },
                    },
                    "required": ["task"],
                },
                fn=guide_workflow_cmd,
            ),
            CalledFn(
                name="build_workflow",
                description="Build and start a custom workflow from a guide. "
                    "Use guide_workflow() first to generate a guide, then pass it here.",
                parameters={
                    "type": "object",
                    "properties": {
                        "guide": {
                            "type": "object",
                            "description": "Guide dict with id, name, description, and stages [{name, description, steps: [{id, description}]}]",
                        },
                    },
                    "required": ["guide"],
                },
                fn=build_workflow_cmd,
            ),
            CalledFn(
                name="expand_implement_steps",
                description="Add custom steps to the current stage of a template workflow (legacy — prefer build_workflow for custom workflows)",
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
