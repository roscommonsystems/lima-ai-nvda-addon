import os
import sys

_LIMA_DIR = os.path.abspath(
	os.path.join(os.path.dirname(__file__), "..", "addon", "globalPlugins", "lima")
)
if _LIMA_DIR not in sys.path:
	sys.path.insert(0, _LIMA_DIR)
