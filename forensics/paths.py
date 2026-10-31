"""Path validation shared by the read-only forensics scripts.

Each script is run by an operator who names an explicit local file on the
command line. Resolve that value once here so the rest of the code only ever
opens a real, existing regular file.
"""
from __future__ import annotations

import os


def readable_file(value: str, label: str = "input file") -> str:
    """Return the real path of an existing regular file, or exit with a message."""
    path = os.path.realpath(value)
    if not os.path.isfile(path):
        raise SystemExit("%s is not an existing regular file: %s" % (label, value))
    return path
