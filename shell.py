"""Simplified shell command execution for Linux."""

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Literal


@dataclass
class ShellResult:
    """Result of a shell command."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int | None
    execution_time: float
    error: str | None = None
    
    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"ShellResult({status} exit={self.exit_code} time={self.execution_time:.2f}s)"


class Shell:
    """Simplified shell command runner for Linux."""
    
    def __init__(
        self,
        timeout: int = 60,
        cwd: str | None = None,
    ):
        self.timeout = timeout
        self.cwd = cwd
    
    async def run(
        self,
        command: str,
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> ShellResult:
        """Run a shell command.
        
        Args:
            command: The command to execute.
            timeout: Optional timeout override (seconds).
            cwd: Optional working directory override.
            
        Returns:
            ShellResult with stdout, stderr, exit code, etc.
        """
        timeout = timeout or self.timeout
        cwd = cwd or self.cwd
        
        if not command or not command.strip():
            return ShellResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=None,
                execution_time=0.0,
                error="Command cannot be empty"
            )
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                # Start in new session on Linux for proper process group handling
                start_new_session=True,
            )
            
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
                exit_code = proc.returncode
                
            except asyncio.TimeoutError:
                # Kill the process group on timeout
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
                
                execution_time = asyncio.get_event_loop().time() - start_time
                return ShellResult(
                    success=False,
                    stdout="",
                    stderr="",
                    exit_code=None,
                    execution_time=execution_time,
                    error=f"Command timed out after {timeout}s"
                )
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            return ShellResult(
                success=exit_code == 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=exit_code,
                execution_time=execution_time,
            )
            
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            return ShellResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=None,
                execution_time=execution_time,
                error=str(e)
            )
    
    async def run_background(
        self,
        command: str,
        cwd: str | None = None,
    ) -> tuple[int, str]:
        """Run a command in background.
        
        Returns:
            Tuple of (pid, log_file_path)
        """
        import tempfile
        
        cwd = cwd or self.cwd
        
        # Create temp file for output
        log_file = tempfile.NamedTemporaryFile(
            mode="w",
            prefix="riven_bg_",
            suffix=".log",
            delete=False,
        )
        log_path = log_file.name
        log_file.close()
        
        # Start detached process
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,
        )
        
        return proc.pid, log_path


# Convenience function for quick use
async def run(
    command: str,
    timeout: int = 60,
    cwd: str | None = None,
) -> ShellResult:
    """Quick helper to run a shell command."""
    shell = Shell(timeout=timeout, cwd=cwd)
    return await shell.run(command, cwd=cwd)
