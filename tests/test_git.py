"""Tests for modules/file/git.py"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.file.git import (
    _git_status,
    _git_status_summary,
    _git_warning,
    _is_git_repo,
    _is_git_tracked,
    _run_git,
    _get_git_hash,
)


# =============================================================================
# _run_git()
# =============================================================================

class TestRunGit:
    """Test _run_git() - verify it silences errors."""

    def test_successful_git_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="some output", stderr=""
            )
            result = _run_git(["status"])
            assert result.returncode == 0
            assert result.stdout == "some output"

    def test_failed_git_command_silenced(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="not a git repo"
            )
            result = _run_git(["status"])
            # Should return the result without raising
            assert result.returncode == 128
            assert "not a git repo" in result.stderr


# =============================================================================
# _is_git_repo()
# =============================================================================

class TestIsGitRepo:
    """Test _is_git_repo() detection."""

    def test_inside_git_repo(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="true\n")

            assert _is_git_repo() is True

    def test_outside_git_repo(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="")

            assert _is_git_repo() is False

    def test_case_insensitive(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="TRUE\n")

            assert _is_git_repo() is True


# =============================================================================
# _is_git_tracked()
# =============================================================================

class TestIsGitTracked:
    """Test _is_git_tracked() file tracking detection."""

    def test_tracked_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/file.py"):
                with patch("os.path.relpath", return_value="file.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0, stdout="")
                        mock_toplevel.return_value = "/repo"

                        assert _is_git_tracked("/repo/file.py") is True

    def test_untracked_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/newfile.py"):
                with patch("os.path.relpath", return_value="newfile.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="")
                        mock_toplevel.return_value = "/repo"

                        assert _is_git_tracked("/repo/newfile.py") is False

    def test_no_git_repo(self):
        with patch("config._git_toplevel") as mock_toplevel:
            mock_toplevel.return_value = None

            assert _is_git_tracked("/some/path.py") is False

    def test_cross_device_path(self):
        """On cross-device paths, relpath raises ValueError — treat as untracked."""
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/mnt/file.py"):
                with patch("os.path.relpath", side_effect=ValueError("path on different device")):
                    mock_toplevel.return_value = "/mnt"

                    assert _is_git_tracked("/mnt/file.py") is False


# =============================================================================
# _get_git_hash()
# =============================================================================

class TestGetGitHash:
    """Test _get_git_hash() content-based hash retrieval."""

    def test_get_hash_for_tracked_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/file.py"):
                with patch("os.path.relpath", return_value="file.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0, stdout="abc123def\n")
                        mock_toplevel.return_value = "/repo"

                        result = _get_git_hash("/repo/file.py")
                        assert result == "abc123def"

    def test_hash_untracked_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/new.py"):
                with patch("os.path.relpath", return_value="new.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="")
                        mock_toplevel.return_value = "/repo"

                        assert _get_git_hash("/repo/new.py") is None

    def test_hash_no_git_repo(self):
        with patch("config._git_toplevel") as mock_toplevel:
            mock_toplevel.return_value = None

            assert _get_git_hash("/some/path.py") is None

    def test_hash_cross_device(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/mnt/file.py"):
                with patch("os.path.relpath", side_effect=ValueError("cross-device")):
                    mock_toplevel.return_value = "/mnt"

                    assert _get_git_hash("/mnt/file.py") is None


# =============================================================================
# _git_status()
# =============================================================================

class TestGitStatus:
    """Test _git_status() short status code."""

    def test_modified_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/file.py"):
                with patch("os.path.relpath", return_value="file.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0, stdout=" M file.py\n"
                        )
                        mock_toplevel.return_value = "/repo"

                        result = _git_status("/repo/file.py")
                        assert result == "M"

    def test_untracked_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/new.py"):
                with patch("os.path.relpath", return_value="new.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0, stdout="?? new.py\n"
                        )
                        mock_toplevel.return_value = "/repo"

                        result = _git_status("/repo/new.py")
                        assert result == "??"

    def test_added_file(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/new.py"):
                with patch("os.path.relpath", return_value="new.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(
                            returncode=0, stdout="A  new.py\n"
                        )
                        mock_toplevel.return_value = "/repo"

                        result = _git_status("/repo/new.py")
                        assert result == "A"

    def test_no_git_repo(self):
        with patch("config._git_toplevel") as mock_toplevel:
            mock_toplevel.return_value = None

            assert _git_status("/some/path.py") == ""

    def test_cross_device(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/mnt/file.py"):
                with patch("os.path.relpath", side_effect=ValueError("cross-device")):
                    mock_toplevel.return_value = "/mnt"

                    assert _git_status("/mnt/file.py") == ""

    def test_no_status_output(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.abspath", return_value="/repo/file.py"):
                with patch("os.path.relpath", return_value="file.py"):
                    with patch("modules.file.git._run_git") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0, stdout="\n\n")
                        mock_toplevel.return_value = "/repo"

                        assert _git_status("/repo/file.py") == ""


# =============================================================================
# _git_status_summary()
# =============================================================================

class TestGitStatusSummary:
    """Test _git_status_summary() one-line repo summary."""

    def test_clean_repo(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="\n\n\n", stderr="")

            assert _git_status_summary() == "clean"

    def test_with_changes(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=" M file.py\n?? new.py\n", stderr=""
            )

            assert _git_status_summary() == "2 change(s)"

    def test_not_a_git_repo(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="not a repo")

            assert _git_status_summary() == "not a git repo"

    def test_cwd_override(self):
        with patch("modules.file.git._run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=" M file.py\n", stderr="")

            _git_status_summary(cwd="/custom/path")

            # Verify cwd was passed
            call_args = mock_run.call_args
            assert call_args[1]["cwd"] == "/custom/path"


# =============================================================================
# _git_warning()
# =============================================================================

class TestGitWarning:
    """Test _git_warning() generates actionable messages."""

    def test_no_git_repo_at_all(self):
        with patch("modules.file.git._git_toplevel") as mock_toplevel:
            mock_toplevel.return_value = None

            result = _git_warning("test.py", "/some/path/test.py")

            assert "not inside a git repository" in result
            assert "git init" in result

    def test_file_not_tracked(self):
        with patch("config._git_toplevel") as mock_toplevel:
            with patch("os.path.basename", return_value="test.py"):
                mock_toplevel.return_value = "/repo"

                result = _git_warning("test.py", "/repo/test.py")

                assert "not tracked by git" in result
                assert "git add test.py" in result
