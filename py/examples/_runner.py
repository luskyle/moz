"""Run an OpenSCAD example through the moz_openscad Python API."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "py") not in sys.path:
    sys.path.insert(0, str(ROOT / "py"))

import moz_openscad as moz


def run(relative_scad: str, output_name: str | None = None):
    source = ROOT / "3rd" / "openscad" / "examples" / relative_scad
    geometry = moz.eval_file(str(source))
    print(f"{relative_scad}: dimension={geometry.dimension}")
    if output_name is None:
        output_name = source.stem.lower().replace("-", "_")
    output_dir = ROOT / "build" / "out" / source.parent.name.lower()
    output_dir.mkdir(parents=True, exist_ok=True)
    if geometry.dimension == 3:
        output = output_dir / f"{output_name}.stl"
        geometry.export("binstl", str(output))
    elif geometry.dimension == 2:
        output = output_dir / f"{output_name}.svg"
        geometry.export("svg", str(output))
    else:
        print(f"{relative_scad}: no exportable geometry")
        return geometry
    print(f"exported: {output}")
    return geometry
