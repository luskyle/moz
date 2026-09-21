import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _direct import build_example

def build():
	return build_example("Advanced/assert")

if __name__ == "__main__":
	build().show(title="moz - Advanced/assert")
