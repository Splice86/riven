"""
Riven - Agentic Loop Package

An autonomous agentic loop that runs in a background thread,
interacting with modules that provide info and functions.

Uses ReAct pattern: Reason -> Act -> Observe -> loop
"""

from module import Module, ClockModule, PrintModule, NotificationModule
from registry import ModuleRegistry
from template import render_template, extract_tags
from llm import LlamaCppClient, create_reasoner
from agentic_loop import AgenticLoop
from context import AgentContext, ToolExecution

__all__ = [
    "Module",
    "ClockModule", 
    "PrintModule",
    "NotificationModule",
    "ModuleRegistry",
    "render_template",
    "extract_tags", 
    "LlamaCppClient",
    "create_reasoner",
    "AgenticLoop",
    "AgentContext",
    "ToolExecution",
]

__version__ = "0.2.0"
