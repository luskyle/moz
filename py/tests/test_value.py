"""取值通道（value/number/vector）与逐比特三角函数。"""

import math

import pytest


def test_value_full_precision(moz):
    # echo()/str() 只有 6 位有效数字；取值通道按 17 位输出
    assert moz.value("1/3") == "0.33333333333333331"


def test_number(moz):
    assert moz.number("sqrt(2)") == pytest.approx(math.sqrt(2))
    assert moz.number("2 + 3") == 5.0


def test_number_rejects_non_number(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.number('"abc"')


def test_vector(moz):
    values = moz.vector("rands(0, 1, 5, 42)")
    assert len(values) == 5
    assert all(0.0 <= v <= 1.0 for v in values)


def test_vector_rejects_non_vector(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.vector("1 + 1")


def test_value_uses_source_scope(moz):
    assert moz.number("x * 2", "x = 21;") == 42.0
    assert moz.vector("f(3)", "function f(a) = [a, a * a];") == [3.0, 9.0]


def test_value_undef_raises(moz):
    with pytest.raises(moz.OpenSCADError):
        moz.value("no_such_function(1)")


def test_trig_matches_scad_exact_constants(moz):
    assert moz.sin_deg(30) == 0.5
    assert moz.cos_deg(60) == 0.5
    assert moz.sin_deg(45) == math.sqrt(0.5)
    assert moz.tan_deg(45) == 1.0
    assert moz.sin_deg(90) == 1.0


def test_inverse_trig_snaps_to_integers(moz):
    assert moz.acos_deg(-1) == 180.0
    assert moz.asin_deg(0.5) == 30.0
    assert moz.atan_deg(1) == 45.0
    assert moz.atan2_deg(1, 1) == 45.0


def test_lookup_matches_scad_formula(moz):
    # SCAD 是 high_v * f + low_v * (1 - f)，末位与直觉写法可能不同
    assert moz.lookup(20, [[0, 0], [40, 4]]) == 2.0
