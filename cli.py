"""CLI handling for Riven agent - input/output and REPL loop."""

import asyncio
import argparse

from core import get_core, list_cores

# Flag to track if we're currently processing a request
_processing = False


def get_prompt_prefix(core_name: str) -> str:
    """Get the prompt prefix with core name in cyan."""
    return f"\033[96m[{core_name}]\033[0m"


async def run_repl(core_name: str) -> None:
    """Run the interactive REPL."""
    global _processing
    
    core = get_core(core_name)
    prompt_prefix = get_prompt_prefix(core_name)
    
    print(f"Using core: {core_name}")
    print(f"Tools loaded: {list(core._modules.all().keys())}")
    print(f"Memory DB: {core.db_name}")
    print("Riven agent ready. Type 'quit' or 'exit' to stop.\n")
    
    while True:
        try:
            # Block input while processing
            _processing = True
            prompt = input(f"{prompt_prefix} > ").strip()
            _processing = False
            
            if prompt.lower() in ('quit', 'exit'):
                print("Goodbye!")
                break
            
            if not prompt:
                continue
            
            # Result is already streamed to terminal
            await core.run(prompt)
            _processing = False
            
        except KeyboardInterrupt:
            # Interrupt - cancel any ongoing operation
            _processing = False
            core.cancel()
            print("\n^C Interrupted")
            print(f"{prompt_prefix} > ", end="")
        except Exception as e:
            _processing = False
            print(f"Error: {e}\n")


def main() -> None:
    """Main entry point for CLI."""
    import logging
    
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    parser.add_argument(
        "--core", "-c",
        default="default",
        help=f"Core to use (default: default). Available: {list_cores()}"
    )
    args = parser.parse_args()
    
    # Suppress HTTP request logging from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    asyncio.run(run_repl(args.core))


if __name__ == "__main__":
    main()