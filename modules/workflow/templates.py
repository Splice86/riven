"""Predefined workflow templates."""

from .models import Workflow, Stage, Step


def _coding_workflow() -> Workflow:
    return Workflow(
        id="coding",
        name="Coding Workflow",
        description="Full stage-gated coding workflow",
        category="coding",
        tags=["coding", "stage-gated", "full"],
        stages=[
            Stage(
                name="explore",
                description="Understand the codebase before starting",
                steps=[
                    Step(id="explore_1", description="List relevant directories and files"),
                    Step(id="explore_2", description="Read existing patterns and conventions"),
                    Step(id="explore_3", description="Identify constraints and dependencies"),
                ],
            ),
            Stage(
                name="intent",
                description="Define the goal clearly",
                gate_description="Intent statement must be specific and achievable",
                steps=[
                    Step(id="intent_1", description="Write clear goal statement"),
                    Step(id="intent_2", description="Define success criteria"),
                ],
            ),
            Stage(
                name="plan",
                description="Create a high-level implementation plan",
                gate_description="Plan has at least 1 step with file references",
                steps=[
                    Step(id="plan_1", description="Break into logical implementation steps"),
                    Step(id="plan_2", description="List files that will be modified"),
                ],
            ),
            Stage(
                name="implement",
                description="Execute the plan step by step",
                steps=[
                    Step(id="impl_1", description="Implementation step 1"),
                ],
            ),
            Stage(
                name="test",
                description="Ensure test coverage meets threshold",
                gate_description="Coverage must meet minimum threshold (default 80%)",
                steps=[
                    Step(id="test_1", description="Write tests for new functionality"),
                    Step(id="test_2", description="Check test coverage percentage"),
                ],
            ),
            Stage(
                name="verify",
                description="Run tests and fix any failures",
                gate_description="All tests must pass",
                steps=[
                    Step(id="verify_1", description="Run full test suite"),
                    Step(id="verify_2", description="Fix any test failures or bugs"),
                ],
            ),
            Stage(
                name="document",
                description="Document the changes",
                steps=[
                    Step(id="doc_1", description="Update or create design documentation"),
                ],
            ),
            Stage(
                name="review",
                description="Self-review before committing",
                steps=[
                    Step(id="review_1", description="Review git diff of changes"),
                    Step(id="review_2", description="Check for issues or improvements"),
                ],
            ),
            Stage(
                name="commit",
                description="Commit and push changes",
                steps=[
                    Step(id="commit_1", description="Stage relevant files"),
                    Step(id="commit_2", description="Write descriptive commit message"),
                    Step(id="commit_3", description="Push to remote repository"),
                ],
            ),
        ],
    )


def _quick_workflow() -> Workflow:
    return Workflow(
        id="quick",
        name="Quick Workflow",
        description="Minimal workflow for small, fast tasks",
        category="general",
        tags=["quick", "minimal"],
        stages=[
            Stage(
                name="intent",
                description="Define what to do",
                steps=[
                    Step(id="q_intent_1", description="Write clear goal statement"),
                ],
            ),
            Stage(
                name="implement",
                description="Make the change",
                steps=[
                    Step(id="q_impl_1", description="Implement the change"),
                ],
            ),
            Stage(
                name="commit",
                description="Commit and push",
                steps=[
                    Step(id="q_commit_1", description="Stage, commit, and push"),
                ],
            ),
        ],
    )


def _review_workflow() -> Workflow:
    return Workflow(
        id="review",
        name="Review Workflow",
        description="Code review and refactor workflow",
        category="review",
        tags=["review", "refactor"],
        stages=[
            Stage(
                name="identify",
                description="Identify what to review",
                steps=[
                    Step(id="rev_id_1", description="List files or changes to review"),
                ],
            ),
            Stage(
                name="analyze",
                description="Analyze for issues",
                steps=[
                    Step(id="rev_an_1", description="Check for bugs or logic errors"),
                    Step(id="rev_an_2", description="Check for style and convention issues"),
                    Step(id="rev_an_3", description="Check for performance concerns"),
                ],
            ),
            Stage(
                name="fix",
                description="Fix identified issues",
                steps=[
                    Step(id="rev_fix_1", description="Apply fixes for identified issues"),
                ],
            ),
            Stage(
                name="verify",
                description="Verify fixes",
                steps=[
                    Step(id="rev_ver_1", description="Run tests to verify fixes"),
                ],
            ),
        ],
    )


def _exploratory_workflow() -> Workflow:
    return Workflow(
        id="exploratory",
        name="Exploratory Workflow",
        description="Open-ended exploration without strict gates",
        category="general",
        tags=["exploratory", "flexible"],
        stages=[
            Stage(
                name="explore",
                description="Explore and understand",
                steps=[
                    Step(id="exp_1", description="Investigate the codebase"),
                    Step(id="exp_2", description="Document findings"),
                ],
            ),
            Stage(
                name="iterate",
                description="Iterate and experiment",
                steps=[
                    Step(id="exp_it_1", description="Make experimental changes"),
                    Step(id="exp_it_2", description="Test hypotheses"),
                ],
            ),
            Stage(
                name="conclude",
                description="Draw conclusions",
                steps=[
                    Step(id="exp_conc_1", description="Summarize findings"),
                    Step(id="exp_conc_2", description="Note any follow-up items"),
                ],
            ),
        ],
    )


# Registry of all available workflows
WORKFLOWS: dict[str, Workflow] = {
    "coding": _coding_workflow(),
    "quick": _quick_workflow(),
    "review": _review_workflow(),
    "exploratory": _exploratory_workflow(),
}


def get_workflow(workflow_id: str) -> Workflow | None:
    """Get a workflow by ID."""
    return WORKFLOWS.get(workflow_id)


def list_workflows(category: str | None = None) -> list[Workflow]:
    """List workflows, optionally filtered by category."""
    workflows = list(WORKFLOWS.values())
    if category:
        workflows = [w for w in workflows if w.category == category]
    return workflows
