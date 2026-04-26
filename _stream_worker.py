#!/usr/bin/env python3
"""Stream worker — runs as a subprocess to stream process output to a file.

Uses the new process API:
1. POST /processes to spawn a process
2. GET /processes/{id}/output/stream to stream SSE output

Do not run this directly. Use test_cli.py instead.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--session", required=True, help="Process ID (session)")
    parser.add_argument("--shard", default="codehammer")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output_file = open(args.output, "w", buffering=1)  # line-buffered
    base = args.api_url

    # Step 1: Spawn the process via the new process API
    spawn_payload = json.dumps({
        "shard_name": args.shard,
        "message": args.message,
        "process_id": args.session,
    }).encode("utf-8")

    spawn_req = urllib.request.Request(
        f"{base}/processes",
        data=spawn_payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(spawn_req, timeout=10) as resp:
            spawn_data = json.loads(resp.read())
            process_id = spawn_data["process_id"]
            output_file.write(f"[Spawned] id={process_id} shard={args.shard} status={spawn_data.get('status', '?')}\n")
            output_file.flush()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        output_file.write(f"[SPAWN ERROR {e.code}] {body}\n")
        output_file.flush()
        sys.exit(1)
    except urllib.error.URLError as e:
        output_file.write(f"[CONNECTION ERROR on spawn] {e.reason}\n")
        output_file.flush()
        sys.exit(1)

    # Step 2: Stream output from the process
    stream_req = urllib.request.Request(
        f"{base}/processes/{process_id}/output/stream",
        headers={"Accept": "text/event-stream"},
    )

    thinking_buf = ""

    def flush_thinking():
        nonlocal thinking_buf
        if thinking_buf:
            output_file.write(f"\n--- thinking ---\n{thinking_buf.strip()}\n--------------------------\n")
            output_file.flush()
            thinking_buf = ""

    try:
        with urllib.request.urlopen(stream_req, timeout=300) as resp:
            for line in resp:
                line = line.decode("utf-8", errors="replace")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str:
                    continue
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    output_file.write(f"[parse error] {data_str}\n")
                    output_file.flush()
                    continue

                etype = event.get("type")

                if etype == "token":
                    output_file.write(event.get("content", ""))
                    output_file.flush()
                elif etype == "thinking":
                    thinking_buf += event.get("content", "")
                elif etype == "tool_call":
                    flush_thinking()
                    tc = event.get("content", {})
                    args_str = tc.get("arguments", {}) if isinstance(tc, dict) else {}
                    name = tc.get("name", "?") if isinstance(tc, dict) else "?"
                    output_file.write(
                        f"\n[call] {name}({json.dumps(args_str) if isinstance(args_str, dict) else args_str})\n"
                    )
                    output_file.flush()
                elif etype == "tool_result":
                    flush_thinking()
                    tr = event.get("content", {})
                    if isinstance(tr, dict):
                        if tr.get("error"):
                            output_file.write(f"[result ERROR: {tr['error']}] {tr.get('content', '')}\n")
                        else:
                            output_file.write(f"[result] {tr.get('content', '')}\n")
                    else:
                        output_file.write(f"[result] {tr}\n")
                    output_file.flush()
                elif etype == "error":
                    flush_thinking()
                    output_file.write(f"\n[ERROR] {event.get('content', event)}\n")
                    output_file.flush()
                elif etype in ("status", "done"):
                    flush_thinking()
                    if etype == "done":
                        output_file.write(f"\n[done] status={event.get('status', 'done')}\n")
                        output_file.flush()
                        return

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        output_file.write(f"\n[HTTP ERROR {e.code}] {body}\n")
        output_file.flush()
        sys.exit(1)
    except urllib.error.URLError as e:
        output_file.write(f"\n[CONNECTION ERROR] {e.reason}\n")
        output_file.flush()
        sys.exit(1)
    finally:
        flush_thinking()
        output_file.close()


if __name__ == "__main__":
    main()
