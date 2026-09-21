"""库搜索路径（add_library_path / library_paths）与导出选项。"""


def test_library_paths_include_resource_libraries(moz):
    paths = moz.library_paths()
    assert paths
    assert any("libraries" in p for p in paths)


def test_add_library_path_appends(moz, tmp_path):
    before = moz.library_paths()
    moz.add_library_path(str(tmp_path))
    after = moz.library_paths()
    assert str(tmp_path) in after
    assert len(after) == len(before) + 1


def test_add_library_path_ignores_empty(moz):
    before = len(moz.library_paths())
    moz.add_library_path("")
    assert len(moz.library_paths()) == before


def test_use_library_from_added_path(moz, tmp_path):
    """加进搜索路径的库能被 use <> 找到。"""
    (tmp_path / "lib.scad").write_text("module marker() { cube(2); }\n")
    moz.add_library_path(str(tmp_path))
    g = moz.eval_text("use <lib.scad>\nmarker();")
    assert g.measure.volume > 0
