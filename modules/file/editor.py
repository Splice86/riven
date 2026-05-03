"""FileEditor class with all file operations.

Provides a clean interface for file manipulation with fuzzy matching,
atomic writes, AST-based code extraction, and memory integration.
"""

from __future__ import annotations

import ast
import difflib
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from .git import (
    _get_git_hash,
    _git_warning,
    _is_git_tracked,
)

try:
    from ..config import get as config_get
except ImportError:
    # Running as standalone module
    from config import get as config_get

from .code_parser import (
    CodeDefinition,
    _extract_code_definitions,
    _extract_definition_source,
    _find_definitions_by_name,
)
from .constants import (
    MEMORY_KEYWORD_PREFIX,
    make_open_file_keyword,
    match_open_file_keyword,
)
from .db import (
    set_open_file,
    get_open_files,
    delete_open_file,
    delete_open_file_by_path,
    delete_all_open_files,
    get_open_file_by_keyword,
)
from .memory import (
    format_file_history,
    get_file_history,
    hash_content,
    track_file_change,
    _count_tokens,
)
from config import RIVEN_DIR, find_project_root

# ─── Events (optional — graceful fallback if not running in Riven process) ────
try:
    from events import (acquire_lock, release_lock,
                        get_lock_state, is_browser_lock,
                        publish as _events_publish)
except ImportError:
    # Standalone use: no-op fallbacks
    async def _dummy_lock(*a, **k): yield  # type: ignore
    acquire_lock = lambda *a, **k: _dummy_lock(*a, **k)  # type: ignore
    release_lock = lambda *a, **k: None  # type: ignore
    get_lock_state = lambda *a, **k: None  # type: ignore
    is_browser_lock = lambda *a, **k: False  # type: ignore
    _events_publish = lambda *a, **k: None  # type: ignore
    _REL_PATH = None  # type hint only


class BrowserLockError(Exception):
    """Raised when Riven tries to edit a file that the browser has locked."""
    def __init__(self, path: str, holder: str):
        self.path = path
        self.holder = holder
        super().__init__(
            f"File is open in the browser editor ({holder}). "
            f"Close or save the file in the browser before editing it here."
        )


def _require_no_browser_lock(path: str) -> None:
    """Raise BrowserLockError if the file is locked by a browser editor.
    
    Called before every write operation. Riven will NOT wait for the lock —
    it fails immediately so the user knows to close the browser first.
    """
    lock = get_lock_state(path)
    if lock is not None and is_browser_lock(lock):
        raise BrowserLockError(path, lock.holder)


def _rel_path(abs_path: str) -> str:
    """Return a file path relative to the project root, or the absolute path if
    project root cannot be determined."""
    try:
        root = find_project_root()
        return os.path.relpath(abs_path, root)
    except Exception:
        return abs_path


def _is_riven_project(from_path: str | None = None) -> bool:
    """True if from_path or any parent has a .riven/ directory."""
    root = find_project_root(from_path)
    return root is not None and os.path.isdir(os.path.join(root, RIVEN_DIR))

logger = logging.getLogger(__name__)


def _warn_no_riven_project(abs_path: str) -> str | None:
    """Return a warning if abs_path is not inside a Riven project, else None."""
    if not _is_riven_project(abs_path):
        return (
            f"Not inside a Riven project — goals, plans, and project metadata are not available.\n"
            f"Working directory: {os.path.dirname(abs_path)}\n"
            f"File operations will still work, but goal tracking will be disabled."
        )
    return None


# =============================================================================
# Data Classes for Structured Responses
# =============================================================================

@dataclass
class EditResult:
    """Structured result for file edit operations."""
    success: bool
    path: str
    message: str
    changed: bool = False
    diff: str = ""
    line_start: int | None = None
    line_end: int | None = None
    similarity: float | None = None
    syntax_error: str | None = None

    def to_string(self) -> str:
        """Convert to user-friendly string."""
        if self.success:
            parts = [f"✅ {self.message}"]
            if self.line_start and self.line_end:
                parts.append(f"   Lines {self.line_start}-{self.line_end}")
            if self.similarity:
                parts.append(f"   Match: {self.similarity:.0%}")
            if self.diff:
                parts.append(f"\n{self.diff}")
            return "\n".join(parts)
        else:
            parts = [f"❌ {self.message}"]
            if self.similarity:
                parts.append(f"   Best match: {self.similarity:.0%}")
            if self.syntax_error:
                parts.append(f"   Syntax error: {self.syntax_error}")
            if self.diff:
                parts.append(f"\n{self.diff}")
            return "\n".join(parts)


@dataclass
class Replacement:
    """A single text replacement for batch operations."""
    old_str: str
    new_str: str


# =============================================================================
# Robustness Helpers
# =============================================================================

def _atomic_write(path: str, content: str) -> None:
    """Write content atomically using temp file + rename.

    Uses a temp file in the same directory to ensure atomicity on POSIX systems.
    """
    dir_path = os.path.dirname(path) or '.'
    fd, temp_path = tempfile.mkstemp(dir=dir_path, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _sanitize_content(content: str) -> str:
    """Sanitize content for UTF-8 encoding edge cases."""
    try:
        return content.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return content


def _file_type(path: str) -> str:
    """Get human-readable file type."""
    ext = Path(path).suffix.lower()
    type_map = {
        '.py': 'Python',
        '.js': 'JavaScript',
        '.ts': 'TypeScript',
        '.json': 'JSON',
        '.md': 'Markdown',
        '.txt': 'Text',
        '.html': 'HTML',
        '.css': 'CSS',
        '.yaml': 'YAML',
        '.yml': 'YAML',
        '.toml': 'TOML',
    }
    return type_map.get(ext, ext.lstrip('.') or 'File')


def _validate_python(content: str) -> tuple[bool, str | None]:
    """Validate Python syntax. Returns (is_valid, error_message)."""
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"


def _generate_diff(
    path: str,
    old_lines: list[str],
    new_lines: list[str],
    context_lines: int = 3
) -> str:
    """Generate unified diff between old and new content."""
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{Path(path).name}",
            tofile=f"b/{Path(path).name}",
            n=context_lines,
        )
    )


def _find_best_window(
    haystack_lines: list[str],
    needle: str,
    threshold: float = 0.95
) -> tuple[tuple[int, int, int, int | None] | None, float]:
    """Find line window with best Jaro-Winkler similarity to needle.
    
    Returns: (start_line, end_line, start_char, end_char | None, similarity)
    For multi-line needles, end_char is None.
    """
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    
    if win_size == 0:
        return None, 0.0

    import jellyfish  # lazily — avoids breaking module discovery when jellyfish isn't installed

    # First, try exact substring match
    haystack_text = "".join(haystack_lines)
    if needle in haystack_text:
        return _find_exact_span(haystack_lines, needle)
    
    # Fall back to fuzzy matching
    best_score = 0.0
    best_span = None
    
    for i in range(len(haystack_lines) - win_size + 1):
        window = "\n".join(haystack_lines[i:i + win_size])
        # Strip leading whitespace from each line and trailing newlines for comparison
        window_lines = [line.strip() for line in window.rstrip('\n').splitlines()]
        window_clean = "\n".join(window_lines)
        score = jellyfish.jaro_winkler_similarity(window_clean, needle)
        if score > best_score:
            best_score = score
            best_span = (i, i + win_size, 0, None)  # Fuzzy match doesn't know char offsets
    
    if best_score >= threshold:
        return best_span, best_score
    return None, best_score


def _find_exact_span(
    haystack_lines: list[str],
    needle: str
) -> tuple[tuple[int, int, int, int | None], float]:
    """Find line span for exact needle match. Returns 100% similarity.
    
    Also returns character offsets within first and last lines.
    """
    needle = needle.rstrip("\n")
    needle_lines = needle.splitlines()
    win_size = len(needle_lines)
    
    # Try to find the needle directly in the original lines
    # This is more accurate than rejoining and re-splitting
    haystack_text = "".join(haystack_lines)
    pos = haystack_text.find(needle)
    if pos == -1:
        return None, 0.0
    
    # Count characters before the position to determine line
    # Track cumulative position through each line
    char_count = 0
    start_line = 0
    char_offset = 0
    
    for i, line in enumerate(haystack_lines):
        line_len = len(line)
        if pos < char_count + line_len:
            # Found in this line
            start_line = i
            char_offset = pos - char_count
            break
        char_count += line_len
    
    end_line = start_line + win_size
    
    # Calculate end character offset (if needle is within single line)
    end_char_offset = None
    if win_size == 1:
        end_char_offset = char_offset + len(needle)
    
    return (start_line, end_line, char_offset, end_char_offset), 1.0

# =============================================================================
# FileEditor Class
# =============================================================================

class FileEditor:
    """Handles all file operations with consistent state management."""
    
    def __init__(self, session_id_func=None, db_module=None):
        """Initialize FileEditor.
        
        Args:
            session_id_func: Function that returns current session ID
            db_module: Ignored (kept for backward compat) — file module is self-contained
        """
        from modules import get_session_id
        self._get_session_id = session_id_func or get_session_id
        self._db_module = db_module  # kept for backward compat, not used

    # -------------------------------------------------------------------------
    # Open/Close Operations
    # -------------------------------------------------------------------------
    
    def _check_and_merge_open_range(
        self,
        session_id: str,
        abs_path: str,
        line_start: int,
        line_end: int | None,
    ) -> str | None:
        """Check if a file is already open and validate/merge the range.
        
        Returns:
            None   - no conflict, proceed normally
            str    - rejection or merge message (caller should return it)
        """
        filename = os.path.basename(abs_path)
        keyword = make_open_file_keyword(filename)
        records = get_open_files(session_id, keyword, limit=10)

        for rec in records:
            existing_path = rec.get("path", "")

            # Only check entries for this exact path
            if os.path.abspath(existing_path) != abs_path:
                continue

            existing_start = int(rec.get("line_start", 0) or 0)
            existing_end = rec.get("line_end")  # None = to end, int = specific

            # Normalize None end to infinity for comparison
            existing_end_inf = float('inf') if existing_end is None else existing_end
            new_end_inf = float('inf') if line_end is None else line_end

            # Case 1: new range is entirely inside existing range -> reject
            if existing_start <= line_start and new_end_inf <= existing_end_inf:
                return (
                    f"{filename} is already open with lines {existing_start}-"
                    f"{'end' if existing_end is None else existing_end}. "
                    f"That range fully covers lines {line_start}-"
                    f"{'end' if line_end is None else line_end}. "
                    f"Read the file from context — do NOT call open_file() again."
                )

            # Case 2: new range overlaps or extends existing range -> merge
            if not (existing_start > new_end_inf or line_start > existing_end_inf):
                merged_start = min(existing_start, line_start)
                merged_end = max(existing_end_inf, new_end_inf)
                merged_end_int = None if merged_end == float('inf') else int(merged_end)

                # Replace the existing entry with merged range
                delete_open_file(session_id, keyword)

                new_keyword = make_open_file_keyword(filename)
                set_open_file(
                    session_id, new_keyword, abs_path,
                    content=f"open: {filename} [{merged_start}-{'end' if merged_end_int is None else merged_end_int}]",
                    line_start=merged_start,
                    line_end=merged_end_int,
                )

                if merged_end_inf == float('inf'):
                    return (
                        f"{filename} is already open (lines {existing_start}-"
                        f"{'end' if existing_end is None else existing_end}). "
                        f"Range expanded to lines {merged_start}-end."
                    )
                return (
                    f"{filename} is already open (lines {existing_start}-"
                    f"{'end' if existing_end is None else existing_end}). "
                    f"Range expanded to lines {merged_start}-{int(merged_end_inf)}."
                )

        return None

    def _check_file_open(self, abs_path: str) -> str | None:
        """Verify a file is open in context before an edit operation.
        
        Uses the memory database (with session scope) to check for an open-file
        entry matching the given path. Can be disabled via
        config: file.context_required = false.
        
        Returns:
            None         - file is open (or guard disabled), proceed normally
            str (error)  - rejection message, caller should return it
        """
        if not config_get('file.context_required', True):
            return None  # guard disabled via config

        session_id = self._get_session_id()
        filename = os.path.basename(abs_path)
        keyword = make_open_file_keyword(filename)
        records = get_open_files(session_id, keyword, limit=10)

        for rec in records:
            existing_path = rec.get("path", "")
            if existing_path and os.path.abspath(existing_path) == os.path.abspath(abs_path):
                return None  # found a match — file is open
        
        return (
            f"[NOT IN CONTEXT] {filename} is not open. "
            f"Call open_file('{filename}') first to add it to context before editing."
        )

    async def open_file(self, path: str, line_start: int = None, line_end: int = None, allow_untracked: bool = False) -> str:
        """Open a file and add it to the file context.
        
        Fails with an actionable warning if the file is not git-tracked,
        because safe file editing (automatic rollback) requires git.
        Pass allow_untracked=True to override this gate (rollback protection
        will be disabled for this file).
        Rejects opening a range that is a subset of an already-open range.
        Merges or expands when a superset/partial overlap is requested.
        """
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        # Warn if not inside a Riven project (logged, not returned — don't interrupt the flow)
        project_warning = _warn_no_riven_project(abs_path)
        if project_warning:
            logger.warning(project_warning)
        
        # Gate: require git tracking for safe rollback
        if not _is_git_tracked(abs_path):
            if not allow_untracked:
                return (
                    f"⚠️  Cannot safely open {os.path.basename(path)} — not tracked by git.\n\n"
                    f"    Safe file editing (automatic rollback on validation failure) requires git.\n\n"
                    f"    To fix this, run:\n"
                    f"      git init && git add {os.path.basename(path)} && git commit -m 'initial'\n\n"
                    f"    Then open the file again.\n\n"
                    f"    Alternatively, open the file with allow_untracked=True to proceed anyway.\n"
                    f"    WARNING: rollback protection will be DISABLED for this file."
                )
            # Soft override: warn but PROCEED with opening — no early return
            logger.warning(
                f"Opening {os.path.basename(path)} WITHOUT git tracking "
                f"— rollback protection is DISABLED. "
                f"Initialize git to enable it: git init && git add {os.path.basename(path)} && git commit -m 'initial'"
            )
        
        filename = os.path.basename(abs_path)
        session_id = self._get_session_id()
        
        line_start = line_start if line_start is not None else 0
        line_end_str = str(line_end) if line_end is not None else "*"
        
        # Guard: reject subsets, merge/superset overlaps
        guard_result = self._check_and_merge_open_range(
            session_id, abs_path, line_start, line_end
        )
        if guard_result is not None:
            return guard_result

        # Unique keyword per file (prevents overwrites in set_open_file)
        memory_type = make_open_file_keyword(filename)

        if not set_open_file(
            session_id, memory_type, abs_path,
            content=f"open: {filename} [{line_start}-{line_end_str}]",
            line_start=line_start,
            line_end=line_end,
        ):
            return f"Error saving to memory"
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            total_lines = len(content.splitlines())
        except Exception:
            content = ""
            total_lines = "?"
        
        # Count tokens for the content that will be in context
        # (applying same 1200-line truncation as file_context())
        all_lines = content.split('\n')
        if line_end is None or line_end == "*":
            ranged_content = '\n'.join(all_lines[line_start:])
        else:
            ranged_content = '\n'.join(all_lines[line_start:line_end])
        
        MAX_LINES = 1200
        content_lines = ranged_content.split('\n')
        if len(content_lines) > MAX_LINES:
            ranged_content = '\n'.join(content_lines[:MAX_LINES])
        
        token_count = _count_tokens(ranged_content)
        
        file_type_str = _file_type(abs_path)
        line_info = ""
        if line_start > 0 or line_end is not None:
            line_info = f" (lines {line_start}-{line_end or 'end'})"
        
        large_warning = ""
        if total_lines != "?" and total_lines > 1000:
            large_warning = " [!LARGE FILE - consider using line_start/line_end to limit scope]"
        

        
        return f"Opened {filename} (~{token_count} tokens). File is now instantly visible in system context{line_info}{large_warning}"
    
    async def close_file(self, name: str, line_start: int = None, line_end: int = None) -> str:
        """Close a file from the file context.
        
        Args:
            name: Filename to close (can be full path or just filename — normalized automatically)
            line_start: Optional specific line range start (unused - kept for API compat)
            line_end: Optional specific line range end (unused - kept for API compat)
        """
        session_id = self._get_session_id()
        
        # Normalize name to absolute path, then extract filename for keyword lookup.
        # This ensures close_file(path) and open_file(path) use the same keyword
        # regardless of whether the path is passed as ./file.py, file.py, or /abs/path.py
        abs_path = os.path.abspath(os.path.expanduser(name))
        filename = os.path.basename(abs_path)
        keyword = make_open_file_keyword(filename)

        # Check if the file is actually open
        records = get_open_files(session_id, keyword, limit=100)
        if not any(r.get("path") == abs_path for r in records):
            return f"File {name} not in context (checked as {filename})"

        if delete_open_file(session_id, keyword):
            return f"Closed {name}"
        return f"File {name} not in context"
    
    async def close_all_files(self) -> str:
        """Close all files from the file context."""
        session_id = self._get_session_id()
        
        count = delete_all_open_files(session_id)
        if count > 0:
            return f"Closed {count} open file(s)"
        return "No open files to close"
    
    # -------------------------------------------------------------------------
    # Read Operations
    # -------------------------------------------------------------------------
    
    def read_file(self, path: str, line_start: int = None, line_end: int = None) -> str:
        """Read a file and return its content."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        try:
            with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
                if line_start is not None or line_end is not None:
                    lines = f.readlines()
                    start = line_start or 0
                    end = line_end or len(lines)
                    content = ''.join(lines[start:end])
                else:
                    content = f.read()
            return content
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
    
    async def file_info(self, path: str) -> str:
        """Get information about a file."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        stat = os.stat(abs_path)
        filename = os.path.basename(abs_path)
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        
        with open(abs_path, 'r', errors='replace') as f:
            content = f.read()
        line_count = len(content.splitlines())
        
        file_type_str = _file_type(abs_path)
        return f"{filename} ({file_type_str}): {line_count} lines, {size} bytes, modified {mtime}"
    
    # -------------------------------------------------------------------------
    # Edit Operations
    # -------------------------------------------------------------------------
    
        """Core replace logic. Returns (result_msg, start_line, end_line, new_content)."""
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            content = _sanitize_content(content)
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}", 0, 0, ""

        span, score = _find_best_window(lines, old, threshold=threshold)

        if not span:
            best_span, best_score = _find_best_window(lines, old, threshold=0.0)
            if best_span:
                start, end, _, _ = best_span
                matched_lines = lines[start:end]
                matched_text = ''.join(matched_lines).strip()
                return (
                    f"No match above {threshold:.0%} threshold. "
                    f"Best match ({best_score:.0%}) at lines {start+1}-{end}:\n"
                    f"{matched_text[:300]}",
                    0, 0, ""
                )
            return f"Text not found in {os.path.basename(abs_path)}.", 0, 0, ""

        start, end, char_start, char_end = span

        if char_end is not None:
            line = lines[start]
            before_part = line[:char_start]
            after_part = line[char_end:]
            new_line = before_part + new + after_part
            before_lines = lines[:start]
            after_lines = lines[end:]
            new_content = ''.join(before_lines + [new_line] + after_lines)
        else:
            before_lines = lines[:start]
            after_lines = lines[end:]
            new_content_lines = new.splitlines(keepends=True)
            if new_content_lines and not new_content_lines[-1].endswith('\n'):
                new_content_lines[-1] += '\n'
            new_content = ''.join(before_lines + new_content_lines + after_lines)

        if validate_syntax and abs_path.endswith('.py'):
            is_valid, syntax_error = _validate_python(new_content)
            if not is_valid:
                return f"Syntax validation failed: {syntax_error}", 0, 0, ""

        try:
            _atomic_write(abs_path, new_content)
        except Exception as e:
            return f"Error writing {abs_path}: {e}", 0, 0, ""

        diff = _generate_diff(abs_path, lines, new_content.splitlines(keepends=True))
        session_id = self._get_session_id()
        track_file_change(session_id, abs_path, "replace_text", diff)

        return f"✅ Replaced text at lines {start+1}-{end} ({score:.0%} match)\n{diff}", start + 1, end, new_content

    async def replace_text(
        self,
        path: str,
        old: str,
        new: str,
        threshold: float = 0.95,
        validate_syntax: bool = True
    ) -> str:
        """Replace text in a file using fuzzy matching."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)

        guard = self._check_file_open(abs_path)
        if guard is not None:
            return guard

        _warn_no_riven_project(abs_path)

        session_id = self._get_session_id()
        rel_path = _rel_path(abs_path)

        # Fail immediately if browser has this file open — don't wait
        _require_no_browser_lock(rel_path)

        async with acquire_lock(rel_path, session_id, timeout=30.0, context="replace_text"):
            result, start, end, new_content = await self._do_replace_text(
                abs_path, old, new, threshold, validate_syntax
            )

        if start > 0 and new_content:  # success
            _events_publish(
                "file_changed",
                path=rel_path,
                content=new_content,
                start=start,
                end=end,
                who=session_id,
            )

        return result
    
    async def batch_edit(
        self,
        path: str,
        replacements: list[Replacement],
        threshold: float = 0.95,
        validate_syntax: bool = True
    ) -> EditResult:
        """Apply multiple replacements in a single pass."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        # Warn if not inside a Riven project
        project_warning = _warn_no_riven_project(abs_path)
        if project_warning:
            logger.warning(project_warning)
        
        # Guard: file must be open in context
        guard = self._check_file_open(abs_path)
        if guard is not None:
            return EditResult(False, abs_path, guard)

        # Fail immediately if browser has this file open — don't wait
        _require_no_browser_lock(_rel_path(abs_path))

        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                original = f.read()
            content = _sanitize_content(original)
            original_lines = content.splitlines(keepends=True)
        except FileNotFoundError:
            return EditResult(False, abs_path, f"File not found: {abs_path}")
        except Exception as e:
            return EditResult(False, abs_path, f"Error reading file: {e}")
        
        final_content = content
        changes: list[tuple[int, int, float]] = []
        
        for rep in replacements:
            lines = final_content.splitlines()
            span, score = _find_best_window(lines, rep.old_str, threshold)
            
            if not span:
                return EditResult(
                    False, abs_path,
                    f"No match for: {rep.old_str[:50]}... (best: {score:.0%})",
                    similarity=score
                )
            
            start, end, char_start, char_end = span
            
            if char_end is not None:
                # Single-line replacement with character offsets
                lines_with_newlines = final_content.splitlines(keepends=True)
                line = lines_with_newlines[start]
                before_part = line[:char_start]
                after_part = line[char_end:]
                new_line = before_part + rep.new_str + after_part
                lines_with_newlines[start] = new_line
                final_content = ''.join(lines_with_newlines)
            else:
                # Multi-line replacement
                lines_list = final_content.splitlines()
                before = "\n".join(lines_list[:start])
                after = "\n".join(lines_list[end:])
                parts = []
                if before:
                    parts.append(before)
                parts.append(rep.new_str.rstrip('\n'))
                if after:
                    parts.append(after)
                final_content = "\n".join(parts)
            
            # Preserve trailing newline
            if original.endswith('\n') and not final_content.endswith('\n'):
                final_content += "\n"
            
            changes.append((start, end, score))
        
        # Validate syntax
        syntax_error = None
        if validate_syntax and abs_path.endswith('.py'):
            is_valid, syntax_error = _validate_python(final_content)
            if not is_valid:
                return EditResult(
                    False, abs_path,
                    f"Syntax validation failed",
                    similarity=changes[-1][2] if changes else 0.0,
                    syntax_error=syntax_error
                )
        
        session_id = self._get_session_id()
        diff = _generate_diff(abs_path, original_lines, final_content.splitlines(keepends=True))

        async with acquire_lock(_rel_path(abs_path), session_id, timeout=30.0, context=f"batch_edit({len(replacements)})") as _lock_info:
            try:
                _atomic_write(abs_path, final_content)
            except Exception as e:
                return EditResult(False, abs_path, f"Failed to write: {e}")
            track_file_change(session_id, abs_path, f"batch_edit({len(replacements)})", diff)

        _events_publish("file_changed", path=_rel_path(abs_path), content=final_content,
                        start=changes[0][0] + 1, end=changes[-1][1] + 1, who=session_id)

        return EditResult(
            True, abs_path,
            f"Applied {len(replacements)} replacement(s)",
            changed=True,
            diff=diff,
            line_start=changes[0][0] + 1 if changes else None,
            line_end=changes[-1][1] + 1 if changes else None,
            similarity=changes[-1][2] if changes else None
        )
    
    async def delete_snippet(self, path: str, snippet: str, threshold: float = 0.95) -> EditResult:
        """Remove a snippet from a file using fuzzy matching."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        # Guard: file must be open in context
        guard = self._check_file_open(abs_path)
        if guard is not None:
            return EditResult(False, abs_path, guard)

        # Fail immediately if browser has this file open — don't wait
        _require_no_browser_lock(_rel_path(abs_path))

        try:
            with open(abs_path, 'r') as f:
                original = f.read()
            original_lines = original.splitlines(keepends=True)
        except FileNotFoundError:
            return EditResult(False, abs_path, f"File not found: {abs_path}")
        except Exception as e:
            return EditResult(False, abs_path, f"Error reading file: {e}")
        
        # First try exact match
        if snippet in original:
            modified = original.replace(snippet, "", 1)
        else:
            # Try fuzzy matching
            lines = original.splitlines(keepends=True)
            span, score = _find_best_window(lines, snippet, threshold)
            if not span:
                return EditResult(False, abs_path, f"Snippet not found", similarity=score)
            
            start, end, char_start, char_end = span
            
            if char_end is not None:
                # Single-line deletion with character offsets
                line = lines[start]
                before_part = line[:char_start]
                after_part = line[char_end:]
                lines[start] = before_part + after_part
                modified = ''.join(lines)
            else:
                # Multi-line deletion
                lines_list = original.splitlines()
                before = "\n".join(lines_list[:start])
                after = "\n".join(lines_list[end:])
                modified = "\n".join([before, after])
            # Clean up double newlines
            modified = modified.replace('\n\n\n', '\n')
        
        session_id = self._get_session_id()
        rel_path = _rel_path(abs_path)
        diff = _generate_diff(abs_path, original_lines, modified.splitlines(keepends=True))

        async with acquire_lock(rel_path, session_id, timeout=30.0, context="delete_snippet") as _lock_info:
            try:
                _atomic_write(abs_path, modified)
            except Exception as e:
                return EditResult(False, abs_path, f"Failed to write: {e}")
            track_file_change(session_id, abs_path, "delete_snippet", diff)

        _events_publish("file_changed", path=rel_path, content=modified,
                        who=session_id)

        return EditResult(
            True, abs_path,
            f"Deleted snippet from file",
            changed=True,
            diff=diff
        )
    
    # -------------------------------------------------------------------------
    # Write Operations
    # -------------------------------------------------------------------------
    
    async def write_text(self, path: str, content: str, create_parent_dirs: bool = False) -> str:
        """Write content to a file."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        # Warn if not inside a Riven project
        project_warning = _warn_no_riven_project(abs_path)
        if project_warning:
            logger.warning(project_warning)
        
        # Guard: file must be open in context
        guard = self._check_file_open(abs_path)
        if guard is not None:
            return guard

        # Fail immediately if browser has this file open — don't wait
        _require_no_browser_lock(rel_path)

        if create_parent_dirs:
            parent = os.path.dirname(abs_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent)
        
        session_id = self._get_session_id()
        rel_path = _rel_path(abs_path)

        async with acquire_lock(rel_path, session_id, timeout=30.0, context="write_text") as _lock_info:
            try:
                _atomic_write(abs_path, content)
            except Exception as e:
                return f"Error writing {abs_path}: {e}"

        _events_publish("file_changed", path=rel_path, content=content, who=session_id)

        line_count = len(content.splitlines())
        return f"✅ Wrote {line_count} lines to {os.path.basename(abs_path)}"
    
    async def delete_file(self, path: str) -> EditResult:
        """Delete a file."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return EditResult(False, abs_path, f"File not found")
        
        if os.path.isdir(abs_path):
            return EditResult(False, abs_path, f"Path is a directory")
        
        session_id = self._get_session_id()
        rel_path = _rel_path(abs_path)

        # Fail immediately if browser has this file open — don't delete behind their back
        _require_no_browser_lock(rel_path)

        async with acquire_lock(rel_path, session_id, timeout=30.0, context="delete_file") as _lock_info:
            try:
                os.unlink(abs_path)
            except Exception as e:
                return EditResult(False, abs_path, f"Failed to delete: {e}")

        # Clean up open-file entry for this file
        filename = os.path.basename(abs_path)
        keyword = make_open_file_keyword(filename)
        delete_open_file(session_id, keyword)

        _events_publish("file_deleted", path=rel_path, who=session_id)

        return EditResult(True, abs_path, f"Deleted {filename}", changed=True)
    
    # -------------------------------------------------------------------------
    # Open Function (AST-based)
    # -------------------------------------------------------------------------
    
    async def open_function(
        self,
        path: str,
        name: str,
        include_docstring: bool = True,
        include_decorators: bool = True
    ) -> str:
        """Open a specific class or function by name."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        if not abs_path.endswith('.py'):
            return f"Error: open_function only works with Python files (.py), got: {abs_path}"
        
        filename = os.path.basename(abs_path)
        session_id = self._get_session_id()
        
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                source = f.read()
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        source = _sanitize_content(source)
        
        definitions = _extract_code_definitions(source)
        
        if not definitions:
            return f"Error: Could not parse {abs_path} as Python code"
        
        matches = _find_definitions_by_name(definitions, name)
        
        if not matches:
            available = [f"{d.type}: {d.qualified_name} (lines {d.line_start}-{d.line_end})" 
                         for d in definitions[:20]]
            if len(definitions) > 20:
                available.append(f"... and {len(definitions) - 20} more")
            return f"Error: No class or function named '{name}' found.\n\nAvailable definitions:\n" + "\n".join(available)
        
        defn = matches[0]
        source_lines = source.splitlines(keepends=True)
        if source_lines and not source_lines[-1].endswith('\n'):
            source_lines[-1] += '\n'
        
        lines = _extract_definition_source(defn, source_lines)
        source_code = '\n'.join(lines)
        
        type_emoji = "🏛️" if defn.type == "class" else "🧩" if defn.type in ("method", "async_method") else "⚡" if defn.type in ("async_function", "async_method") else "🔧"
        type_label = defn.type.replace("_", " ")
        
        parts = [f"{type_emoji} {defn.qualified_name} [{type_label}] lines {defn.line_start}-{defn.line_end} ({filename})"]
        
        if include_decorators and defn.decorators:
            for dec in defn.decorators:
                parts.append(f"  @{dec}")
        
        parts.append(f"  {defn.signature}")
        
        if include_docstring and defn.docstring:
            parts.append(f"\n  " + "\n  ".join(defn.docstring.split('\n')))
        
        parts.append(f"\n```python")
        parts.append(source_code)
        parts.append(f"```")
        
        if len(matches) > 1:
            other_matches = [m.qualified_name for m in matches[1:5] if m.qualified_name != defn.qualified_name]
            if other_matches:
                parts.append(f"\n[Also found: {', '.join(other_matches)}" + (" ..." if len(matches) > 5 else "]"))
        
        result = '\n'.join(parts)
        
        # Store in memory using unique keyword
        memory_type = make_open_file_keyword(filename)
        set_open_file(
            session_id, memory_type, abs_path,
            content=f"open: {filename} {defn.qualified_name} ({defn.type})",
            line_start=defn.line_start,
            line_end=defn.line_end,
        )
        
        return result
    
    # -------------------------------------------------------------------------
    # Preview/Diff Operations
    # -------------------------------------------------------------------------
    
    async def preview_replace(self, path: str, old: str, threshold: float = 0.95) -> str:
        """Preview where a replacement would match."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        span, score = _find_best_window(lines, old, threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, old, threshold=0.0)
            if best_span:
                start, end, _, _ = best_span
                matched_text = ''.join(lines[start:end]).strip()
                return (
                    f"No match above {threshold:.0%} threshold. "
                    f"Best match ({best_score:.0%}) at lines {start+1}-{end}:\n"
                    f"{matched_text[:300]}"
                )
            return f"Text not found in {os.path.basename(abs_path)}."
        
        start, end, _, _ = span
        matched_text = ''.join(lines[start:end]).strip()
        return f"Match at lines {start+1}-{end} (similarity {score:.0%}):\n{matched_text}"
    
    async def diff_text(
        self,
        path: str,
        old: str,
        new: str,
        threshold: float = 0.95
    ) -> str:
        """Show diff of a proposed replacement."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        span, score = _find_best_window(lines, old, threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, old, threshold=0.0)
            if best_span:
                start, end, _, _ = best_span
                matched_text = ''.join(lines[start:end]).rstrip()
                return (
                    f"Cannot diff — best match ({best_score:.0%}) is below {threshold:.0%} threshold.\n\n"
                    f"Best match at lines {start+1}-{end}:\n{matched_text[:300]}\n\n"
                    f"Try lowering threshold for this replacement."
                )
            return f"Cannot diff — text not found in {os.path.basename(abs_path)}."
        
        start, end, _, _ = span
        before = ''.join(lines[start:end]).rstrip()
        new_lines = new.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith('\n'):
            new_lines[-1] += '\n'
        after = ''.join(new_lines).rstrip()
        
        diff = _generate_diff(abs_path, before.splitlines(keepends=True), after.splitlines(keepends=True))
        
        return f"=== diff: {os.path.basename(abs_path)} lines {start+1}-{end} (match {score:.0%}) ===\n\n--- BEFORE ---:\n{before}\n\n--- AFTER ---:\n{after}\n\n--- UNIFIED DIFF ---:\n{diff}"
    
    # -------------------------------------------------------------------------
    # Utility Operations
    # -------------------------------------------------------------------------
    
    async def search_files(self, pattern: str, path: str = ".") -> str:
        """Search for pattern in files."""
        try:
            result = subprocess.run(
                ['grep', '-rn', pattern, path, '--include=*.py', '--include=*.js', '--include=*.ts'],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 100:
                    return f"Found {len(lines)} matches (showing first 100):\n" + '\n'.join(lines[:100])
                return f"Found {len(lines)} matches:\n{result.stdout}"
            elif result.returncode == 1:
                return f"No matches for '{pattern}'"
            else:
                return f"Search error: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "Search timed out"
        except Exception as e:
            return f"Search error: {e}"
    
    async def list_dir(self, path: str = ".") -> str:
        """List directory contents."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: Directory {abs_path} not found"
        
        if not os.path.isdir(abs_path):
            return f"Error: {abs_path} is not a directory"
        
        try:
            entries = os.listdir(abs_path)
            dirs = []
            files = []
            for entry in entries:
                if not entry.startswith('.'):
                    full_path = os.path.join(abs_path, entry)
                    if os.path.isdir(full_path):
                        dirs.append(f"📁 {entry}/")
                    else:
                        files.append(f"📄 {entry}")
            return '\n'.join(sorted(dirs) + sorted(files))
        except Exception as e:
            return f"Error listing {abs_path}: {e}"
    
    # -------------------------------------------------------------------------
    # Memory/Context Operations
    # -------------------------------------------------------------------------
    
    def list_open_files(self) -> str:
        """List all open files for current session."""
        session_id = self._get_session_id()
        memories = get_open_files(session_id)
        
        if not memories:
            return "No open files"
        
        lines = ["Open Files:"]
        for rec in memories:
            path = rec.get("path", "unknown")
            line_start = str(rec.get("line_start", 0) or 0)
            line_end = str(rec.get("line_end", "*"))
            filename = path.split("/")[-1] if "/" in path else path
            lines.append(f"  📄 {filename} (lines {line_start}-{line_end})")
        
        return '\n'.join(lines)
    
    def get_file_history_formatted(self) -> str:
        """Get formatted file change history."""
        session_id = self._get_session_id()
        memories = get_file_history(session_id)
        return format_file_history(memories)
    
    async def pwd(self) -> str:
        """Get current working directory."""
        return os.getcwd()
    
    async def chdir(self, path: str) -> str:
        """Change current working directory."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: Directory {abs_path} not found"
        
        if not os.path.isdir(abs_path):
            return f"Error: {abs_path} is not a directory"
        
        try:
            os.chdir(abs_path)
            return f"Changed directory to {abs_path}"
        except Exception as e:
            return f"Error changing directory: {e}"

    async def restore_from_git(self, path: str) -> str:
        """Restore a file to its last committed state in git."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)

        if not _is_git_tracked(abs_path):
            return f"Error: {path} is not tracked by git"

        try:
            result = subprocess.run(
                ["git", "checkout", "--", os.path.basename(abs_path)],
                cwd=os.path.dirname(abs_path),
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return f"Restored {os.path.basename(path)} to last git commit"
            return f"Error: {result.stderr}"
        except Exception as e:
            return f"Error restoring file: {e}"
