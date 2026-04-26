"""FileEditor class with all file operations.

Provides a clean interface for file manipulation with fuzzy matching,
atomic writes, AST-based code extraction, and memory integration.
"""

from __future__ import annotations

import ast
import difflib
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import jellyfish

from .git import (
    _get_git_hash,
    _git_warning,
    _is_git_tracked,
)

try:
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
        PROP_FILENAME,
        PROP_PATH,
        PROP_LINE_START,
        PROP_LINE_END,
    )
    from .memory import format_file_history, get_file_history, get_open_files, hash_content, track_file_change
except ImportError:
    # Running as standalone module
    from code_parser import (
        CodeDefinition,
        extract_code_definitions,
        extract_definition_source,
        find_definitions_by_name,
    )
    from constants import (
        MEMORY_KEYWORD_PREFIX,
        make_open_file_keyword,
        match_open_file_keyword,
        PROP_FILENAME,
        PROP_PATH,
        PROP_LINE_START,
        PROP_LINE_END,
    )
    from memory import format_file_history, get_file_history, get_open_files, hash_content, track_file_change


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
    """Write content atomically using temp file + rename."""
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

# =============================================================================
# FileEditor Class
# =============================================================================

class FileEditor:
    """Handles all file operations with consistent state management."""
    
    def __init__(self, session_id_func=None, memory_utils_module=None):
        """Initialize FileEditor.
        
        Args:
            session_id_func: Function that returns current session ID
            memory_utils_module: Module containing memory utilities
        """
        from modules import get_session_id
        self._get_session_id = session_id_func or get_session_id
        self._memory_utils = memory_utils_module
        
        # Lazy import helpers if not provided
        if memory_utils_module:
            self._set_memory = memory_utils_module._set_memory
            self._search_memories = memory_utils_module._search_memories
            self._delete_memory = memory_utils_module._delete_memory
        else:
            self._set_memory = None
            self._search_memories = None
            self._delete_memory = None
    
    def _get_set_memory(self):
        if self._set_memory is None:
            from modules.memory_utils import _set_memory
            self._set_memory = _set_memory
        return self._set_memory
    
    def _get_search_memories(self):
        if self._search_memories is None:
            from modules.memory_utils import _search_memories
            self._search_memories = _search_memories
        return self._search_memories
    
    def _get_delete_memory(self):
        if self._delete_memory is None:
            from modules.memory_utils import _delete_memory
            self._delete_memory = _delete_memory
        return self._delete_memory

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
        memories = self._get_search_memories()(session_id, keyword, limit=10)

        for mem in memories:
            props = mem.get("properties", {})
            existing_path = props.get(PROP_PATH, "")
            
            # Only check entries for this exact path
            if os.path.abspath(existing_path) != abs_path:
                continue

            existing_start = int(props.get(PROP_LINE_START, 0))
            existing_end_raw = props.get(PROP_LINE_END, "*")
            existing_end = None if existing_end_raw in ("*", "", None) else int(existing_end_raw)

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
                merged_end_str = "*" if merged_end == float('inf') else str(int(merged_end))
                existing_mem_id = mem.get("id")

                # Update the existing entry with merged range
                if existing_mem_id:
                    self._get_delete_memory()(existing_mem_id)

                new_keyword = make_open_file_keyword(filename)
                existing_git_hash = props.get("git_hash", "*")
                new_content = f"open: {filename} [{merged_start}-{merged_end_str}]"
                new_properties = {
                    PROP_FILENAME: filename,
                    PROP_PATH: abs_path,
                    PROP_LINE_START: str(merged_start),
                    PROP_LINE_END: merged_end_str,
                    "git_hash": existing_git_hash,
                }
                self._get_set_memory()(session_id, new_keyword, new_content, new_properties)

                if merged_end == float('inf'):
                    return (
                        f"{filename} is already open (lines {existing_start}-"
                        f"{'end' if existing_end is None else existing_end}). "
                        f"Range expanded to lines {merged_start}-end."
                    )
                return (
                    f"{filename} is already open (lines {existing_start}-"
                    f"{'end' if existing_end is None else existing_end}). "
                    f"Range expanded to lines {merged_start}-{int(merged_end)}."
                )

        return None

    async def open_file(self, path: str, line_start: int = None, line_end: int = None) -> str:
        """Open a file and add it to the file context.
        
        Fails with an actionable warning if the file is not git-tracked,
        because safe file editing (automatic rollback) requires git.
        Rejects opening a range that is a subset of an already-open range.
        Merges or expands when a superset/partial overlap is requested.
        """
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            return f"Error: File {abs_path} not found"
        
        # Gate: require git tracking for safe rollback
        if not _is_git_tracked(abs_path):
            return _git_warning(path, abs_path)
        
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
        
        # Capture git hash at open time for conflict detection
        git_hash = _get_git_hash(abs_path)
        
        # Unique keyword per file (prevents overwrites in _set_memory)
        # All data goes in properties
        memory_type = make_open_file_keyword(filename)
        content = f"open: {filename} [{line_start}-{line_end_str}]"
        properties = {
            PROP_FILENAME: filename,
            PROP_PATH: abs_path,
            PROP_LINE_START: str(line_start),
            PROP_LINE_END: line_end_str,
            "git_hash": git_hash or "*",
        }
        
        if not self._get_set_memory()(session_id, memory_type, content, properties):
            return f"Error saving to memory"
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            total_lines = len(content.splitlines())
        except Exception:
            total_lines = "?"
        
        file_type_str = _file_type(abs_path)
        line_info = ""
        if line_start > 0 or line_end is not None:
            line_info = f" (lines {line_start}-{line_end or 'end'})"
        
        large_warning = ""
        if total_lines != "?" and total_lines > 1000:
            large_warning = " [!LARGE FILE - consider using line_start/line_end to limit scope]"
        
        return f"Opened {filename} ({file_type_str}, {total_lines} lines){line_info}{large_warning}"
    
    async def close_file(self, name: str, line_start: int = None, line_end: int = None) -> str:
        """Close a file from the file context.
        
        Args:
            name: Filename to close
            line_start: Optional specific line range start (unused - kept for API compat)
            line_end: Optional specific line range end (unused - kept for API compat)
        """
        session_id = self._get_session_id()
        
        # Use the specific keyword for this file
        keyword = make_open_file_keyword(name)
        memories = self._get_search_memories()(session_id, keyword, limit=100)
        
        if not memories:
            return f"File {name} not in context"
        
        deleted_count = 0
        for mem in memories:
            mem_id = mem.get("id")
            if mem_id and self._get_delete_memory()(mem_id):
                deleted_count += 1
        
        if deleted_count > 0:
            return f"Closed {name} ({deleted_count} entry)"
        return f"File {name} not in context"
    
    async def close_all_files(self) -> str:
        """Close all files from the file context."""
        session_id = self._get_session_id()
        
        # Search using property pattern (keyword doesn't support wildcards)
        query = f"p:{PROP_FILENAME}=*"
        memories = self._get_search_memories()(session_id, query, limit=1000)
        
        if not memories:
            return "No open files to close"
        
        count = 0
        for mem in memories:
            mem_id = mem.get("id")
            if mem_id and self._get_delete_memory()(mem_id):
                count += 1
        
        return f"Closed {count} open file(s)"
    
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
    
    async def replace_text(
        self,
        path: str,
        old_text: str,
        new_text: str,
        threshold: float = 0.95,
        validate_syntax: bool = True
    ) -> str:
        """Replace text in a file using fuzzy matching."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            content = _sanitize_content(content)
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        span, score = _find_best_window(lines, old_text, threshold=threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
            if best_span:
                start, end, _, _ = best_span
                matched_lines = lines[start:end]
                matched_text = ''.join(matched_lines).strip()
                return (
                    f"No match above {threshold:.0%} threshold. "
                    f"Best match ({best_score:.0%}) at lines {start+1}-{end}:\n"
                    f"{matched_text[:300]}"
                )
            return f"Text not found in {os.path.basename(abs_path)}."
        
        # Unpack the new span format: (start, end, char_start, char_end)
        start, end, char_start, char_end = span
        
        # Build new content by replacing only the matched portion
        if char_end is not None:
            # Single-line replacement with character offsets
            # Extract parts before and after the match within the line
            line = lines[start]
            before_part = line[:char_start]
            after_part = line[char_end:]
            
            # Combine: before + new_text + after
            new_line = before_part + new_text + after_part
            
            # Build new content: before lines + new line + after lines
            before_lines = lines[:start]
            after_lines = lines[end:]
            new_content = ''.join(before_lines + [new_line] + after_lines)
        else:
            # Multi-line or fuzzy match - use old logic
            before_lines = lines[:start]
            after_lines = lines[end:]
            
            new_content_lines = new_text.splitlines(keepends=True)
            if new_content_lines and not new_content_lines[-1].endswith('\n'):
                new_content_lines[-1] += '\n'
            
            new_content = ''.join(before_lines + new_content_lines + after_lines)
        
        if validate_syntax and abs_path.endswith('.py'):
            is_valid, syntax_error = _validate_python(new_content)
            if not is_valid:
                return f"Syntax validation failed: {syntax_error}"
        
        try:
            _atomic_write(abs_path, new_content)
        except Exception as e:
            return f"Error writing {abs_path}: {e}"
        
        # Track change in memory
        session_id = self._get_session_id()
        diff = _generate_diff(abs_path, lines, new_content.splitlines(keepends=True))
        track_file_change(session_id, abs_path, "replace_text", diff)
        
        return f"✅ Replaced text at lines {start+1}-{end} ({score:.0%} match)\n{diff}"
    
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
        
        diff = _generate_diff(abs_path, original_lines, final_content.splitlines(keepends=True))
        
        try:
            _atomic_write(abs_path, final_content)
        except Exception as e:
            return EditResult(False, abs_path, f"Failed to write: {e}")
        
        # Track change
        session_id = self._get_session_id()
        track_file_change(session_id, abs_path, f"batch_edit({len(replacements)})", diff)
        
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
        
        diff = _generate_diff(abs_path, original_lines, modified.splitlines(keepends=True))
        
        try:
            _atomic_write(abs_path, modified)
        except Exception as e:
            return EditResult(False, abs_path, f"Failed to write: {e}")
        
        # Track change
        session_id = self._get_session_id()
        track_file_change(session_id, abs_path, "delete_snippet", diff)
        
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
        
        if create_parent_dirs:
            parent = os.path.dirname(abs_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent)
        
        try:
            _atomic_write(abs_path, content)
        except Exception as e:
            return f"Error writing {abs_path}: {e}"
        
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
        
        try:
            os.unlink(abs_path)
        except Exception as e:
            return EditResult(False, abs_path, f"Failed to delete: {e}")
        
        # Clean up memory entries for this file using property search
        session_id = self._get_session_id()
        filename = os.path.basename(abs_path)
        query = f"p:{PROP_FILENAME}={filename}"
        memories = self._get_search_memories()(session_id, query, limit=100)
        
        for mem in memories:
            mem_id = mem.get("id")
            if mem_id:
                self._get_delete_memory()(mem_id)
        
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
        
        # Store in memory using unique keyword + properties
        memory_type = make_open_file_keyword(filename)
        content_mem = f"open: {filename} {defn.qualified_name} ({defn.type})"
        properties = {
            PROP_FILENAME: filename,
            PROP_PATH: abs_path,
            PROP_LINE_START: str(defn.line_start),
            PROP_LINE_END: str(defn.line_end),
            "definition_name": defn.name,
            "definition_type": defn.type,
            "qualified_name": defn.qualified_name
        }
        
        self._get_set_memory()(session_id, memory_type, content_mem, properties)
        
        return result
    
    # -------------------------------------------------------------------------
    # Preview/Diff Operations
    # -------------------------------------------------------------------------
    
    async def preview_replace(self, path: str, old_text: str, threshold: float = 0.95) -> str:
        """Preview where a replacement would match."""
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        
        try:
            with open(abs_path, 'r') as f:
                content = f.read()
            lines = content.splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {abs_path}: {e}"
        
        span, score = _find_best_window(lines, old_text, threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
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
        old_text: str,
        new_text: str,
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
        
        span, score = _find_best_window(lines, old_text, threshold)
        
        if not span:
            best_span, best_score = _find_best_window(lines, old_text, threshold=0.0)
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
        new_lines = new_text.splitlines(keepends=True)
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
        for mem in memories:
            props = mem.get("properties", {})
            path = props.get("path", "unknown")
            line_start = props.get("line_start", "0")
            line_end = props.get("line_end", "*")
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
