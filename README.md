# Riven - Agentic Loop Package

An autonomous agentic loop that runs in a background thread, interacting with modules that provide info and callable functions.

## Installation

```bash
cd /home/david/Projects/riven
```

## Quick Start

```python
from agentic_loop import AgenticLoop
from module import ClockModule, PrintModule, NotificationModule
from llm import LlamaCppClient

# Create notification module (handles incoming notifications)
notifications = NotificationModule()

# Create the loop with default LLM (192.168.1.11:8010)
loop = AgenticLoop(
    main_prompt="""You are an autonomous agent.

Context:
{{notifications}}

Available functions:
{{print}}

Decide what to do.""",
    max_iterations=10,
    loop_delay=0.5
)

# Register modules
loop.register_module(ClockModule())
loop.register_module(PrintModule())
loop.register_module(notifications)

# Start the loop
loop.start()

# Send notifications through the module (not the loop)
notifications.send({"type": "event", "data": "Hello!"})

# ... let it run ...

# Stop when done
loop.stop()

# Check what happened
for entry in loop.get_conversation_history():
    print(f"{entry['function']}: {entry['result']}")
```

## Architecture

### Module System

A module is a class with three parts:

| Method | Purpose |
|--------|---------|
| `info()` | Returns str/dict to inject into the prompt |
| `definitions()` | Returns list of function definitions for the LLM |
| `get_functions()` | Returns dict of callable functions |

**Built-in Modules:**

```python
from module import ClockModule, PrintModule, NotificationModule

ClockModule()         # Injects current time into prompt
PrintModule()        # Allows LLM to print messages
NotificationModule()  # Handles incoming notifications
```

**Creating Custom Modules:**

```python
from module import Module

class MyModule(Module):
    def info(self) -> str | dict | None:
        return "This gets injected into {{MyModule}}"
    
    def definitions(self) -> list[dict]:
        return [
            {
                "name": "my_function",
                "description": "Does something cool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "arg": {"type": "string"}
                    },
                    "required": ["arg"]
                }
            }
        ]
    
    def get_functions(self) -> dict:
        return {"my_function": self.my_function}
    
    def my_function(self, arg: str) -> str:
        return f"Called with: {arg}"
```

### Template System

Use `{{tag}}` placeholders in your prompt:

```python
main_prompt = """You are an agent.

Time: {{ClockModule}}

Notifications:
{{notifications}}

Functions available:
{{print}}
"""
```

These get replaced with:
- `{{ClockModule}}` → ClockModule.info() output
- `{{notifications}}` → NotificationModule info
- `{{print}}` → PrintModule.definitions() output

### LLM Client

Default connects to llama.cpp at 192.168.1.11:8010:

```python
from llm import LlamaCppClient, create_reasoner

# Default
client = LlamaCppClient()  # 192.168.1.11:8010

# Custom
client = LlamaCppClient(
    host="192.168.1.100",
    port=8080,
    model="llama3",
    temperature=0.7
)

# Create reasoner function
reasoner = create_reasoner(client)

# Use in loop
loop = AgenticLoop(llm_client=client, main_prompt="...")
```

Or provide your own reasoner:

```python
def my_reasoner(prompt: str, history: list) -> tuple[str, dict]:
    # Call your LLM
    response = llm.chat(prompt)
    # Parse to extract function_name and args
    return "print", {"message": "Hello!"}

loop = AgenticLoop(reasoner=my_reasoner, main_prompt="...")
```

## API Reference

### AgenticLoop

```python
loop = AgenticLoop(
    reasoner=None,           # Your reasoner function (or use llm_client)
    main_prompt="",         # Prompt with {{tag}} placeholders
    llm_client=None,       # LLM client (defaults to llama.cpp @ 192.168.1.11:8010)
    max_iterations=None,   # None = unlimited
    loop_delay=0.5           # Seconds between iterations
)

loop.register_module(module, name=None)
loop.start()
loop.stop(timeout=5.0)

loop.get_conversation_history()  # List of {function, args, result}
loop.is_running()              # bool
```

### NotificationModule

```python
notifications = NotificationModule()
notifications.send({"type": "event", "data": "..."})
```

The LLM can call `get_notifications()` to retrieve pending items.

### LlamaCppClient

```python
client = LlamaCppClient(
    host="192.168.1.11",
    port=8010,
    model="llama3",
    temperature=0.7,
    max_tokens=256
)

response = client.chat(message, system_prompt="...", history=[])
```

## File Structure

```
/home/david/Projects/riven/
├── __init__.py         # Package exports
├── agentic_loop.py    # Main AgenticLoop class
├── module.py           # Module base class + built-in modules
├── registry.py        # Module registry
├── template.py         # Template rendering
├── llm.py             # Llama.cpp client
└── README.md          # This file
```

## Threading

The loop runs in a daemon thread using `threading.Thread`. All shared state is protected with `threading.Lock`. The loop is designed to run without user input - it will continue calling the LLM and executing functions until stopped or max_iterations reached.

## Version

0.1.0
