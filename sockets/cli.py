"""CLI socket for interactive terminal."""

import os
import sys
import argparse
import logging
from sockets.base import SocketBase


# ANSI colors
RED = "\033[91m"
MAGENTA = "\033[95m"
PURPLE = "\033[35m"
CYAN = "\033[96m"
RESET = "\033[0m"

TAGLINE = "⬡ ̸S̵I̷G̴N̷A̵L̷S̴ ̷◆̷ ̷T̶O̶ ̵T̷H̷E̴ ̷V̴O̵I̶D̸ ⬡"


def print_banner() -> None:
    """Print cyberpunk ASCII art banner."""
    try:
        import pyfiglet
        
        fonts = ["slant", "big", "block", "doom", "standard"]
        chosen_font = "slant"
        
        for font in fonts:
            try:
                result = pyfiglet.figlet_format("RIVEN", font=font)
                if len(result.split('\n')[0]) < 80:
                    chosen_font = font
                    break
            except Exception:
                continue
        
        result = pyfiglet.figlet_format("RIVEN", font=chosen_font)
        
        lines = result.split('\n')
        n = len(lines)
        gradient_colors = [RED, MAGENTA, PURPLE, PURPLE, CYAN]
        
        for i, line in enumerate(lines):
            if line.strip():
                color_idx = min(i * len(gradient_colors) // n, len(gradient_colors) - 1)
                print(f"{gradient_colors[color_idx]}{line}{RESET}")
        
        print(f"{' ' * 30}{RED}CODEHAMMER{RESET}")
        print()
        
        import unicodedata
        visible_len = len(unicodedata.normalize('NFKC', TAGLINE))
        print(f"{CYAN}┌{'─' * 40}┐{RESET}")
        print(f"{CYAN}│{RESET}{MAGENTA}        {TAGLINE}{CYAN}{' ' * (40 - visible_len+14)}{RESET}{CYAN}│{RESET}")
        print(f"{CYAN}└{'─' * 40}┘{RESET}")
        
    except ImportError:
        print("RIVEN")
        print("------")


def get_prompt_prefix(core_name: str) -> str:
    """Get prompt prefix with core name in cyan."""
    return f"\033[96mRiven - {core_name}\033[0m"


def get_session_line(session_id: str) -> str:
    """Get session ID line in dim grey."""
    return f"\033[90m[{session_id[:8]}]\033[0m"


class CLISocket(SocketBase):
    """Interactive CLI socket."""
    
    def __init__(self, core_name: str = None):
        super().__init__(session_strategy="new")
        self._core_name = core_name
        self._running = False
    
    def run(self) -> None:
        """Run the CLI socket."""
        print_banner()
        
        # Connect to core
        session = self.connect(core_name=self._core_name)
        display_name = self._core_name or "code_hammer"
        
        print(f"Using core: {display_name}")
        print(f"Session: {session[:8]}")
        print("Riven agent ready. Type '/exit' to stop, '/clear' to reset session.\n")
        
        self._running = True
        self._session_id = session
        
        prompt_prefix = get_prompt_prefix(display_name)
        
        # Input loop
        try:
            while self._running:
                user_input = input(f"{get_session_line(session)}\n{prompt_prefix} > ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == '/exit':
                    break
                
                if user_input.lower() == '/clear':
                    # Start new session
                    result = self._manager.start(core_name=self._core_name)
                    if result["ok"]:
                        session = result["session_id"]
                        self._session_id = session
                    print(f"✓ Session cleared. New session: {session[:8]}")
                    continue
                
                # Send message and get response directly
                result = self._manager.send(session, user_input)
                
                if result.get("ok"):
                    print(f"\n{result['output']}\n")
                else:
                    print(f"\n❌ Error: {result.get('error', 'Unknown')}\n")
                
                print(f"{get_session_line(session)}")
                print(f"{prompt_prefix} > ", end="")
                
                # Check for exit request
                from modules.system import is_exit_requested
                if is_exit_requested():
                    from modules.system import clear_exit
                    clear_exit()
                    break
        
        except KeyboardInterrupt:
            print("\n^C Interrupted")
        except EOFError:
            print("\nGoodbye!")
        finally:
            self._running = False
            self.disconnect()
            print("Disconnected")
    
    def start(self, session_id: str = None, core_name: str = None):
        """Start a new session."""
        return self._manager.start(session_id=session_id, core_name=core_name or self._core_name)


def main():
    """Run CLI socket."""
    # Configure logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    # Load config
    import yaml
    CONFIG = {}
    if os.path.exists("config.yaml"):
        with open("config.yaml") as f:
            CONFIG = yaml.safe_load(f) or {}
    
    default_core = CONFIG.get('default_core', 'code_hammer')
    
    # Get core list for help text
    from core_manager import list_cores
    available = [c['name'] for c in list_cores()]
    
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    parser.add_argument("--core", "-c", default=default_core, 
                        help=f"Core to use (default: {default_core}). Available: {available}")
    args = parser.parse_args()
    
    socket = CLISocket(core_name=args.core)
    socket.run()


if __name__ == "__main__":
    main()