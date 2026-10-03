#!/usr/bin/env python3
"""Portable entry point; keeps the CLI exit code and needs no pip installation."""
import sys

if sys.version_info < (3, 11):
    sys.exit("BeamFix requires Python 3.11 or later.")
from beamfix.cli import main

raise SystemExit(main())
