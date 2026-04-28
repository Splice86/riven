"""Tests for the planning module."""

import pytest
import json
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPlanningImports:
    """Test that planning module has correct imports at module level."""

    def test_os_imported_at_module_level(self):
        """Verify os is imported at module level, not inside functions."""
        import modules.planning as planning_mod
        import inspect
        source = inspect.getsource(planning_mod)
        
        lines = source.split('\n')
        in_function = False
        function_indent = 0
        
        for line in lines:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            
            # Detect function definition
            if stripped.startswith('def ') or stripped.startswith('async def '):
                in_function = True
                function_indent = indent
            elif in_function and indent <= function_indent and stripped and not stripped.startswith('#'):
                in_function = False
            
            # import os inside functions is bad
            if in_function and 'import os' in stripped:
                pytest.fail(f"Found 'import os' inside function: {line}")


class TestGetGoalFiles:
    """Test _get_goal_files utility function."""

    def test_parses_valid_json_files_list(self):
        """Test parsing of valid JSON files list."""
        from modules.planning import _get_goal_files
        
        goal = {
            "properties": {
                "files": '["/path/to/file1.py", "/path/to/file2.py"]'
            }
        }
        files = _get_goal_files(goal)
        assert files == ["/path/to/file1.py", "/path/to/file2.py"]

    def test_parses_empty_files_list(self):
        """Test parsing of empty JSON files list."""
        from modules.planning import _get_goal_files
        
        goal = {"properties": {"files": "[]"}}
        files = _get_goal_files(goal)
        assert files == []

    def test_handles_missing_files_property(self):
        """Test handling when files property is missing."""
        from modules.planning import _get_goal_files
        
        goal = {"properties": {}}
        files = _get_goal_files(goal)
        assert files == []

    def test_handles_invalid_json(self):
        """Test handling of invalid JSON in files property."""
        from modules.planning import _get_goal_files
        
        goal = {"properties": {"files": "not valid json ["}}
        files = _get_goal_files(goal)
        assert files == []


class TestCreateGoal:
    """Test create_goal function."""

    @pytest.mark.asyncio
    async def test_create_goal_with_minimal_args(self, mock_memory_api, mock_config_singleton, planning_tmp_path):
        """Test creating a goal with just a title."""
        from modules import _session_id
        from modules.planning import create_goal

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path)):
            result = await create_goal(title="Test Goal")

        assert "1" in result
        assert "Test Goal" in result
        assert "priority: medium" in result

    @pytest.mark.asyncio
    async def test_create_goal_with_priority(self, mock_memory_api, mock_config_singleton, planning_tmp_path):
        """Test creating a goal with priority."""
        from modules import _session_id
        from modules.planning import create_goal
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path)):
            result = await create_goal(title="High Priority Task", priority="high")

        assert "high" in result
        assert "High Priority Task" in result

    @pytest.mark.asyncio
    async def test_create_goal_invalid_priority_defaults_to_medium(self, mock_memory_api, mock_config_singleton, planning_tmp_path):
        """Test that invalid priority defaults to medium."""
        from modules import _session_id
        from modules.planning import create_goal
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path)):
            result = await create_goal(title="Test", priority="invalid")

        assert "priority: medium" in result


class TestAddFileToGoal:
    """Test add_file_to_goal function."""

    @pytest.mark.asyncio
    async def test_add_file_to_existing_goal(self, mock_memory_api, mock_config_singleton, planning_tmp_path_with_goals):
        """Test adding a file to an existing goal."""
        from modules import _session_id
        from modules.planning import add_file_to_goal
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path_with_goals)):
            result = await add_file_to_goal(1, "/tmp/test_file.py")

        assert "test_file.py" in result
        assert "added" in result.lower()

    @pytest.mark.asyncio
    async def test_add_file_already_linked(self, mock_memory_api, mock_config_singleton, planning_tmp_path_with_goals):
        """Test adding a file that's already linked."""
        from modules import _session_id
        from modules.planning import add_file_to_goal
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        # Pre-populate the goal's files
        import yaml
        riven_dir = planning_tmp_path_with_goals / ".riven"
        with open(riven_dir / "plan.yaml", "w") as f:
            yaml.safe_dump({
                "goals": [{
                    "id": 1,
                    "title": "Existing Goal",
                    "description": "Test description",
                    "status": "open",
                    "priority": "medium",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "updated_at": "2025-01-01T00:00:00+00:00",
                    "properties": {"files": json.dumps(["/tmp/test_file.py"])},
                }]
            }, f)

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path_with_goals)):
            result = await add_file_to_goal(1, "/tmp/test_file.py")

        assert "already linked" in result.lower()


class TestUpdateGoalStatus:
    """Test update_goal_status function."""

    @pytest.mark.asyncio
    async def test_valid_status_update(self, mock_memory_api, mock_config_singleton, planning_tmp_path_with_goals):
        """Test updating goal status with valid status."""
        from modules import _session_id
        from modules.planning import update_goal_status
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path_with_goals)):
            result = await update_goal_status(1, "in_progress")

        assert "in_progress" in result

    @pytest.mark.asyncio
    async def test_invalid_status_returns_error(self, mock_memory_api, mock_config_singleton, planning_tmp_path_with_goals):
        """Test that invalid status returns error."""
        from modules import _session_id
        from modules.planning import update_goal_status
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path_with_goals)):
            result = await update_goal_status(1, "invalid_status")

        assert "Error:" in result
        assert "invalid_status" in result


class TestCloseGoal:
    """Test close_goal function."""

    @pytest.mark.asyncio
    async def test_close_goal_calls_update_status(self, mock_memory_api, mock_config_singleton, planning_tmp_path_with_goals):
        """Test that close_goal delegates to update_goal_status."""
        from modules import _session_id
        from modules.planning import close_goal
        from modules.project import get_project_root

        _session_id.set("test-session-123")

        with patch('modules.project.get_project_root', return_value=str(planning_tmp_path_with_goals)):
            result = await close_goal(1)

        assert "done" in result
