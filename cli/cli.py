#!/usr/bin/env python3
"""Riven CLI - connects to Riven API server."""

import sys
import os

# ANSI colors
RED = "\033[91m"
MAGENTA = "\033[95m"
PURPLE = "\033[35m"
CYAN = "\033[96m"
RESET = "\033[0m"

TAGLINE = "⬡ ̸S̵I̷G̴N̷A̵L̷S̴ ̷◆̷ ̷T̶O̶ ̵T̷H̷E̴ ̷V̴O̵I̶D̸ ⬡"


def print_banner():
    """Print cyberpunk ASCII art banner."""
    try:
        import pyfiglet
        result = pyfiglet.figlet_format("RIVEN", font="slant")
        print(f"{RED}{result}{RESET}")
        print(f"{' ' * 30}{RED}CODEHAMMER{RESET}")
        print()
        print(f"{CYAN}┌────────────────────────────────────────┐{RESET}")
        print(f"{CYAN}│{RESET}{MAGENTA}        {TAGLINE}{CYAN}{' ' * 10}{RESET}{CYAN}│{RESET}")
        print(f"{CYAN}└────────────────────────────────────────┘{RESET}")
    except ImportError:
        print("RIVEN")
        print("------")


def get_prompt_prefix(core_name: str) -> str:
    return f"{CYAN}Riven - {core_name}{RESET}"


def get_session_line(session_id: str) -> str:
    return f"\033[90m[{session_id[:8]}]{RESET}"


def main():
    """Run CLI."""
    print_banner()
    
    from client import get_client
    import requests
    
    client = get_client()
    
    # Check API health
    try:
        resp = requests.get(f"{client.base_url}/")
        if resp.status_code != 200:
            print(f"{RED}Error: API not responding correctly{RESET}")
            sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"{RED}Error: Cannot connect to API at {client.base_url}{RESET}")
        print("Make sure the Riven API server is running:")
        print(f"  python -m uvicorn api:app")
        sys.exit(1)
    
    # Create session
    result = client.create_session(core_name="code_hammer")
    
    if not result.get("ok"):
        print(f"{RED}Error: {result.get('message')}{RESET}")
        sys.exit(1)
    
    session = result["session_id"]
    print(f"Using core: code_hammer")
    print(f"Session: {session[:8]}")
    print("Riven agent ready. Type '/exit' to stop, '/clear' to reset session.\n")
    
    prompt_prefix = get_prompt_prefix("code_hammer")
    
    # Input loop
    try:
        while True:
            user_input = input(f"{get_session_line(session)}\n{prompt_prefix} > ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == '/exit':
                break
            
            if user_input.lower() == '/clear':
                client.close_session()
                result = client.create_session(core_name="code_hammer")
                session = result["session_id"]
                print(f"✓ Session cleared. New session: {session[:8]}")
                continue
            
            # Send message
            result = client.send_message(user_input)
            
            if result.get("output"):
                print(f"\n{result['output']}\n")
            elif result.get("error"):
                print(f"\n{RED}Error: {result['error']}{RESET}\n")
    
    except KeyboardInterrupt:
        print("\n^C Interrupted")
    except EOFError:
        print("\nGoodbye!")
    finally:
        client.close_session()
        print("Disconnected")


if __name__ == "__main__":
    main()