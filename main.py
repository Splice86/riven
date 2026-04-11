"""Main entry point for Riven agent."""

import asyncio
import logging
import sys
import threading

from core import get_core, list_cores

# Flag to track if we're currently processing a request
_processing = False


def input_with_blocking(prompt: str) -> str:
    """Input that blocks until processing is done."""
    global _processing
    
    while _processing:
        pass  # Spin wait - simple blocking
    
    return input(prompt).strip()


async def main():
    """Interactive REPL for the agent."""
    global _processing
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    parser.add_argument(
        "--core", "-c",
        default="default",
        help=f"Core to use (default: default). Available: {list_cores()}"
    )
    args = parser.parse_args()
    
    core = get_core(args.core)
    core_name = args.core
    prompt_prefix = f"\033[96m[{core_name}]\033[0m"  # Cyan color
    
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
            
            # Result is already streamed to terminal, just run it
            result = await core.run(prompt)
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


if __name__ == "__main__":
    # Suppress HTTP request logging from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())