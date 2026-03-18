#!/usr/bin/env python3
"""
Test script for ReAct agentic loop.

This makes real LLM calls to the configured llama.cpp server.
"""

import time
import sys

from agentic_loop import AgenticLoop
from module import PrintModule, ClockModule, ExitModule, MessageModule
from llm import LlamaCppClient, create_reasoner
from context import AgentContext


def test_with_real_llm():
    """Run the agentic loop with a real LLM."""
    
    print("=" * 60)
    print("ReAct Agentic Loop Test")
    print("=" * 60)
    
    # Create LLM client (adjust host/port if needed)
    client = LlamaCppClient(
        host="192.168.1.11",
        port=8012,
        model="llama3",
        temperature=0.7,
        max_tokens=256,
        json_mode=False  # Disable JSON mode - let model respond freely
    )
    
    # Test the client first
    print("\n[1] Testing LLM connection...")
    try:
        test_response = client.chat("Say 'hello' in exactly 3 words.")
        print(f"    LLM response: {test_response[:100]}...")
    except Exception as e:
        print(f"    ERROR: {e}")
        print("    Make sure llama.cpp server is running!")
        return
    
    # Create the agentic loop
    print("\n[2] Creating AgenticLoop...")
    loop = AgenticLoop(
        reasoner=create_reasoner(client),
        main_prompt="""You are an autonomous agent. Your job is to follow instructions from messages.

CURRENT TIME: {{time}}
{{messages}}

Think carefully about each step. First reason about what to do, then take action.""",
        max_iterations=10,  # Allow up to 10, but exit will stop earlier
        loop_delay=1.0
    )
    
    # Register modules
    print("\n[3] Registering modules...")
    msg_module = MessageModule()
    loop.register_module(PrintModule())
    loop.register_module(ClockModule())
    loop.register_module(msg_module)
    loop.register_module(ExitModule(exit_callback=loop.stop))
    
    # Add a test message to the queue
    msg_module.add_message("Say something interesting about the current time, then exit.")
    
    # Start the loop
    print("\n[4] Starting loop...")
    loop.start()
    
    # Let it run
    print("    Running (will exit when LLM signals done)...")
    # Wait longer since we rely on LLM to exit
    time.sleep(35)
    
    # Stop
    print("\n[5] Stopping loop...")
    loop.stop(timeout=3.0)
    
    # Show results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    # Get context
    ctx = loop.get_context()
    print(f"\nTotal executions: {len(ctx)}")
    
    # Show observations
    print("\nObservations:")
    print("-" * 40)
    for i, obs in enumerate(ctx.get_execution_history(), 1):
        print(f"  {i}. {obs}")
    

    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


def test_context_only():
    """Test the context class without the full loop."""
    
    print("\n" + "=" * 60)
    print("Context Class Test (no LLM)")
    print("=" * 60)
    
    ctx = AgentContext()
    
    # Set tool definitions
    ctx.set_tool_definitions({
        "print": [{
            "name": "print",
            "description": "Print a message",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"]
            }
        }]
    })
    
    print(f"\nTools description:\n{ctx.get_tools_description()}")
    
    # Add some executions
    ctx.add_execution("print", {"message": "Hello!"}, "Printed: Hello!")
    ctx.add_execution("print", {"message": "World!"}, "Printed: World!")
    
    print(f"\nObservations:\n{ctx.get_observations()}")
    
    print(f"\nContext iteration: {ctx.get_observations()}")
    
    print("\nContext test complete!")


def test_simple_start_stop():
    """Test simple start/stop - tools registered before start."""
    
    print("\n" + "=" * 60)
    print("Simple Start/Stop Test")
    print("=" * 60)
    
    # Create a simple loop (no LLM needed for this test)
    loop = AgenticLoop(
        main_prompt="You are a test agent.",
        max_iterations=2
    )
    
    # Register modules BEFORE starting
    print("\n[1] Registering modules (before start)...")
    loop.register_module(ClockModule())
    loop.register_module(PrintModule())
    
    # Start the loop
    print("\n[2] Starting loop...")
    loop.start()
    
    # Let it run
    print("    Running...")
    time.sleep(4)
    
    # Stop the loop
    print("\n[3] Stopping loop...")
    loop.stop()
    
    # Check context
    ctx = loop.get_context()
    print(f"\nTotal executions: {len(ctx.get_execution_history())}")
    
    print("\nStart/Stop test complete!")


if __name__ == "__main__":
    # Run start/stop test first (no LLM needed)
    test_simple_start_stop()
    
    # Then run context test
    test_context_only()
    
    # Run LLM test
    # test_with_real_llm()  # Commented out - uncomment if LLM server is running
