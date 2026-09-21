"""examples/Old/example009.scad 的忠实 Python 移植。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import moz_openscad as moz

# 原 .scad 与本文件用同一个数据文件（3rd/openscad/examples/Old/ 下），
# Python 版求值没有文档目录，必须写绝对路径。
DATA = Path(__file__).resolve().parents[3] / "3rd" / "openscad" / "examples" / "Old"
DXF = DATA / "example009.dxf"


def build():
    # dxf_dim() 需要取值，用 moz.number 在 SCAD 里求值（同样是绝对路径）。
    fanwidth = moz.number(f'dxf_dim(file = "{DXF}", name = "fanwidth")')
    fanrot = moz.number(f'dxf_dim(file = "{DXF}", name = "fanrot")')

    # 原文件里另外三个从 dxf 里取的值只被下面的 % 背景对象用到，而 % 对象不参与 F6 导出
    # （F6 会跳过 % 对象），因此这里不再求值：
    #   bodywidth  = dxf_dim(file = "example009.dxf", name = "bodywidth")
    #   platewidth = dxf_dim(file = "example009.dxf", name = "platewidth")
    #   fan_side_center = dxf_cross(file = "example009.dxf", layer = "fan_side_center")
    # 原文件里对应的两个 % 背景对象：
    #   % linear_extrude(height = bodywidth, center = true, convexity = 10) import(..., "body");
    #   % for (z = [ +(bodywidth/2 + platewidth/2), -(bodywidth/2 + platewidth/2) ]) { ... "plate" }

    return moz.intersection(
        moz.linear_extrude(moz.import_shape(str(DXF), layer="fan_top"),
                           height=fanwidth, center=True, convexity=10, twist=-fanrot),
        moz.rotate_extrude(
            moz.import_shape(str(DXF), layer="fan_side", origin=[0, -40]),
            angle=360),
    )


if __name__ == "__main__":
    build().show(title="moz - Old/example009")