"""求值 / 导出 / dump 的测试。"""

import struct

import pytest


def test_binstl_export_roundtrip(moz, tmp_path):
    out = tmp_path / "cube.stl"
    moz.eval_text("cube(10);").export("binstl", str(out))
    data = out.read_bytes()
    assert struct.unpack_from("<I", data, 80)[0] == 12


def test_export_bytes_binstl_count(moz):
    assert struct.unpack_from("<I", moz.eval_text("sphere(5, $fn = 64);").export_bytes("binstl"), 80)[0] > 0


def test_export_dimension_mismatch(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.eval_text("cube(1);").export_bytes("svg")       # 3D → 2D 格式
    with pytest.raises(moz.OpenSCADError):
        moz.eval_text("circle(1);").export_bytes("binstl")  # 2D → 3D 格式


def test_export_unknown_format(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.eval_text("cube(1);").export_bytes("nope")


def test_text_format_rejected_by_export(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.eval_text("cube(1);").export_bytes("csg")


def test_export_options_accepted(moz):
    data = moz.eval_text("circle(2);").export_bytes("svg", source_file_name="a.svg", source_file_path="/a.svg")
    assert b"<svg" in data


def test_eval_error_surfaces(moz):
    with pytest.raises(moz.OpenSCADError) as excinfo:
        moz.eval_text("this is not scad (((")
    assert str(excinfo.value).strip()


def test_undefined_variable_warns_but_evaluates(moz):
    g = moz.eval_text("cube(1);")
    assert g.dimension == 3


def test_dump_formats(moz):
    assert "cube" in moz.dump("cube(2);", "csg")
    assert "cube" in moz.dump("cube(2);", "ast")
    assert moz.dump('echo("hi");', "echo").strip() == '"hi"'
    with pytest.raises(moz.OpenSCADError):
        moz.dump("cube(1);", "nope")


def test_dump_docname_accepted(moz):
    assert moz.dump("cube(1);", "ast", docname="/abs/x.scad").strip()


def test_dump_file(moz, tmp_path):
    src = tmp_path / "m.scad"
    src.write_text("cube(3);\n")
    assert "cube" in moz.dump_file(str(src), "csg")


def test_eval_file(tmp_path, moz):
    src = tmp_path / "m.scad"
    src.write_text("cube([2, 3, 4]);\n")
    assert moz.eval_file(str(src)).measure.volume == pytest.approx(24.0)


def test_render_png_bytes(moz):
    data = moz.eval_text("cube(4, $fn = 8);").render_png_bytes(64, 64)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_log_captures_echo(moz):
    g = moz.eval_text('echo("hello", 42);\ncube(1);')
    assert 'ECHO: "hello", 42' in g.log
    assert g.take_log().strip()          # 读取后清空
    assert g.log.strip() == ""
