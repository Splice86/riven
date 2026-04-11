"""Main entry point for Riven agent."""

import argparse
import os
import yaml


def main():
    """Main entry point."""
    # Load config for default core
    CONFIG = {}
    if os.path.exists("config.yaml"):
        with open("config.yaml") as f:
            CONFIG = yaml.safe_load(f) or {}
    
    default_core = CONFIG.get('default_core', 'code_hammer')
    
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    
    # Mode selection
    parser.add_argument("--http", action="store_true",
                        help="Launch HTTP API socket")
    parser.add_argument("--websocket", "-w", action="store_true",
                        help="Launch WebSocket socket")
    
    # Core selection
    parser.add_argument("--core", default=default_core,
                        help=f"Core to use (default: {default_core})")
    
    args = parser.parse_args()
    
    # Default to CLI
    if args.http:
        print("HTTP socket not implemented yet")
    elif args.websocket:
        print("WebSocket socket not implemented yet")
    else:
        # Default: CLI - pass core via sys.argv
        import sys
        sys.argv = ['cli', '-c', args.core]
        
        from sockets.cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()