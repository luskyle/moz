import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _direct import build_example

def build():
    return build_example("Old/example021")

if __name__ == "__main__":
    build().show(title="moz - Old/example021")
