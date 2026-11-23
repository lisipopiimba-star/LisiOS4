#!/usr/bin/python3 -I
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

sys.exit(core.cli(sys.argv))
