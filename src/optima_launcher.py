"""Starts Optima without needing PYTHONPATH (some assistants ignore env settings).

    python /path/to/optima_launcher.py mcp
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optima.__main__ import main  # noqa: E402

main()
