"""CLI handling for Riven agent - input/output and REPL loop."""

import asyncio
import argparse

from core import get_core, list_cores, get_core_display_name, CONFIG

# Flag to track if we're currently processing a request
_processing = False


def get_prompt_prefix(core_name: str) -> str:
    """Get the prompt prefix with core name in cyan."""
    return f"\033[96mRiven - {core_name}\033[0m"


TAGLINE = "⬡ ̵S̸Y̷N̴T̷H̶W̸A̵V̴E̷ ̷◆̶ ⬡"


def print_banner() -> None:
    """Print cyberpunk ASCII art banner using pyfiglet."""
    try:
        import pyfiglet
        from pyfiglet import FigletFont
        
        # Custom gradient colors: red -> magenta -> purple -> cyan
        RED = "\033[91m"
        MAGENTA = "\033[95m"
        PURPLE = "\033[35m"
        CYAN = "\033[96m"
        RESET = "\033[0m"
        
        # Try different fonts that look good
        fonts = ["slant", "big", "block", "doom", "standard"]
        chosen_font = "slant"
        
        for font in fonts:
            try:
                result = pyfiglet.figlet_format("RIVEN", font=font)
                if len(result.split('\n')[0]) < 80:  # Reasonable width
                    chosen_font = font
                    break
            except Exception:
                continue
        
        result = pyfiglet.figlet_format("RIVEN", font=chosen_font)
        
        # Apply gradient by lines
        lines = result.split('\n')
        n = len(lines)
        gradient_colors = [RED, MAGENTA, PURPLE, PURPLE, CYAN]
        
        for i, line in enumerate(lines):
            if line.strip():
                color_idx = min(i * len(gradient_colors) // n, len(gradient_colors) - 1)
                print(f"{gradient_colors[color_idx]}{line}{RESET}")
            else:
                print()
        
        # Tagline
        print(f"{CYAN}┌{'─' * 40}┐{RESET}")
        print(f"{CYAN}│{RESET}{MAGENTA}        {TAGLINE}{CYAN}{' ' * (40 - len(TAGLINE))+8}{RESET}{CYAN}│{RESET}")
        print(f"{CYAN}└{'─' * 40}┘{RESET}")
        
    except ImportError:
        # Fallback if pyfiglet not installed
        print("RIVEN")
        print("------")


async def run_repl(core_name: str) -> None:
    """Run the interactive REPL."""
    global _processing
    
    print_banner()
    
    core = get_core(core_name)
    display_name = get_core_display_name(core_name)
    prompt_prefix = get_prompt_prefix(display_name)
    
    print(f"Using core: {display_name}")
    print(f"Tools loaded: {list(core._modules.all().keys())}")
    print(f"Memory DB: {core.db_name}")
    print(f"Session: {core.get_session_id()[:8]}...")
    print("Riven agent ready. Type '/exit' to stop, '/clear' to reset session.\n")
    
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
            
            # Handle /clear command - reset session
            if prompt.strip().lower() == '/clear':
                new_session = core.clear_session()
                print(f"✓ Session cleared. New session: {new_session[:8]}...")
                _processing = False
                print(f"{prompt_prefix} > ", end="")
                continue
            
            # Result is already streamed to terminal
            await core.run(prompt)
            _processing = False
            
            # Check if exit was requested via tool call
            from modules.system import is_exit_requested
            if is_exit_requested():
                from modules.system import clear_exit
                clear_exit()
                break
            
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
    
    # Get default core from config
    default_core = CONFIG.get('default_core', 'code_hammer')
    default_display = get_core_display_name(default_core)
    
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    parser.add_argument(
        "--core", "-c",
        default=default_core,
        help=f"Core to use (default: {default_display}). Available: {list_cores()}"
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