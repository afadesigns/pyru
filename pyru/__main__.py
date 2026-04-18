"""Run `python -m pyru` to launch the CLI without the console script."""

from __future__ import annotations

import sys

from pyru.cli import main

if __name__ == "__main__":
    sys.exit(main())
