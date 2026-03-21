"""Continuous agent with message queue."""

import argparse
import asyncio
import logging
import sys

from core import Core
from modules.messaging import queue
from modules.time import get_time_module
from modules.documents import get_documents_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'  # Simple format
)

# Suppress httpx and openai HTTP logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)




async def on_llm_message(message: str):
    """Callback for when LLM sends a message."""
    print(f"\nLLM Says: {message}\n", flush=True)

# Register the callback
queue.on_outbox(on_llm_message)


async def user_input_loop():
    """Handle user input to post messages to queue."""
    while True:
        try:
            user_input = input("\nYou (Enter to post, /quit to exit): ").strip()
            
            if user_input.lower() in ["/quit", "/exit"]:
                print("Goodbye!")
                break
            
            # Post message to queue
            if user_input:
                await queue.put(user_input)
                print(f"Posted to queue: {user_input}", flush=True)
            else:
                # Just show queue status
                count = await queue.inbox_count()
                print(f"Queue: {count} message(s) waiting")
                
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n👋 Interrupted. Goodbye!")
            break


async def main():
    """Run the continuous agent."""
    parser = argparse.ArgumentParser(description="riven - Continuous Agent")
    parser.add_argument("--model", default="llama3", help="Model name")
    parser.add_argument("--url", default="http://192.168.1.11:8010", help="LLM URL")
    parser.add_argument("--max-iterations", type=int, default=10, help="Max iterations")
    parser.add_argument("--timeout", type=int, default=60, help="Shell timeout")
    parser.add_argument("--debug", action="store_true", help="Show debug output")
    
    args = parser.parse_args()
    
    print("🐶 riven - Continuous Agent")
    print("=" * 40)
    print("Enter messages to post to the agent queue.")
    print("The agent will poll for messages and respond.")
    print("Commands:")
    print("  /quit - Exit")
    print("=" * 40)
    
    # Create core
    core = Core(
        model=args.model,
        max_iterations=args.max_iterations,
        llm_url=args.url,
    )
    # Register modules first (so context tags work)
    core.register_module(get_time_module())
    core.register_module(get_documents_module())
    core.register_shell(timeout=args.timeout)
    core.register_messaging()
    core.register_control()
    
    # Set system prompt after modules (for tag replacement)
    core.set_system_prompt("""You are riven, a helpful AI assistant.

Current time: {{time}}

Open documents:
{{documents}}

When the user sends messages, they go into a message queue.
Use the check_messages and get_message tools to retrieve waiting messages.

IMPORTANT: When responding to the user, you MUST use the send_message tool. 
Never output text directly - always use send_message to send your response.

Always check for new messages first!
""")
    

    
    # Start the agent in background thread
    core.start(reason="Initial startup - check for any pending messages and respond using send_message tool.")
    
    # Run user input loop
    await user_input_loop()
    
    # Clean up
    core.stop()


if __name__ == "__main__":
    asyncio.run(main())
