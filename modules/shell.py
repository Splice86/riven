"""Shell module for riven."""

import asyncio
from dataclasses import dataclass
from typing import Literal
from shell import Shell as ShellBase


@dataclass
class ShellResult:
    """Result of a shell command."""
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    timeout: bool = False


class Shell:
    """Shell command executor."""
    
    def __init__(self, timeout: int = 60):
        self.timeout = timeout
    
    async def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int | None = None
    ) -> ShellResult:
        """Execute a shell command."""
        import subprocess
        
        timeout_val = timeout or self.timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_val
                )
                return ShellResult(
                    exit_code=proc.returncode,
                    stdout=stdout.decode().strip(),
                    stderr=stderr.decode().strip()
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ShellResult(
                    exit_code=1,
                    error=f"Command timed out after {timeout_val}s",
                    timeout=True
                )
        except Exception as e:
            return ShellResult(
                exit_code=1,
                error=str(e)
            )


async def run_shell_command(
    command: str,
    cwd: str | None = None,
    timeout: int | None = None
) -> str:
    """Execute a shell command.
    
    Args:
        command: The shell command to execute.
        cwd: Optional working directory.
        timeout: Optional timeout override in seconds.
        
    Returns:
        Command output with success status.
    """
    shell = Shell()
    result = await shell.run(command, cwd=cwd, timeout=timeout)
    
    output = f"Exit code: {result.exit_code}\n"
    if result.stdout:
        output += f"stdout: {result.stdout}\n"
    if result.stderr:
        output += f"stderr: {result.stderr}\n"
    if result.error:
        output += f"error: {result.error}\n"
    return output


def get_shell_module(timeout: int = 60):
    """Get the shell module.
    
    Args:
        timeout: Default timeout for shell commands.
        
    Returns:
        Shell Module instance
    """
    from modules import Module
    
    # Create the shell instance for this enrollment
    shell = Shell(timeout=timeout)
    
    async def run_shell(command: str, cwd: str | None = None, timeout: int | None = None) -> str:
        """Execute a shell command.
        
        Args:
            command: The shell command to execute.
            cwd: Optional working directory.
            timeout: Optional timeout override in seconds.
            
        Returns:
            Command output with success status.
        """
        result = await shell.run(command, cwd=cwd, timeout=timeout)
        
        output = f"Exit code: {result.exit_code}\n"
        if result.stdout:
            output += f"stdout: {result.stdout}\n"
        if result.stderr:
            output += f"stderr: {result.stderr}\n"
        if result.error:
            output += f"error: {result.error}\n"
        return output
    
    return Module(
        name="shell",
        enrollment=lambda: None,  # Shell setup - can add logging later
        functions={"run_shell_command": run_shell}
    )
