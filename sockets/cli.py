"""CLI socket for interactive terminal."""

import sys
import threading
from sockets.base import SocketBase


class CLISocket(SocketBase):
    """Interactive CLI socket."""
    
    def __init__(self, core_name: str = None):
        super().__init__(session_strategy="new")
        self._core_name = core_name
        self._running = False
        self._input_thread: threading.Thread = None
    
    def run(self) -> None:
        """Run the CLI socket."""
        # Connect to core
        session = self.connect(core_name=self._core_name)
        print(f"Connected: {session}")
        print("Type /exit to quit\n")
        
        self._running = True
        
        # Start output poller
        def poll_output():
            while self._running:
                msgs = self.receive(timeout=0.5)
                for msg in msgs:
                    print(f"\n{msg}\n> ", end="")
                    sys.stdout.flush()
        
        output_thread = threading.Thread(target=poll_output, daemon=True)
        output_thread.start()
        
        # Input loop
        try:
            while self._running:
                user_input = input("> ").strip()
                
                if not user_input:
                    continue
                
                if user_input == "/exit":
                    break
                
                self.send(user_input)
        
        except (KeyboardInterrupt, EOFError):
            print("\nInterrupted")
        
        finally:
            self._running = False
            self.disconnect()
            print("Disconnected")


def main():
    """Run CLI socket."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Riven CLI Socket")
    parser.add_argument("--core", "-c", default="code_hammer", 
                        help="Core to use (default: code_hammer)")
    args = parser.parse_args()
    
    socket = CLISocket(core_name=args.core)
    socket.run()


if __name__ == "__main__":
    main()