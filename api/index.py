"""Vercel entry point — exposes server.app as the WSGI handler.

The Vercel Python runtime auto-detects a WSGI callable named `app` and
serves all incoming requests through it. Templates and static files
resolve relative to server.py (project root), which Vercel includes in
the function bundle.
"""

import sys
import pathlib

# Vercel runs functions with cwd = repo root, but make sure server.py and
# its sibling modules are importable regardless of how the runtime invokes us.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import app  # noqa: E402  (sys.path tweak above)
