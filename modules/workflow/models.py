"""Data models for the workflow system."""

from dataclasses import dataclass, field
from enum import Enum


class StepStatus(Enum):
    """Status of a workflow step."""
    PENDING = "○"
    IN_PROGRESS = "→"
    COMPLETE = "✓"
    SKIPPED = "⊘"


@dataclass
class Step:
    """A single step within a workflow stage."""
    id: str
    description: str


@dataclass
class Stage:
    """A stage in a workflow containing multiple steps."""
    name: str
    description: str
    steps: list[Step] = field(default_factory=list)
    gate_description: str | None = None


@dataclass
class Workflow:
    """A complete workflow with multiple stages."""
    id: str
    name: str
    description: str
    category: str
    stages: list[Stage] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class WorkflowState:
    """Current state of an active workflow session."""
    workflow_id: str
    current_stage_index: int = 0
    started_at: str | None = None
    step_states: dict[str, StepStatus] = field(default_factory=dict)
    step_notes: dict[str, str] = field(default_factory=dict)
    # Full custom stages for dynamically-built workflows
    dynamic_stages: list[Stage] = field(default_factory=list)
    # Legacy: per-stage steps (superseded by dynamic_stages, kept for compat)
    dynamic_steps: dict[str, list[Step]] = field(default_factory=dict)

    # -------------------------------------------------------------------------
    # Stage resolution — dynamic stages take priority over template stages
    # -------------------------------------------------------------------------

    def _get_stages(self) -> list[Stage]:
        """Return the custom stages for this workflow."""
        return self.dynamic_stages

    def get_current_stage(self) -> Stage | None:
        """Get the current stage object."""
        stages = self._get_stages()
        if self.current_stage_index >= len(stages):
            return None
        return stages[self.current_stage_index]

    def get_stage_progress(self) -> tuple[int, int]:
        """Get (completed_steps, total_steps) for current stage."""
        stage = self.get_current_stage()
        if not stage:
            return (0, 0)
        all_steps = stage.steps + self.dynamic_steps.get(stage.name, [])
        total = len(all_steps)
        completed = sum(
            1 for s in all_steps
            if self.step_states.get(s.id, StepStatus.PENDING) == StepStatus.COMPLETE
        )
        return (completed, total)

    def is_stage_complete(self) -> bool:
        """Check if all steps in current stage are complete or skipped."""
        stage = self.get_current_stage()
        if not stage:
            return True
        all_steps = stage.steps + self.dynamic_steps.get(stage.name, [])
        for step in all_steps:
            status = self.step_states.get(step.id, StepStatus.PENDING)
            if status not in (StepStatus.COMPLETE, StepStatus.SKIPPED):
                return False
        return True

    def can_advance(self) -> bool:
        """Check if we can advance to the next stage."""
        return self.is_stage_complete()

    def advance(self) -> bool:
        """Move to next stage. Returns True if advanced, False if at end."""
        stages = self._get_stages()
        if self.current_stage_index < len(stages) - 1:
            self.current_stage_index += 1
            return True
        return False

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            'workflow_id': self.workflow_id,
            'current_stage_index': self.current_stage_index,
            'started_at': self.started_at,
            'step_states': {k: v.value for k, v in self.step_states.items()},
            'step_notes': self.step_notes,
            'dynamic_stages': [
                {
                    'name': s.name,
                    'description': s.description,
                    'gate_description': s.gate_description,
                    'steps': [{'id': st.id, 'description': st.description} for st in s.steps],
                }
                for s in self.dynamic_stages
            ],
            # Legacy compat
            'dynamic_steps': {
                k: [{'id': s.id, 'description': s.description} for s in steps]
                for k, steps in self.dynamic_steps.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'WorkflowState':
        """Deserialize from dict."""
        state = cls(workflow_id=data['workflow_id'])
        state.current_stage_index = data.get('current_stage_index', 0)
        state.started_at = data.get('started_at')
        state.step_states = {
            k: StepStatus(v) for k, v in data.get('step_states', {}).items()
        }
        state.step_notes = data.get('step_notes', {})
        state.dynamic_stages = [
            Stage(
                name=ds['name'],
                description=ds['description'],
                gate_description=ds.get('gate_description'),
                steps=[Step(id=s['id'], description=s['description']) for s in ds.get('steps', [])],
            )
            for ds in data.get('dynamic_stages', [])
        ]
        state.dynamic_steps = {
            k: [Step(id=s['id'], description=s['description']) for s in steps]
            for k, steps in data.get('dynamic_steps', {}).items()
        }
        return state
