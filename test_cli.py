#!/usr/bin/env python3
"""Test CLI for riven_core.

Sends a message to the Riven API via the process API, spawns a process,
streams output to a file in real-time, and prints the PID so you can
track whether it's still running.

Usage:
    python test_cli.py --message "your prompt" --session "sess123" --output "out.txt"
    python test_cli.py --message "your prompt" --session "sess123" --output "out.txt" --shard "codehammer"

    # In another terminal:
    python killcheck.py 12345
    cat out.txt
"""

import argparse
import json
import os
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description="Send a streaming message to riven_core and save output to a file.")
    parser.add_argument("--message", "-m", required=True, help="The message to send to the AI")
    parser.add_argument("--session", "-s", default=None, help="Session ID (auto-generated if omitted)")
    parser.add_argument("--shard", default="codehammer", help="Shard name to use (default: codehammer)")
    parser.add_argument("--output", "-o", required=True, help="Output file to write to")
    parser.add_argument("--api-url", default="http://127.0.0.1:8080", help="Riven API base URL")
    args = parser.parse_args()

    session_id = args.session or str(uuid.uuid4())

    script_path = os.path.join(os.path.dirname(__file__), "_stream_worker.py")
    cmd = [
        sys.executable,
        script_path,
        "--api-url", args.api_url,
        "--message", args.message,
        "--session", session_id,
        "--shard", args.shard,
        "--output", args.output,
    ]

    proc = subprocess.Popen(cmd)
    print(f"PID: {proc.pid}")
    print(f"Session: {session_id}")
    print(f"Output: {args.output}")
    print(f"Shard: {args.shard}")
    print(f"API: {args.api_url}")
    print(f"[watch with: python killcheck.py {proc.pid}]")

    proc.wait()
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
