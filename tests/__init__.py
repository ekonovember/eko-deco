"""Test package bootstrap.

The library lives under ``src/`` (src layout), so it is importable only after
an install. The suite is meant to run straight out of a checkout with **no
install and no third-party packages** — ``python -m unittest discover -s tests``
— so put ``src/`` on ``sys.path`` here, once, for every test module.

An installed ``deco`` (``pip install -e .``) still wins nothing and loses
nothing: the checkout's ``src/`` is prepended, which is the copy you are
editing and the one you want under test.
"""

from __future__ import annotations

import os
import sys

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
