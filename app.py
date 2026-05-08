"""Vercel Flask entry — re-exports server.app at the project root.

The Flask framework preset looks for `app` at the repo root and serves
everything through it as a WSGI app. Templates and static/ live next to
server.py (also at the root) so they resolve correctly.
"""

from server import app  # noqa: F401
