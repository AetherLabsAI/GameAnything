"""`python -m gameanything ...` = `gameanything ...` (bin/gameanything uses it when neither a .venv nor uv is there)."""
import sys

from .cli import main

sys.exit(main())
