#!/usr/bin/env python3
"""Riven CLI - connects to Riven API server."""

import sys
import os
import re

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GREY = "\033[90m"
RESET = "\033[0m"

BOLD = "\033[1m"
DIM = "\033[2m"

TAGLINE = "⬡ ̸S̵I̷G̴N̷A̵L̷S̴ ̷◆̷ ̷IN̶̶ ̵T̷H̷E̴ ̷V̴O̵I̶D̸ ⬡"


def print_banner():
    """Print cyberpunk ASCII art banner with vertical gradient."""
    try:
        import pyfiglet
        result = pyfiglet.figlet_format("RIVEN", font="slant")
        
        # Vertical gradient: dark red -> magenta -> cyan
        #gradient = [31, 31, 35, 35, 35, 36, 36, 36]  # explicit colors
        gradient = [31, 91, 35, 95,36]
        
        lines = result.split('\n')
        nonempty = [l for l in lines if l.strip()]
        num_lines = len(nonempty)
        
        for i, line in enumerate(nonempty):
            #color_idx = int(i / max(num_lines - 1, 1) * (len(gradient) - 1))
            #color_idx = min(color_idx, len(gradient) - 1)
            color = gradient[i]
            print(f"\033[{color}m{line}\033[0m")
        
        print(f"{' ' * 30}\033[91mCODEHAMMER\033[0m")
        print()
        print(f"{CYAN}┌────────────────────────────────────────┐{RESET}")
        print(f"{CYAN}│{RESET}{MAGENTA}        {TAGLINE}{CYAN}{' ' * 7}{RESET}{CYAN}│{RESET}")
        print(f"{CYAN}└────────────────────────────────────────┘{RESET}")
    except ImportError:
        print("RIVEN")
        print("------")


def get_prompt_prefix(core_name: str) -> str:
    return f"{CYAN}Riven - {core_name}{RESET}"


def get_session_line(session_id: str) -> str:
    return f"\033[90m[{session_id[:8]}]{RESET}"


def print_streamed(text: str):
    """Print streamed output with colors: grey thinking, yellow tools, cyan text."""
    if not text:
        return
    
    GREY = "\033[90m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    
    in_thinking = False
    in_tool = False
    tool_buffer = ""
    
    while text:
        if in_thinking:
            end = text.find('</think>')
            if end != -1:
                print(f"{GREY}{text[:end]}{RESET}", end="", flush=True)
                text = text[end + len('</think>'):]
                in_thinking = False
                print()  # newline after thinking
            else:
                print(f"{GREY}{text}{RESET}", end="", flush=True)
                break
        elif in_tool:
            end = text.find('</tool>')
            if end != -1:
                tool_buffer += text[:end]
                text = text[end + len('</tool>'):]
                print(f"{YELLOW}{tool_buffer}{RESET}", end="", flush=True)
                tool_buffer = ""
                in_tool = False
                print()  # newline after tool
            else:
                tool_buffer += text
                break
        else:
            # Check for thinking start
            start = text.find('<think>')
            if start != -1:
                print(f"{CYAN}{text[:start]}{RESET}", end="", flush=True)
                text = text[start + len('<think>'):]
                in_thinking = True
            else:
                # Check for tool start
                start = text.find('<tool>')
                if start != -1:
                    print(f"{CYAN}{text[:start]}{RESET}", end="", flush=True)
                    text = text[start + len('<tool>'):]
                    in_tool = True
                else:
                    print(f"{CYAN}{text}{RESET}", end="", flush=True)
                    break
    
    print()  # newline at end


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
    
    # Try to resume saved session, or create new one
    result = client.resume_session(core_name="code_hammer")
    if not result:
        result = client.create_session(core_name="code_hammer")
        client.save_session()
    
    if not result.get("ok"):
        print(f"{RED}Error: {result.get('message')}{RESET}")
        sys.exit(1)
    
    session = result["session_id"]
    resumed = result.get("resumed", False)
    
    print(f"Using core: code_hammer")
    if resumed:
        print(f"Session: {session[:8]} (resumed)")
    else:
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
                client.delete_saved_session()
                result = client.create_session(core_name="code_hammer")
                client.save_session()
                session = result["session_id"]
                print(f"✓ Session cleared. New session: {session[:8]}")
                continue
            
            # Send message with streaming (client prints during stream)
            try:
                client.stream_message(user_input)
            except Exception as e:
                print(f"\n{RED}Error: {e}{RESET}\n")
    
    except KeyboardInterrupt:
        print("\n^C Interrupted")
    except EOFError:
        print("\nGoodbye!")
    finally:
        # Keep session alive for persistence - don't close on exit
        print("Disconnected (session preserved)")


if __name__ == "__main__":
    main()