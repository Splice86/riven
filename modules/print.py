"""
Print module - allows LLM to print messages to terminal.
"""

from typing import Callable
from modules.base import Module


class PrintModule(Module):
    """Print module - allows LLM to print messages to terminal."""

    def info(self) -> None:
        """No info to inject."""
        return None

    def definitions(self) -> list[dict]:
        """Define the print function."""
        return [
            {
                "name": "print",
                "description": "Print a message to the terminal output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to print"
                        }
                    },
                    "required": ["message"]
                }
            }
        ]

    def get_functions(self) -> dict[str, Callable]:
        """Return the print function."""
        return {"print": self.print}

    def print(self, message: str) -> str:
        """Print a message to terminal."""
        print(f"[Agent] {message}")
        return f"Printed: {message}"
