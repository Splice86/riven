"""Shell module for temp_riven - enhanced shell command execution.

Features:
- run: Execute shell command with timeout and proper process group handling
- cd: Change working directory
- get_cwd: Get current directory
- which: Find executable path
- run_background: Run command in background, returns PID and log file
- kill: Kill a background process by PID

Process group handling: On timeout, first sends SIGTERM, then SIGKILL after 5s.
CWD persists per session via session_id.

Session ID is automatically available via get_session_id().
"""

import asyncio
import os
import signal
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

from modules import CalledFn, ContextFn, Module
from config import get

# High-level debug flag
DEBUG_HANG = False

def _debug(step: str) -> None:
    """Print timestamped debug messages to trace execution flow."""
    if not DEBUG_HANG:
        return
    ts = time.time()
    print(f"[DEBUG {ts:.3f}] SHELL: {step}", flush=True)


DEFAULT_TIMEOUT = get('tool_timeout', 60.0)


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


def _shell_help() -> str:
    """Static tool documentation - does not change between calls."""
    from modules import _tool_ref
    return """## Shell (Help)

""" + _tool_ref('shell') + """

### Usage
Check exit codes. stderr is where the truth lives. Use run_background() for long-running tasks."""


def _shell_context() -> str:
    """Dynamic context - current working directory. Changes when cd is called."""
    cwd = os.getcwd()
    return f"""### Current Directory
`{cwd}`"""


async def run(
    command: str,
    timeout: float = None,
    cwd: str = None,
) -> str:
    _debug(f"run() ENTRY: command='{command}' timeout={timeout}")
    """Execute a shell command with proper process group handling.
    
    On timeout: sends SIGTERM, waits 5s, then SIGKILL if still running.
    
    Args:
        command: The shell command to execute
        timeout: Maximum execution time in seconds (default: 60)
        cwd: Optional working directory override
        
    Returns:
        Formatted output including stdout, stderr, and return code
    """
    timeout = timeout or DEFAULT_TIMEOUT
    
    if not command or not command.strip():
        return "[ERROR] Command cannot be empty"
    
    cwd = cwd or os.getcwd()
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        _debug(f"run(): creating subprocess shell")
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,  # Proper process group handling
        )
        _debug(f"run(): subprocess created, pid={proc.pid}")
        
        try:
            _debug(f"run(): calling proc.communicate() with timeout={timeout}s")
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            _debug(f"run(): proc.communicate() returned, bytes stdout={len(stdout_bytes) if stdout_bytes else 0}, stderr={len(stderr_bytes) if stderr_bytes else 0}")
            exit_code = proc.returncode
            execution_time = asyncio.get_event_loop().time() - start_time
            
            stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
            
        except asyncio.TimeoutError:
            _debug(f"run(): TIMEOUT after {timeout}s")
            # Kill process group on timeout
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    await proc.wait()
            except (ProcessLookupError, ValueError):
                pass  # Process already dead
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            result = ShellResult(
                success=False,
                stdout="",
                stderr="",
                exit_code=None,
                execution_time=execution_time,
                error=f"Command timed out after {timeout}s",
            )
            
            return _format_result(result)
    
    except Exception as e:
        _debug(f"run(): exception: {e}")
        execution_time = asyncio.get_event_loop().time() - start_time
        
        result = ShellResult(
            success=False,
            stdout="",
            stderr="",
            exit_code=None,
            execution_time=execution_time,
            error=f"{type(e).__name__}: {e}",
        )
        
        return _format_result(result)
    
    result = ShellResult(
        success=exit_code == 0,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        execution_time=execution_time,
    )
    
    _debug(f"run() EXIT: exit_code={exit_code}")
    return _format_result(result)


def _format_result(result: ShellResult) -> str:
    """Format ShellResult for output."""
    output = f"Exit code: {result.exit_code} (time: {result.execution_time:.2f}s)\n"
    
    if result.stdout:
        output += f"[stdout]\n{result.stdout}"
        if not result.stdout.endswith('\n'):
            output += '\n'
    
    if result.stderr:
        output += f"[stderr]\n{result.stderr}"
        if not result.stderr.endswith('\n'):
            output += '\n'
    
    if result.error:
        output += f"[error] {result.error}\n"
    
    if not result.stdout and not result.stderr and not result.error:
        output += "[no output]\n"
    
    return output


async def run_background(
    command: str,
    cwd: str = None,
) -> str:
    """Run a command in background, returns PID and log file path.
    
    Args:
        command: The shell command to execute
        cwd: Optional working directory
        
    Returns:
        PID and log file path for monitoring
    """
    _debug(f"run_background() ENTRY: command='{command}'")
    cwd = cwd or os.getcwd()
    
    # Create temp file for output
    log_file = tempfile.NamedTemporaryFile(
        mode='w',
        prefix='riven_bg_',
        suffix='.log',
        delete=False,
    )
    log_path = log_file.name
    log_file.close()
    
    try:
        _debug(f"run_background(): spawning Popen")
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=open(log_path, 'w'),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            start_new_session=True,
        )
        _debug(f"run_background(): spawned PID={proc.pid}")
        return f"Started background process: PID={proc.pid}\nLog file: {log_path}\nUse kill({proc.pid}) to stop it."
    
    except Exception as e:
        _debug(f"run_background(): EXCEPTION: {e}")
        return f"[ERROR] Failed to start background process: {e}"


async def kill(pid: int, sig: int = signal.SIGTERM) -> str:
    """Send a signal to a process.
    
    Args:
        pid: Process ID to kill
        sig: Signal number (default: SIGTERM=15). Use 9 for SIGKILL.
        
    Returns:
        Confirmation or error message
    """
    try:
        os.kill(pid, sig)
        sig_name = {15: "SIGTERM", 9: "SIGKILL"}.get(sig, str(sig))
        return f"Sent {sig_name} to process {pid}"
    except ProcessLookupError:
        return f"Process {pid} not found"
    except PermissionError:
        return f"Permission denied to kill process {pid}"
    except Exception as e:
        return f"[ERROR] {e}"


async def cd(path: str) -> str:
    """Change the current working directory.
    
    Args:
        path: Directory to change to (supports ~ expansion)
        
    Returns:
        Confirmation message with new directory
    """
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        return f"[ERROR] Directory does not exist: {path}"
    
    if not os.path.isdir(path):
        return f"[ERROR] Not a directory: {path}"
    
    try:
        os.chdir(path)
        return f"Changed directory to: {os.getcwd()}"
    except Exception as e:
        return f"[ERROR] Changing directory: {e}"


async def get_cwd() -> str:
    """Get the current working directory.
    
    Returns:
        Current working directory path
    """
    return os.getcwd()



async def which(program: str) -> str:
    """Find the full path to a program executable.
    
    Args:
        program: Name of the program to locate
        
    Returns:
        Full path to the program or error message
    """
    result = shutil.which(program)
    if result:
        return result
    return f"Program '{program}' not found"


def get_module():
    """Get the shell module."""
    return Module(
        name="shell",
        called_fns=[
            CalledFn(
                name="run",
                description="Execute a shell command with timeout and process group handling. On timeout: SIGTERM → 5s → SIGKILL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                        "timeout": {"type": "number", "description": "Maximum execution time in seconds (default: 60)"},
                        "cwd": {"type": "string", "description": "Optional working directory override"},
                    },
                    "required": ["command"],
                },
                fn=run,
            ),
            CalledFn(
                name="run_background",
                description="Run a command in background, returns PID and log file path.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The shell command to execute"},
                        "cwd": {"type": "string", "description": "Optional working directory"},
                    },
                    "required": ["command"],
                },
                fn=run_background,
            ),
            CalledFn(
                name="kill",
                description="Send a signal to a process. Default is SIGTERM (15). Use 9 for SIGKILL.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pid": {"type": "integer", "description": "Process ID to signal"},
                        "sig": {"type": "integer", "description": "Signal number (15=SIGTERM, 9=SIGKILL, default: 15)"},
                    },
                    "required": ["pid"],
                },
                fn=kill,
            ),
            CalledFn(
                name="cd",
                description="Change the current working directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory to change to (supports ~ expansion)"},
                    },
                    "required": ["path"],
                },
                fn=cd,
            ),
            CalledFn(
                name="get_cwd",
                description="Get the current working directory.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                fn=get_cwd,
            ),

            CalledFn(
                name="which",
                description="Find the full path to a program executable.",
                parameters={
                    "type": "object",
                    "properties": {
                        "program": {"type": "string", "description": "Name of the program to locate"},
                    },
                    "required": ["program"],
                },
                fn=which,
            ),
        ],
        context_fns=[
            ContextFn(tag="shell_help", fn=_shell_help),
            ContextFn(tag="shell", fn=_shell_context),
        ],
    )
