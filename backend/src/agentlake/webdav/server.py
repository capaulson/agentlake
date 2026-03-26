"""WebDAV server entry point.

Runs a WsgiDAV server that exposes the AgentLake vault as a mountable
network drive. Compatible with macOS Finder, Windows Explorer, and Linux.

Usage:
    python -m agentlake.webdav.server [--port 8008] [--host 0.0.0.0]

Mount on macOS:
    Finder → Go → Connect to Server → http://localhost:8008/

Mount on Windows:
    net use Z: http://localhost:8008/ /user:api test-admin-key

Mount on Linux:
    sudo mount -t davfs http://localhost:8008/ /mnt/agentlake
"""

from __future__ import annotations

import argparse
import os
import sys

import structlog

# Add backend src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logger = structlog.get_logger(__name__)


def create_app():
    """Create the WsgiDAV WSGI application."""
    from wsgidav.wsgidav_app import WsgiDAVApp
    from agentlake.webdav.provider import VaultProvider

    config = {
        "provider_mapping": {
            "/": VaultProvider(),
        },
        "verbose": 2,
        "logging": {
            "enable": True,
            "enable_loggers": ["wsgidav"],
        },
        # Authentication via AgentLake API keys
        "http_authenticator": {
            "domain_controller": None,  # We'll use a custom one
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        # Allow anonymous read for simplicity; protect writes with API key
        "simple_dc": {
            "user_mapping": {
                "*": {
                    "api": {"password": os.environ.get("DEFAULT_ADMIN_API_KEY", "test-admin-key")},
                    "admin": {"password": os.environ.get("DEFAULT_ADMIN_API_KEY", "test-admin-key")},
                },
            },
        },
        # Lock manager
        "lock_storage": True,
        # Read-only resources (system files)
        "dir_browser": {
            "enable": True,
            "response_trailer": "AgentLake WebDAV Server",
            "show_user": False,
        },
    }

    app = WsgiDAVApp(config)
    logger.info("webdav_app_created")
    return app


def main():
    parser = argparse.ArgumentParser(description="AgentLake WebDAV Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8008, help="Bind port")
    args = parser.parse_args()

    from cheroot.wsgi import Server as WSGIServer

    app = create_app()
    server = WSGIServer((args.host, args.port), app)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║          AgentLake WebDAV Server                         ║
║                                                          ║
║  Listening on: http://{args.host}:{args.port}/                   ║
║                                                          ║
║  Mount on macOS:                                         ║
║    Finder → Go → Connect to Server                       ║
║    → http://localhost:{args.port}/                              ║
║                                                          ║
║  Mount on Windows:                                       ║
║    net use Z: http://localhost:{args.port}/                     ║
║                                                          ║
║  Credentials: api / test-admin-key                       ║
║                                                          ║
║  Hooks active:                                           ║
║    ✓ Auto-process new files (GPT-5.4 pipeline)           ║
║    ✓ Folder analysis on change                           ║
║    ✓ Real-time UI sync (WebSocket)                       ║
║    ✓ Version tracking (DiffLog)                          ║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
        print("\nWebDAV server stopped.")


if __name__ == "__main__":
    main()
