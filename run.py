"""Launcher: python run.py [--base URL] [--dry-run]

Local, single-operator game-state server. Speaks MCP over stdio and talks only to the
loopback bridge inside the operator's own game client (default 127.0.0.1:8787).
"""
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'mcgg_mcp'))
from mcgg_mcp.server import main
if __name__ == '__main__':
    raise SystemExit(main())
