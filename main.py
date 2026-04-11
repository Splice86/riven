"""Main entry point for Riven agent."""

import asyncio
import logging

from core import get_core, list_cores


async def main():
    """Interactive REPL for the agent."""
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
            prompt = input(f"{prompt_prefix} > ").strip()
            
            if prompt.lower() in ('quit', 'exit'):
                print("Goodbye!")
                break
            
            if not prompt:
                continue
            
            # Result is already streamed to terminal, just run it
            await core.run(prompt)
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == "__main__":
    # Suppress HTTP request logging from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(main())