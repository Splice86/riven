"""Sockets for Riven - multiple entry points to core instances."""

from sockets.base import SocketBase
from sockets.cli import CLISocket

__all__ = ["SocketBase", "CLISocket"]