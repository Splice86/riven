"""
Template rendering for prompt tags.

Replaces {{tag}} placeholders with module info/definitions.
"""

import re
from typing import Any

# Compile regex once at module level
_TAG_PATTERN = re.compile(r'\{\{(\w+)\}\}')


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render a template by replacing {{tag}} with values from context.
    
    Args:
        template: The prompt template with {{tag}} placeholders
        context: Dict mapping tag names to their replacement values
        
    Returns:
        Rendered prompt with all tags replaced
    """
    result = template
    
    # Find all {{tag}} patterns
    for match in _TAG_PATTERN.finditer(result):
        tag = match.group(1)
        if tag in context:
            replacement = context[tag]
            if replacement is None:
                replacement = ""
            # Replace this specific match
            result = result[:match.start()] + str(replacement) + result[match.end():]
    
    return result


def extract_tags(template: str) -> list[str]:
    """Extract all tag names from a template.
    
    Args:
        template: The prompt template with {{tag}} placeholders
        
    Returns:
        List of tag names found in the template
    """
    return _TAG_PATTERN.findall(template)


def build_context(
    notifications: list[Any],
    module_infos: dict[str, str | dict | None],
    function_defs: dict[str, list[dict]]
) -> dict[str, Any]:
    """Build the context dict for template rendering.
    
    Args:
        notifications: List of notification items from the queue
        module_infos: Dict mapping module names to their info() output
        function_defs: Dict mapping function names to their definitions
        
    Returns:
        Context dict ready for template rendering
    """
    context = {}
    
    # Notifications
    if notifications:
        context["notifications"] = "\n".join(str(n) for n in notifications)
    else:
        context["notifications"] = "No new notifications"
    
    # Module info - each module provides its own tag
    for module_name, info in module_infos.items():
        if info:
            context[module_name] = info
    
    # Function definitions - each function gets its definition
    for func_name, defs in function_defs.items():
        if defs:
            # Format as a simple list for the prompt
            formatted = []
            for d in defs:
                formatted.append(f"- {d.get('name', 'unknown')}: {d.get('description', '')}")
            context[func_name] = "\n".join(formatted)
        else:
            context[func_name] = ""
    
    return context
