"""AST-based Python code parser for extracting classes and functions.

Provides CodeDefinition dataclass and DefinitionExtractor AST visitor
for extracting code structure from Python files.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Literal

import jellyfish


@dataclass
class CodeDefinition:
    """Represents a class or function definition extracted from Python code."""
    name: str                    # Function/class name
    type: Literal["class", "function", "method", "async_function", "async_method"]
    line_start: int              # 1-indexed start line
    line_end: int                # 1-indexed end line
    qualified_name: str          # Full path including class: "ClassName.method_name"
    decorators: list[str] = field(default_factory=list)
    signature: str = ""          # Function signature as string
    docstring: str = ""          # Docstring content
    async_keyword: bool = False

    @property
    def line_range(self) -> str:
        """Get the line range string."""
        return f"{self.line_start}-{self.line_end}"

    @property
    def memory_key(self) -> str:
        """Get the memory key for this definition."""
        return f"{self.name}:{self.line_start}-{self.line_end}"


class DefinitionExtractor(ast.NodeVisitor):
    """AST visitor that extracts all class and function definitions.
    
    Walks an AST and collects all top-level and nested definitions,
    tracking line numbers, decorators, signatures, and docstrings.
    """
    
    def __init__(self, source_lines: list[str]):
        self.source_lines = source_lines  # Lines with trailing newlines
        self.definitions: list[CodeDefinition] = []
        self._class_stack: list[str] = []  # Stack of enclosing class names
    
    def extract(self, tree: ast.AST) -> list[CodeDefinition]:
        """Extract all definitions from an AST tree."""
        self.visit(tree)
        return self.definitions
    
    def _get_source_lines(self, start: int, end: int) -> list[str]:
        """Get source lines (1-indexed) as raw strings without trailing newlines."""
        result = []
        for i in range(start - 1, min(end, len(self.source_lines))):
            line = self.source_lines[i]
            result.append(line.rstrip('\n'))
        return result
    
    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Build a signature string from a function/method AST node."""
        args = node.args
        parts = []
        
        # Self/cls for methods
        if args.args:
            first_arg = args.args[0]
            if self._class_stack and first_arg.arg == 'self':
                parts.append('self')
            elif self._class_stack and first_arg.arg == 'cls':
                parts.append('cls')
            else:
                parts.append(first_arg.arg)
        
        # Regular args (skip self/cls if in class)
        start_idx = 1 if (self._class_stack and args.args and 
                          args.args[0].arg in ('self', 'cls')) else 0
        for arg in args.args[start_idx:]:
            parts.append(arg.arg)
        
        # *args
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        
        # Keyword-only args (Python 3.10 uses kwonlyargs)
        kwonly = getattr(args, 'kwonly', None) or getattr(args, 'kwonlyargs', [])
        if kwonly:
            for arg in kwonly:
                parts.append(arg.arg)
        
        # **kwargs
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        
        return f"{', '.join(parts)}"
    
    def _get_docstring(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
        """Extract docstring from a node."""
        docstring = ast.get_docstring(node)
        # Truncate long docstrings
        if docstring and len(docstring) > 500:
            docstring = docstring[:500].rstrip() + "..."
        return docstring or ""
    
    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool = False):
        """Visit a function/method definition."""
        line_start = node.lineno
        line_end = node.end_lineno or line_start
        
        # Build qualified name
        qualified_name = node.name
        if self._class_stack:
            qualified_name = f"{'.'.join(self._class_stack)}.{node.name}"
        
        # Determine type
        is_async = isinstance(node, ast.AsyncFunctionDef)
        if is_method:
            func_type = "async_method" if is_async else "method"
        else:
            func_type = "async_function" if is_async else "function"
        
        # Get decorators
        decorators = []
        for dec in node.decorator_list:
            dec_name = ast.unparse(dec) if hasattr(ast, 'unparse') else getattr(dec, 'attr', str(dec))
            decorators.append(dec_name)
        
        # Build signature
        sig = self._build_signature(node)
        prefix = "async def " if is_async else "def "
        signature = f"{prefix}{node.name}({sig})"
        
        # Get docstring
        docstring = self._get_docstring(node)
        
        # Create definition
        self.definitions.append(CodeDefinition(
            name=node.name,
            type=func_type,
            line_start=line_start,
            line_end=line_end,
            qualified_name=qualified_name,
            decorators=decorators,
            signature=signature,
            docstring=docstring,
            async_keyword=is_async
        ))
    
    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit a class definition."""
        line_start = node.lineno
        line_end = node.end_lineno or line_start
        
        # Get decorators
        decorators = []
        for dec in node.decorator_list:
            dec_name = ast.unparse(dec) if hasattr(ast, 'unparse') else getattr(dec, 'attr', str(dec))
            decorators.append(dec_name)
        
        # Get docstring
        docstring = self._get_docstring(node)
        
        # Create class definition
        self.definitions.append(CodeDefinition(
            name=node.name,
            type="class",
            line_start=line_start,
            line_end=line_end,
            qualified_name=node.name,
            decorators=decorators,
            signature=f"class {node.name}",
            docstring=docstring
        ))
        
        # Push class onto stack and visit body
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()
    
    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit a function definition."""
        self._visit_function(node, is_method=bool(self._class_stack))
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Visit an async function definition."""
        self._visit_function(node, is_method=bool(self._class_stack))


def _extract_code_definitions(source: str) -> list[CodeDefinition]:
    """Extract all class and function definitions from Python source.
    
    Args:
        source: Python source code as string
        
    Returns:
        List of CodeDefinition objects sorted by line number
    """
    try:
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'  # Ensure last line has newline
        extractor = DefinitionExtractor(lines)
        definitions = extractor.extract(tree)
        # Sort by line number
        definitions.sort(key=lambda d: d.line_start)
        return definitions
    except SyntaxError:
        return []


def _find_definitions_by_name(
    definitions: list[CodeDefinition],
    name: str,
    threshold: float = 0.8
) -> list[CodeDefinition]:
    """Find definitions matching a name (exact or fuzzy).
    
    Args:
        definitions: List of CodeDefinition to search
        name: Name or pattern to match
        threshold: Minimum Jaro-Winkler similarity for fuzzy matching
        
    Returns:
        List of matching definitions (exact matches first, then fuzzy)
    """
    exact_matches = []
    fuzzy_matches = []
    
    for defn in definitions:
        # Check exact match on name and qualified_name
        if defn.name == name or defn.qualified_name == name:
            exact_matches.append(defn)
        else:
            # Fuzzy match on qualified name
            score = jellyfish.jaro_winkler_similarity(defn.qualified_name.lower(), name.lower())
            if score >= threshold:
                fuzzy_matches.append((defn, score))
    
    # Sort fuzzy matches by score descending
    fuzzy_matches.sort(key=lambda x: x[1], reverse=True)
    
    return exact_matches + [x[0] for x in fuzzy_matches]


def _extract_definition_source(defn: CodeDefinition, source_lines: list[str]) -> list[str]:
    """Extract the source lines for a definition.
    
    Args:
        defn: CodeDefinition to extract
        source_lines: Source file lines (with newlines)
        
    Returns:
        List of source lines without trailing newlines
    """
    # source_lines is 0-indexed, defn lines are 1-indexed
    start_idx = defn.line_start - 1
    end_idx = min(defn.line_end, len(source_lines))
    return [line.rstrip('\n') for line in source_lines[start_idx:end_idx]]
