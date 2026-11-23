"""What a test may assume about the machine it runs on (Windows: symlinks need Developer Mode or an administrator, WinError 1314)."""
import os
import tempfile

import pytest


def can_symlink() -> bool:
    """True when this process may create symbolic links (always on Linux / macOS; on Windows only with Developer Mode or as admin)."""
    with tempfile.TemporaryDirectory() as d:
        try: os.symlink(os.path.join(d, "target"), os.path.join(d, "link")); return True
        except (OSError, NotImplementedError): return False


CAN_SYMLINK = can_symlink()
needs_symlinks = pytest.mark.skipif(not CAN_SYMLINK, reason="cannot create symlinks here (Windows without Developer Mode: WinError 1314)")
