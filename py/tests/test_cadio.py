"""libmozcadio.so（LibreCAD 的 libdxfrw 抽取）的用例。

重点不是"几何算得对"（那是 ``py/moz_dxf.py`` 的活），而是：**图元读得全、读得对、
差异有解释**——所以核心是两个交叉核对（与 ezdxf 的模型空间逐类对比）和错误路径。

坐标/数量的基准来自 ``scripts/make_dxf_samples.py`` 生成的样例（手算验收值见
``py/tests/test_dxf.py`` 的模块文档）。
"""

import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRAWINGS = ROOT / "py" / "moz_data" / "drawings"
LIBDXFRW = ROOT / "3rd" / "librecad" / "libraries" / "libdxfrw"
CORPUS = ROOT / "corpus" / "dxf"


@pytest.fixture(scope="module")
def cadio():
    """导入 moz_cadio；libmozcadio.so 缺失/不可用时跳过本模块。"""
    mod = pytest.importorskip("moz_cadio")
    try:
        mod.read(str(DRAWINGS / "plate.dxf"))
    except mod.CadIoError as exc:
        pytest.skip(f"libmozcadio.so 不可用：{str(exc)[:120]}")
    return mod


def modelspace(cad):
    """模型空间实体（``owner`` 为空）；块定义里的实体另有 owner。"""
    return [entity for entity in cad.entities if entity.owner == ""]


def kinds(entities):
    counts = {}
    for entity in entities:
        counts[entity.kind] = counts.get(entity.kind, 0) + 1
    return counts


# --- 与我们自己的样例对拍 ---


def test_reads_plate_with_expected_geometry(cadio):
    cad = cadio.read(str(DRAWINGS / "plate.dxf"))
    assert cad.format == "dxf"
    assert cad.version == "AC1009"
    assert kinds(modelspace(cad)) == {"CIRCLE": 4, "DIMENSION": 2, "LINE": 8}
    circles = sorted(cad.by_kind("CIRCLE"), key=lambda e: (e.p1[0], e.p1[1]))
    assert [(c.p1[0], c.p1[1], c.radius) for c in circles] == [
        (20.0, 20.0, 5.0), (55.0, 20.0, 5.0), (60.0, 50.0, 5.0), (100.0, 20.0, 5.0)]


def test_block_contents_are_kept_and_tagged(cadio):
    """块定义里的实体也要留（渲染 INSERT 要用），并用 owner 标明归属。

    样例里的 ``*D1``/``*D2`` 是标注自带的匿名块、``_CLOSEDFILLED`` 是箭头块。
    """
    cad = cadio.read(str(DRAWINGS / "plate.dxf"))
    owners = {entity.owner for entity in cad.entities if entity.owner}
    assert {"*D1", "*D2", "_CLOSEDFILLED"} <= owners
    assert {block.name for block in cad.blocks} >= {"*D1", "*D2", "_CLOSEDFILLED"}
    assert cad.by_kind("SOLID")          # 箭头在块里，模型空间里没有


def test_polyline_bulges_and_closure(cadio):
    cad = cadio.read(str(DRAWINGS / "bracket.dxf"))
    (slot,) = cad.by_kind("LWPOLYLINE")
    assert slot.closed
    assert len(slot.points) == 8                    # 4 个顶点，x,y 交错
    assert list(slot.bulges) == [0.0, 1.0, 0.0, 1.0]
    assert slot.xy(0) == (25.0, 20.0)


def test_units_version_and_layer_flags(cadio):
    cad = cadio.read(str(DRAWINGS / "bracket.dxf"))
    assert cad.version == "AC1015"
    assert cad.insunits == 4 and cad.units_name == "mm"
    layers = cad.layer_map()
    assert {"OUTLINE", "CENTER", "HIDDEN", "DIM"} <= set(layers)
    assert layers["CENTER"].linetype is not None    # 中心线有自己的线型
    assert not layers["OUTLINE"].off


def test_extents_sentinel_is_not_reported(cadio):
    """DXF 用 ±1e20 表示"范围未设置"——不能当真的包围盒报出来（样例就是这种）。"""
    for name in ("plate", "bracket", "messy"):
        assert cadio.read(str(DRAWINGS / f"{name}.dxf")).extents is None


def test_dimension_text_is_the_named_dimension(cadio):
    """标注的文字覆盖就是 ``dxf_dim(file, name)`` 认的那一列（P1 参数表同一来源）。"""
    cad = cadio.read(str(DRAWINGS / "plate.dxf"))
    dims = cad.by_kind("DIMENSION")
    assert {dim.text for dim in dims} == {"bodywidth", "plateheight"}
    assert all(dim.dim_kind == "linear" for dim in dims)


# --- 与 ezdxf 交叉核对（同一个文件两条独立实现） ---


@pytest.mark.parametrize("name", ["plate", "bracket", "messy"])
def test_modelspace_matches_ezdxf(cadio, name):
    ezdxf = pytest.importorskip("ezdxf")
    path = DRAWINGS / f"{name}.dxf"
    cad = cadio.read(str(path))
    document = ezdxf.readfile(str(path))

    theirs = {}
    for entity in document.modelspace():
        theirs[entity.dxftype()] = theirs.get(entity.dxftype(), 0) + 1
    assert kinds(modelspace(cad)) == theirs

    assert {layer.name for layer in cad.layers} == {layer.dxf.name for layer in document.layers}

    mine = {dim.text for dim in cad.by_kind("DIMENSION")}
    expected = {dim.dxf.text for dim in document.modelspace().query("DIMENSION")}
    assert mine == expected


def test_circle_coordinates_match_ezdxf(cadio):
    ezdxf = pytest.importorskip("ezdxf")
    path = DRAWINGS / "plate.dxf"
    cad = cadio.read(str(path))
    document = ezdxf.readfile(str(path))
    mine = sorted((round(c.p1[0], 6), round(c.p1[1], 6), round(c.radius, 6))
                  for c in cad.by_kind("CIRCLE"))
    theirs = sorted((round(c.dxf.center.x, 6), round(c.dxf.center.y, 6), round(c.dxf.radius, 6))
                    for c in document.modelspace().query("CIRCLE"))
    assert mine == theirs


# --- 格式覆盖面与错误路径 ---


def test_vendored_ascii_sample(cadio):
    cad = cadio.read(str(LIBDXFRW / "screw2012ascii.DXF"))
    assert kinds(cad.entities) == {"LINE": 23, "ARC": 4}
    assert cad.version == "AC1021"


@pytest.mark.parametrize("name,expected", [("bin_dxf_r12.dxf", {"LINE": 3}),
                                           ("bin_dxf_r13.dxf", {"LINE": 3}),
                                           ("bin_dxf_r14.dxf", {"LINE": 3}),
                                           ("bin_dxf_r2000.dxf", {"TEXT": 1})])
def test_binary_dxf_is_supported(cadio, name, expected):
    """二进制 DXF 由 libdxfrw 自己识别（哨兵串 "AutoCAD Binary DXF"）；R12–2000 都读得出来。

    上游 2.0.0 把 R12 的二进制也修好了（树里那份 0.5.11 读不了它）。
    """
    path = CORPUS / "ezdxf" / f"integration_tests__data__{name}"
    if not path.exists():
        pytest.skip(f"语料缺失：{name}")
    assert kinds(cadio.read(str(path)).entities) == expected


def test_vendored_binary_sample_is_unreadable_and_says_so(cadio):
    """上游自带的二进制样本，**它的对象段两个版本的 libdxfrw 都读不了**。

    0.5.11 报 BAD_READ_SECTION、2.0.0 报 BAD_READ_OBJECTS（ezdxf 读它没问题、27 个实体，
    文件本身完整：ENDSEC + EOF 都在）。我们的态度是**整体报错**，不静默给半个图。
    """
    with pytest.raises(cadio.CadIoError) as info:
        cadio.read(str(LIBDXFRW / "screw2012binary.dxf"))
    assert "BAD_READ_OBJECTS" in str(info.value)


def test_ancient_dwg_version_is_refused_with_reason(cadio, tmp_path):
    """上游只支持 R1.40–2018+；R2.5 及更早的几个古董版本没有读取器——要明确说清，不读成空图。"""
    for tag in ("MC0.0", "AC1002"):
        fake = tmp_path / f"{tag}.dwg"
        fake.write_bytes(tag.encode() + b"\0" * 256)
        with pytest.raises(cadio.CadIoError) as info:
            cadio.read(str(fake))
        message = str(info.value)
        assert tag in message and "没有可用的读取器" in message


def test_supported_but_bogus_dwg_is_not_reported_as_unsupported(cadio, tmp_path):
    """AC1032（2018+）**是支持**的：一个内容为空壳的 AC1032 文件要报读失败，而不是报"版本不支持"。"""
    fake = tmp_path / "hollow.dwg"
    fake.write_bytes(b"AC1032" + b"\0" * 256)
    with pytest.raises(cadio.CadIoError) as info:
        cadio.read(str(fake))
    message = str(info.value)
    assert "AC1032" in message and "BAD_READ_FILE_HEADER" in message
    assert "没有可用的读取器" not in message


def test_decimal_comma_is_refused_like_the_other_paths(cadio, moz):
    """小数写成逗号的图：libdxfrw 直接拒绝（BAD_READ_HEADER），不拿截断出来的几何冒充结果。

    同一个文件在 ``py/moz_dxf.py``（ezdxf 路径）也是拒绝、引擎的 ``import()`` 是空几何——
    三条路径态度一致。
    """
    path = ROOT / "3rd" / "openscad" / "testdata" / "dxf" / "nothing-decimal-comma-separated.dxf"
    with pytest.raises(cadio.CadIoError) as info:
        cadio.read(str(path))
    assert "BAD_READ_HEADER" in str(info.value)

    moz_dxf = pytest.importorskip("moz_dxf")
    pytest.importorskip("ezdxf")
    with pytest.raises(moz.OpenSCADError):
        moz_dxf.read_dxf(str(path))


def test_missing_file_raises(cadio, tmp_path):
    with pytest.raises(cadio.CadIoError, match="找不到文件"):
        cadio.read(str(tmp_path / "nope.dxf"))


def test_report_and_helpers(cadio):
    cad = cadio.read(str(DRAWINGS / "messy.dxf"))
    text = cad.report()
    assert "格式：dxf" in text and "图层：" in text
    assert cad.by_layer()["OUTLINE"]                 # 按图层分组
    assert kinds(modelspace(cad))["LINE"] == 12      # 模型空间 12 条线
    assert cad.counts()["LINE"] == 16                # 加上标注匿名块里的 4 条
    assert isinstance(cad.ignored(), list)


@pytest.mark.parametrize("path", ["py/moz_data/drawings/plate.dxf",
                                  "corpus/dxf/local/imu_to_dxl-board-45x22-R2.dxf"])
def test_reads_real_corpus_without_crashing(cadio, path):
    cad = cadio.read(str(ROOT / path))
    assert cad.entities and not cad.format.startswith("UNKNOWN")


# --- DWG（真实样本：ACadSharp 的版本阶梯 + libdxfrw 自己的 fixtures） ---

DWG = ROOT / "corpus" / "dwg"


def dwg(name):
    """按扁平化文件名在各来源子目录里找（corpus/dwg/<来源>/<同名文件>）。"""
    matches = sorted(DWG.glob(f"*/{name}"))
    if not matches:
        pytest.skip(f"DWG 语料缺失：{name}（scripts/fetch_dwg_samples.py）")
    return str(matches[0])


@pytest.mark.parametrize("version", ["AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027"])
def test_dwg_version_ladder(cadio, version):
    """同一张图的 6 个版本：每个都要读得出来，内容也要像（这是 DWG 侧的核心验收）。

    一次盯住 dwgReader15/18/21/24/27 五个读取器——树里那份 0.5.11 在 AC1018+ 上全军覆没。
    """
    cad = cadio.read(dwg(f"samples__sample_{version}.dwg"))
    assert cad.format == "dwg" and cad.version == version
    counts = kinds(modelspace(cad))
    assert {"TEXT", "LINE", "LWPOLYLINE", "DIMENSION"} <= set(counts)
    assert len(cad.layers) >= 19 and len(cad.blocks) >= 20
    assert len(modelspace(cad)) > 100


def test_dwg_versions_agree_with_each_other(cadio):
    """同一张图的 6 个版本实体数应当接近（版本口径差异不该超过 10%）。"""
    sizes = [len(modelspace(cadio.read(dwg(f"samples__sample_{version}.dwg"))))
             for version in ("AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027")]
    assert min(sizes) > 0
    assert (max(sizes) - min(sizes)) / max(sizes) < 0.10, sizes


def test_dwg_2018_is_supported(cadio):
    """2018+（AC1032）也读得出来——上游 2.0.0 的 dwgreader32；0.5.11 时代完全没有。"""
    cad = cadio.read(dwg("tests__fixtures__dwg__mpolygon_solid.dwg"))
    assert cad.format == "dwg" and cad.version == "AC1032"
    assert kinds(modelspace(cad)) == {"HATCH": 1}


def test_dwg_encoding_page_sample(cadio):
    """带编码页的 DWG（ANSI932）也要读得出来（文字串按对应码页解码）。"""
    cad = cadio.read(dwg("tests__fixtures__dwg__ordinary_enc_ac1027_ansi932.dwg"))
    assert cad.version == "AC1027"
    assert kinds(modelspace(cad)) == {"LINE": 3}


def test_dwg_insert_names_are_not_truncated(cadio):
    """块参照的块名必须是**块定义里真有的名字**：DWG 侧上游会给出被截断的匿名占位名。

    实测 `samples__sample_AC1015.dwg`：上游在实体到达时按"块记录句柄"查表，11 个块参照拿到
    `*T`/`*U` 这种两字符占位名（真名是 `*T9`，表里还没有），于是查不到块定义、整块画不出来。
    我们在读完整张图后按句柄重查一遍（见 3rd/libdxfrw/moz/moz_cadio.cc 的 resolve_pending）。
    """
    cad = cadio.read(dwg("samples__sample_AC1015.dwg"))
    definitions = {block.name for block in cad.blocks}
    names = [entity.name for entity in cad.entities if entity.kind == "INSERT"]
    assert names, "这张图应当有块参照"
    assert all(name in definitions for name in names), \
        f"仍有指向不存在块定义的块参照：{sorted(set(names) - definitions)}"
    assert "*T9" in definitions and "*T9" in set(names)


def test_hatch_curve_warnings_are_aggregated(cadio):
    """剖面线边界曲线的"仅为显示"通知要**汇成一行带计数**，不能每个剖面线来一条。

    实测 `api-cw750-details.dxf`：87 个剖面线里有 71 个带曲线边界，以前在面板里刷 71 条
    同声（去重后只有 5 种 N 值，没有别的信息量），现在是一行。
    """
    path = CORPUS / "dxf-parser" / "samples__data__api-cw750-details.dxf"
    if not path.exists():
        pytest.skip("DXF 语料缺失")
    cad = cadio.read(str(path))
    assert len(cad.by_kind("HATCH")) >= 80
    assert len(cad.warnings) <= 2, cad.warnings[:5]
    assert not [text for text in cad.warnings if "剖面线边界含 " in text]  # 旧的逐条消息没了
    assert any("个剖面线边界含曲线段" in text for text in cad.warnings)    # 汇成一行带计数了


def test_hatch_spline_edges_are_sampled_like_spline_entities(cadio):
    """剖面线边界里的**样条边**要真正画出来，且与 SPLINE 实体同一条曲线。

    实测 ezdxf 的 `examples_dxf__hatches_2.dxf` 就带一条样条边（DXF 内联边记录：72=4）。
    以前这段被跳过，环上留一个横跨样条的大缺口；现在用与 `py/moz_cadio.py::spline_points`
    相同的（有理）de Boor 求值采样——**逐点对照两条路径必须同一条曲线**。
    """
    path = CORPUS / "ezdxf" / "examples_dxf__hatches_2.dxf"
    if not path.exists():
        pytest.skip("DXF 语料缺失")
    vals = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()]

    def read_first_spline_edge():
        start = next(i for i, line in enumerate(vals)
                     if line == "72" and vals[i + 1] == "4")
        edge = {}
        j = start + 2
        while j < len(vals) and vals[j] not in ("72", "97"):
            code = vals[j]
            value = vals[j + 1]
            try:
                edge.setdefault(code, []).append(float(value))
            except ValueError:
                pass
            j += 2
        return edge

    edge = read_first_spline_edge()
    degree = int(edge["94"][0])
    knots = tuple(edge["40"])
    controls = [(x, y) for x, y in zip(edge["10"], edge["20"], strict=True)]
    assert len(knots) == len(controls) + degree + 1

    expected = cadio.spline_points(cadio.Entity(      # Python 侧同一算法
        kind="SPLINE", layer="0", degree=degree, flags=0, knots=knots,
        points=tuple(v for pair in controls for v in pair)))
    assert len(expected) == max(16, 8 * len(controls)) + 1

    cad = cadio.read(str(path))
    best = None
    for hatch in cad.by_kind("HATCH"):
        for loop in hatch.loop_points():
            for index in range(0, len(loop) - len(expected) + 1):
                segment = loop[index:index + len(expected)]
                delta = (math.dist(segment[0], expected[0])
                         + math.dist(segment[-1], expected[-1]))
                if best is None or delta < best[0]:
                    best = (delta, segment)
    assert best is not None, "环里应该有这条样条款"
    _delta, segment = best
    assert all(math.dist(a, b) < 1e-9 for a, b in zip(segment, expected, strict=True)), \
        "C++ 侧采样与 Python spline_points 必须同一条曲线"
    steps = sorted(math.dist(segment[i], segment[i + 1]) for i in range(len(segment) - 1))
    assert steps[-1] < 5 * steps[len(steps) // 2], "没有横跨样条的大缺口"
    assert not any("样条段" in text or "空的" in text for text in cad.warnings), \
        "样条边已经采样了，不该再有'这截是空的'的通知"


def test_helix_is_drawn_from_axis_and_turns(cadio, tmp_path):
    """HELIX（螺旋）：上游给了轴基点/起点/轴向量/半径/圈数，按它采样成折线画出来。

    以前它和 MLINE/MLEADER 一样被接口的**默认空实现**静默丢掉。这里手写最小 DXF 钉住几何：
    轴是 (0,0,1)、起点 (1,0,0)、半径 5 → 每个点到轴基点的 xy 距离都应当是 5（垂直轴的螺旋
    在 xy 上就是个圆，2D 投影）。
    """
    knots = "".join(f"40\n{value}\n" for value in (0, 0, 0, 0, 1, 1, 1, 1))
    controls = "".join(f"10\n{x}\n20\n{y}\n30\n0\n"
                       for x, y in ((0, 0), (1, 0), (2, 1), (3, 1)))
    body = ("71\n3\n72\n8\n73\n4\n" + knots + controls
            + "100\nAcDbHelix\n90\n29\n91\n0\n10\n0\n20\n0\n30\n0\n"
              "11\n1\n21\n0\n31\n0\n12\n0\n22\n0\n32\n1\n40\n5\n41\n3\n42\n1\n")
    path = tmp_path / "helix.dxf"
    path.write_text("0\nSECTION\n2\nENTITIES\n0\nHELIX\n8\n0\n100\nAcDbSpline\n70\n0\n"
                    + body + "0\nENDSEC\n0\nEOF\n", encoding="utf-8")
    cad = cadio.read(str(path))
    assert not cad.warnings
    helix, = modelspace(cad)
    assert helix.kind == "HELIX" and helix.flags & cadio.FLAG_APPROX
    assert (helix.radius, helix.height) == (5.0, 3.0)           # 半径、圈数
    points = [helix.xy(i) for i in range(len(helix.points) // 2)]
    assert len(points) > 100                                    # 每圈 48 段、3 圈
    assert all(abs(math.hypot(x, y) - 5.0) < 1e-9 for x, y in points)
    assert len(cadio.entity_polylines(helix)) == 1


def test_dxf_mleader_only_drawing_is_not_blank(cadio):
    """模型空间里**只有 MLEADER** 的图（语料实测 `dxf-parser/test__data__mleader.dxf`）。

    以前这些实体被接口的默认空实现吞掉，整张图判成"空白"；现在它算画得出来，文字也在。
    """
    path = CORPUS / "dxf-parser" / "test__data__mleader.dxf"
    if not path.exists():
        pytest.skip("DXF 语料缺失")
    cad = cadio.read(str(path))
    leaders = modelspace(cad)
    assert leaders and all(entity.kind == "MLEADER" for entity in leaders)
    assert any((entity.text or "").strip() for entity in leaders)


def test_dwg_entity_families_are_drawn(cadio):
    """MESH/MLINE/MLEADER/WIPEOUT/UNDERLAY/SHAPE/IMAGE 从"只报数量"变成**真画出来**。

    这是 ACadSharp 那张版本阶梯样本（每张都含 15 个 MLEADER、3 个 MLINE、2 个 MESH…）：
    `DRW_Interface` 里这些回调有默认空实现，不覆盖就是静默丢几何。这里逐族钉住读到的几何。
    """
    cad = cadio.read(dwg("samples__sample_AC1015.dwg"))
    assert not cad.warnings, cad.warnings
    assert {"MESH", "MLINE", "MLEADER", "WIPEOUT", "UNDERLAY", "SHAPE", "IMAGE"} <= set(
        kinds(modelspace(cad)))

    # 多线：展开成 N 条平行线，实测两条线在**每个顶点**都相隔一个 scale（标准样式 ±0.5 偏移）
    mlines = cad.by_kind("MLINE")
    assert len(mlines) == 3
    for mline in mlines:
        loops = [loop for loop in mline.loop_points() if len(loop) > 1]
        assert len(loops) == 2
        for first, second in zip(loops[0], loops[1], strict=True):
            assert math.dist(first, second) == pytest.approx(mline.height, rel=1e-9)

    # 网格：按去重后的边画线框（每条边两个点）
    for mesh in cad.by_kind("MESH"):
        assert mesh.nloops > 100 and all(len(loop) == 2 for loop in mesh.loop_points())

    # 多重引线：文字内容读到了（引线折点上游没给，见 docs/third-party.md）
    assert sum(1 for entity in cad.by_kind("MLEADER") if entity.text) == 15

    # 图片：整幅边框（5 点闭环）+ 名字来自 IMAGEDEF
    image, = cad.by_kind("IMAGE")
    assert len(image.points) // 2 == 5 and image.name.lower().endswith(".jpg")

    # 遮罩：裁剪边界是闭合多边形（像素坐标已映射到 WCS）
    wipeout, = cad.by_kind("WIPEOUT")
    assert len(wipeout.points) // 2 == 5 and wipeout.nloops == 1
    assert wipeout.points[0:2] == wipeout.points[-2:]           # 首尾同点 = 闭合

    # 底图参照：裁剪边界/十字标记 + 外部文件名（定义对象后到 → 读完再解析）
    underlay, = cad.by_kind("UNDERLAY")
    assert underlay.nloops >= 1 and underlay.name.lower().endswith(".pdf")
    assert underlay.flags & cadio.FLAG_APPROX

    # 形（SHAPE）：字形在外部 .shx 里，画的是插入点上的标记（标注里说明）
    shape, = cad.by_kind("SHAPE")
    assert shape.flags & cadio.FLAG_APPROX and len(shape.points) // 2 == 5
