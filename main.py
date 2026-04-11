"""Main entry point for Riven agent."""

import argparse


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Riven AI Agent")
    
    # Mode selection
    parser.add_argument("--http", action="store_true",
                        help="Launch HTTP API socket")
    parser.add_argument("--websocket", "-w", action="store_true",
                        help="Launch WebSocket socket")
    
    # Core selection
    parser.add_argument("--core", default="code_hammer",
                        help="Core to use (default: code_hammer)")
    
    args = parser.parse_args()
    
    # Default to CLI
    if args.http:
        print("HTTP socket not implemented yet")
    elif args.websocket:
        print("WebSocket socket not implemented yet")
    else:
        # Default: CLI
        from sockets.cli import main as cli_main
        cli_main()


if __name__ == "__main__":
    main()