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
    print("Riven agent ready. Type '/exit' to stop.\n")
    
    while True:
        try:
            # Block input while processing
            if _processing:
                # Wait for previous operation to finish
                print("\n⏳ Still processing...\n")
                print(f"{prompt_prefix} > ", end="")
                continue
            
            _processing = True
            prompt = input(f"{prompt_prefix} > ").strip()
            
            if not prompt:
                _processing = False
                continue
            
            # Handle /exit command BEFORE sending to LLM
            if prompt.strip().lower() == '/exit':
                core.cancel()  # Cancel any ongoing operation
                print("Goodbye!")
                _processing = False
                break
            
            # Result is already streamed to terminal
            await core.run(prompt)
            _processing = False
            
        except KeyboardInterrupt:
            # Interrupt - cancel any ongoing operation
            _processing = False
            core.cancel()
            print("\n^C Interrupted")
            print(f"{prompt_prefix} > ", end="")
        except asyncio.CancelledError:
            # Clean exit - don't print error
            _processing = False
            print("\nGoodbye!")
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
        help=f"Core to use (default: code_hammer). Available: {list_cores()}"
    )
    args = parser.parse_args()
    
    # Suppress HTTP request logging from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    try:
        asyncio.run(run_repl(args.core))
    except KeyboardInterrupt:
        pass  # Clean exit


if __name__ == "__main__":
    main()