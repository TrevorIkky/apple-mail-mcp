"""MCP server for reading Apple Mail on macOS."""

from .errors import ConfigError, MailError
from .server import build_server

__all__ = ["ConfigError", "MailError", "__version__", "build_server"]
__version__ = "0.1.0"
