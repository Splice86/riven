"""Tests for modules/shell/__init__.py"""

import os
import signal
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.shell import (
    _format_result,
    _shell_context,
    _shell_help,
    cd,
    kill,
    run,
    run_background,
    which,
)


# =============================================================================
# _format_result
# =============================================================================

class TestFormatResult:
    """Format ShellResult for different output combinations."""

    def test_success_with_stdout(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=True, stdout="hello world\n", stderr="", exit_code=0, execution_time=0.5
        )
        output = _format_result(result)
        assert "Exit code: 0" in output
        assert "[stdout]" in output
        assert "hello world" in output
        assert "[stderr]" not in output
        assert "[error]" not in output

    def test_success_with_stderr(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=False, stdout="", stderr="something went wrong\n", exit_code=1, execution_time=0.1
        )
        output = _format_result(result)
        assert "Exit code: 1" in output
        assert "[stderr]" in output
        assert "something went wrong" in output

    def test_error_field(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=False, stdout="", stderr="", exit_code=None, execution_time=1.0,
            error="Command timed out after 60s",
        )
        output = _format_result(result)
        assert "[error] Command timed out" in output

    def test_no_output(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=True, stdout="", stderr="", exit_code=0, execution_time=0.0
        )
        output = _format_result(result)
        assert "[no output]" in output

    def test_stdout_without_trailing_newline(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=True, stdout="no newline", stderr="", exit_code=0, execution_time=0.1
        )
        output = _format_result(result)
        # Should append newline to stdout that lacks one
        assert "no newline" in output

    def test_stderr_without_trailing_newline(self):
        from modules.shell import ShellResult

        result = ShellResult(
            success=False, stdout="", stderr="error message", exit_code=1, execution_time=0.1
        )
        output = _format_result(result)
        assert "error message" in output


# =============================================================================
# run() - async shell execution
# =============================================================================

class TestRun:
    """Test run() function."""

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self):
        result = await run("")
        assert "[ERROR]" in result

    @pytest.mark.asyncio
    async def test_whitespace_only_command_rejected(self):
        result = await run("   \t  ")
        assert "[ERROR]" in result

    @pytest.mark.asyncio
    async def test_successful_command(self):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.communicate = AsyncMock(return_value=(b"hello", b""))
            mock_proc.returncode = 0
            mock_shell.return_value = mock_proc

            result = await run("echo hello")

            mock_shell.assert_called_once()
            assert "Exit code: 0" in result
            assert "hello" in result

    @pytest.mark.asyncio
    async def test_command_with_nonzero_exit(self):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_proc = MagicMock()
            mock_proc.pid = 999
            mock_proc.communicate = AsyncMock(return_value=(b"", b"file not found"))
            mock_proc.returncode = 2
            mock_shell.return_value = mock_proc

            result = await run("ls /nonexistent")

            assert "Exit code: 2" in result
            assert "file not found" in result

    @pytest.mark.asyncio
    async def test_command_with_cwd_override(self):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_proc = MagicMock()
            mock_proc.pid = 1
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_proc.returncode = 0
            mock_shell.return_value = mock_proc

            await run("pwd", cwd="/tmp")

            call_kwargs = mock_shell.call_args
            assert call_kwargs[1]["cwd"] == "/tmp"

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        with patch("asyncio.create_subprocess_shell") as mock_shell:
            mock_proc = MagicMock()
            mock_proc.pid = 888
            mock_proc.communicate = AsyncMock(side_effect=[
                pytest.importorskip("asyncio").TimeoutError
            ])
            mock_proc.wait = AsyncMock(return_value=MagicMock(returncode=-1))
            mock_shell.return_value = mock_proc

            with patch("os.killpg") as mock_kill:
                result = await run("sleep 999", timeout=0.5)

                assert "[error]" in result.lower() or "timeout" in result.lower()

    @pytest.mark.asyncio
    async def test_command_exception(self):
        with patch("asyncio.create_subprocess_shell", side_effect=OSError("boom!")):
            result = await run("something")
            assert "[error]" in result
            assert "OSError" in result or "boom" in result


# =============================================================================
# run_background()
# =============================================================================

class TestRunBackground:
    """Test run_background() function."""

    @pytest.mark.asyncio
    async def test_successful_start(self):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_popen.return_value = mock_proc

            result = await run_background("python script.py")

            assert "54321" in result
            assert "Started background process" in result

    @pytest.mark.asyncio
    async def test_failure_to_start(self):
        with patch("subprocess.Popen", side_effect=OSError("no permission")):
            result = await run_background("restricted-command")
            assert "[ERROR]" in result
            assert "no permission" in result

    @pytest.mark.asyncio
    async def test_with_cwd(self):
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 111
            mock_popen.return_value = mock_proc

            await run_background("python script.py", cwd="/home")

            call_kwargs = mock_popen.call_args
            assert call_kwargs[1]["cwd"] == "/home"


# =============================================================================
# kill()
# =============================================================================

class TestKill:
    """Test kill() function."""

    @pytest.mark.asyncio
    async def test_kill_sigterm_success(self):
        with patch("os.kill") as mock_kill:
            result = await kill(12345)
            assert "Sent SIGTERM to process 12345" in result
            mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_kill_sigkill(self):
        with patch("os.kill") as mock_kill:
            result = await kill(99999, sig=signal.SIGKILL)
            assert "Sent SIGKILL to process 99999" in result
            mock_kill.assert_called_once_with(99999, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_kill_process_not_found(self):
        with patch("os.kill", side_effect=ProcessLookupError()):
            result = await kill(12345)
            assert "not found" in result

    @pytest.mark.asyncio
    async def test_kill_permission_denied(self):
        with patch("os.kill", side_effect=PermissionError()):
            result = await kill(1)  # PID 1 is protected
            assert "Permission denied" in result

    @pytest.mark.asyncio
    async def test_kill_unexpected_error(self):
        with patch("os.kill", side_effect=RuntimeError("unexpected")):
            result = await kill(12345)
            assert "[ERROR]" in result


# =============================================================================
# cd()
# =============================================================================

class TestCd:
    """Test cd() function."""

    @pytest.mark.asyncio
    async def test_cd_nonexistent_directory(self):
        with patch("os.path.exists", return_value=False):
            result = await cd("/nonexistent/path")
            assert "[ERROR]" in result
            assert "does not exist" in result

    @pytest.mark.asyncio
    async def test_cd_not_a_directory(self):
        with patch("os.path.exists", return_value=True):
            with patch("os.path.isdir", return_value=False):
                result = await cd("/some/file.txt")
                assert "[ERROR]" in result
                assert "Not a directory" in result

    @pytest.mark.asyncio
    async def test_cd_success(self):
        with patch("os.path.exists", return_value=True):
            with patch("os.path.isdir", return_value=True):
                with patch("os.chdir"):
                    with patch("os.getcwd", return_value="/tmp"):
                        result = await cd("/tmp")
                        assert "Changed directory" in result
                        assert "/tmp" in result

    @pytest.mark.asyncio
    async def test_cd_expands_tilde(self):
        with patch("os.path.expanduser", return_value="/home/user"):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.isdir", return_value=True):
                    with patch("os.chdir"):
                        result = await cd("~")
                        assert "Changed directory" in result


# =============================================================================
# which()
# =============================================================================

class TestWhich:
    """Test which() function."""

    @pytest.mark.asyncio
    async def test_which_found(self):
        with patch("shutil.which", return_value="/usr/bin/python"):
            result = await which("python")
            assert result == "/usr/bin/python"

    @pytest.mark.asyncio
    async def test_which_not_found(self):
        with patch("shutil.which", return_value=None):
            result = await which("nonexistent_program_xyz")
            assert "not found" in result


# =============================================================================
# Context functions
# =============================================================================

class TestShellContextFunctions:
    """Test _shell_help and _shell_context."""

    def test_shell_help_returns_docs(self):
        result = _shell_help()
        assert "Shell" in result
        assert len(result) > 0

    def test_shell_context_returns_cwd(self):
        with patch("os.getcwd", return_value="/home/test"):
            result = _shell_context()
            assert "/home/test" in result
