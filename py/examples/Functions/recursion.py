import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz


def factorial(n):
	return 1 if n == 0 else factorial(n - 1) * n

def build():
	return moz.color(moz.text(f"6! = {factorial(6)}", halign="center"), "Cyan")

if __name__ == "__main__":
	build().show(title="moz - Functions/recursion")
