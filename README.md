# Riven

An AI coding agent that gets things done.

## What

- Read, edit, and write files
- Run shell commands
- Store and search memories
- Extend via modules

## Run

```bash
pip install -r requirements.txt
python main.py
```

## Config

Edit `config.yaml` for LLM settings, timeouts, etc.

### Cores

| Core | Use |
|------|-----|
| `default` | General |
| `code_hammer` | Development |
| `research` | Info gathering |

```bash
python main.py --core code_hammer
```

## Modules

| Module | Tools |
|--------|-------|
| **file** | open_file, replace_text, insert_lines, remove_lines, close_file, list_open_files |
| **shell** | run_shell |
| **memory** | search_memories, add_memory, get_memory, list_memories |
| **system** | exit_session, get_system_info |

### Add a Module

```python
from modules import Module

def get_module():
    async def my_tool(arg: str) -> str:
        """Does something."""
        return f"Result: {arg}"
    
    return Module(
        name="my_module",
        functions={"my_tool": my_tool}
    )
```

## Memory Server

The `memory/` folder is a separate FastAPI server.

```bash
cd memory
pip install -r requirements.txt
python api.py
# Runs on http://localhost:8030
```

## Commands

- `/exit` - Quit
- `Ctrl+C` - Interrupt

MIT