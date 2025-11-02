"""Legacy setup.py shim.

Primary build configuration lives in `pyproject.toml`. This file remains to
support environments or tooling that still invoke `setup.py` directly.
"""

from setuptools import setup


if __name__ == "__main__":  # pragma: no cover
    setup()
