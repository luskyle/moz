import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _direct import build_example

def build():
	print("echo: Python function values")
	return build_example("Functions/echo")

if __name__ == "__main__":
	build().show(title="moz - Functions/echo")
