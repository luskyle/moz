#!/usr/bin/env python3
"""验证**装好的** moz 是否自带齐全部运行时数据（打包 smoke test）。

它只用 site-packages 里的东西，所以要在**仓库之外**的目录、用装了 wheel 的解释器跑：

    bash scripts/build_wheel.sh
    python3 -m venv /tmp/mozvenv
    /tmp/mozvenv/bin/pip install build/dist/moz_openscad-*.whl
    cd /tmp && /tmp/mozvenv/bin/python <repo>/scripts/smoke_installed.py

覆盖的正是「打包时必须带上」的那几项：预编译的 `.so`、`color-schemes/*.json`（换配色会
渲染出不同图）、`fonts/`（引擎默认字体 + 自带中文字库）、`libraries/MCAD/fonts.scad`
（`use <MCAD/fonts.scad>`，靠引擎自动把 `<资源>/libraries` 加进搜索路径）、
`examples/` 下的 dxf/dat/stl/png/json。
"""

import os
import sys

import moz_openscad as moz


def main():
    print("python       :", sys.version.split()[0])
    print("moz 来自      :", os.path.dirname(moz.__file__))
    print("DATA_DIR     :", moz.DATA_DIR)
    if not (moz.DATA_DIR or "").endswith("moz_data"):
        raise SystemExit("DATA_DIR 不是随包分发的 moz_data —— 这个脚本要在装好的环境里跑")
    assert os.environ.get("MOZ_OPENSCAD_RESOURCE_DIR") == moz.DATA_DIR
    assert os.path.join(moz.DATA_DIR, "fonts") == os.environ["OPENSCAD_FONT_PATH"].split(os.pathsep)[-1]

    geometry = moz.eval_text("cube([10,20,30]);")
    print("求值         :", geometry.dimension, "D,", geometry.measure.facets, "面, 体积",
          geometry.measure.volume)
    assert geometry.measure.volume == 6000

    # 配色方案：引擎从 <资源>/color-schemes/render/*.json 读，换方案必须渲染出不同的图
    first = geometry.render_png_bytes(200, 150, colorscheme="Tomorrow")
    again = geometry.render_png_bytes(200, 150, colorscheme="Tomorrow")
    other = geometry.render_png_bytes(200, 150, colorscheme="Starnight")
    print("渲染 PNG     :", len(first), "字节 | 同配色一致:", first == again, "| 换配色不同:", first != other)
    assert first[:8] == b"\x89PNG\r\n\x1a\n"
    assert first == again and first != other, "配色方案没生效"
    assert "Unknown color scheme" not in geometry.log

    colors = moz.eval_text('color("red") cube(10);').face_colors()
    print("逐面颜色     :", len(colors), "字节, 首个 RGBA", tuple(colors[:4]))
    assert colors[:3] == b"\xff\x00\x00"

    # 引擎默认字体只有拉丁字形（中文变空心方框，每字 8 个面）；自带字库要能出真字形
    plain = moz.text("技术要求", size=10).eval().measure
    real = moz.text("技术要求", size=10, font="Moz Sans SC").eval().measure
    print("默认字体中文  :", plain.facets, "面（8/字 = 空心方框）| Moz Sans SC:", real.facets, "面")
    assert plain.facets == 8 * 4 and real.facets > 8 * 4

    for parts in [("examples", "Old", "example007.dxf"), ("examples", "Old", "example010.dat"),
                  ("examples", "Old", "example016.stl"), ("examples", "Basics", "projection.stl"),
                  ("examples", "Advanced", "surface_image.png"),
                  ("examples", "Parametric", "sign.json"), ("libraries", "MCAD", "fonts.scad")]:
        path = moz.data_path(*parts)
        assert os.path.exists(path), f"随包数据缺失: {path}"
    print("随包数据     :", moz.data_path("examples"))

    # use <MCAD/...>：不设 OPENSCADPATH，靠引擎的 <资源>/libraries
    source = "use <MCAD/fonts.scad>\n"
    table = moz.vector("8bit_polyfont()", source)
    indices = moz.vector('search("one", 8bit_polyfont()[2], 1, 1)', source)
    print("MCAD 字形表   :", len(table[2]), "项, search('one') =", indices)
    assert len(table[2]) == 256 and indices == [ord(c) for c in "one"]

    # 真的用随包数据跑几何：dxf 导入 + surface 高度图
    dxf = moz.data_path("examples", "Old", "example007.dxf")
    imported = moz.eval_text(f'linear_extrude(height = 2) import(file = "{dxf}");').measure
    print("DXF 导入      :", imported.facets, "面, 体积", round(imported.volume, 1))
    assert imported.volume > 0

    # 图纸 → 模型（P1）：ezdxf 是可选依赖——装了顺手验一遍，没装必须给可读提示而不是崩掉
    import moz_dxf
    drawing_path = moz.data_path("drawings", "plate.dxf")
    assert os.path.exists(drawing_path), f"随包数据缺失: {drawing_path}"
    try:
        import ezdxf
    except ImportError:
        try:
            moz_dxf.read_dxf(drawing_path)
        except moz.OpenSCADError as exc:
            assert "ezdxf" in str(exc), exc
            print("图纸→模型     : 未装 ezdxf，给出可读提示（符合预期）")
        else:
            raise AssertionError("缺 ezdxf 却没有报错")
    else:
        parsed = moz_dxf.read_dxf(drawing_path)
        volume = parsed.extrude(height=2.0).measure.volume
        print("图纸→模型     :", f"{len(parsed.outlines)} 外 + {len(parsed.holes)} 孔，"
              f"挤出 {volume:.1f} mm³（ezdxf {ezdxf.__version__}）")
        assert volume > 0 and parsed.parameters() == {"bodywidth": 120.0, "plateheight": 40.0}

    image = moz.data_path("examples", "Advanced", "surface_image.png")
    section = moz.projection(
        moz.translate([0, 0, -30], moz.surface(image, center=True)), cut=True
    ).measure
    print("surface 高度图:", section.facets, "个顶点, 面积", round(section.area, 1))
    assert section.area > 0

    print("打包 smoke test 全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
